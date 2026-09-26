"""In-memory Laqta (spec §9).

Dicts plus a call log, so tests can assert what the assistant asked Laqta to
do. The real v2 implementation replaces this with a thin HTTP layer against
the same LaqtaAdapter protocol.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.laqta.adapter import LaqtaEvent, LaqtaNotFound, LaqtaUser
from app.laqta.fixtures import SEED_ORGANIZERS

# Laqta's own EventStatus values (api/app/models/enums.py).
STATUS_DRAFT = "draft"
STATUS_CLOSED = "closed"


class MockLaqta:
    def __init__(
        self,
        users: Iterable[LaqtaUser] = (),
        events: Iterable[LaqtaEvent] = (),
    ) -> None:
        self._users: dict[uuid.UUID, LaqtaUser] = {user.id: user for user in users}
        self._events: dict[uuid.UUID, LaqtaEvent] = {event.id: event for event in events}
        # idempotency_key -> event id (spec §9: the key is booking.id)
        self._keys: dict[str, uuid.UUID] = {}
        self.calls: list[tuple[str, dict]] = []

    @classmethod
    def seeded(cls, session: Session | None = None) -> MockLaqta:
        """The seeded organizers' accounts, plus — if a session is given —
        a Laqta event for every booking that already has one.

        The rehydration matters because this adapter is in-memory: without
        it, a booking created in one CLI run would reference an event the
        next run has never heard of.
        """
        mock = cls(users=[organizer.user for organizer in SEED_ORGANIZERS])
        if session is not None:
            mock.hydrate_from_bookings(session)
        return mock

    def hydrate_from_bookings(self, session: Session) -> None:
        from app.models import Booking  # local: avoids a models→laqta import cycle

        bookings = session.scalars(
            select(Booking).where(Booking.laqta_event_id.is_not(None))
        ).all()
        for booking in bookings:
            self._events[booking.laqta_event_id] = LaqtaEvent(
                id=booking.laqta_event_id,
                org_id=booking.laqta_org_id,
                name_ar=booking.event_name,
                starts_at=booking.starts_at,
                ends_at=booking.ends_at,
                match_mode=booking.match_mode.value,
                privacy_mode="strict" if booking.strict_mode else "standard",
                status=STATUS_DRAFT,
            )
            self._keys[str(booking.id)] = booking.laqta_event_id

    # --- LaqtaAdapter

    def get_user(self, user_id: uuid.UUID) -> LaqtaUser:
        self.calls.append(("get_user", {"user_id": user_id}))
        try:
            return self._users[user_id]
        except KeyError:
            raise LaqtaNotFound(f"no Laqta user {user_id}") from None

    def create_event(
        self,
        *,
        idempotency_key: str,
        org_id: uuid.UUID,
        name_ar: str,
        starts_at: datetime,
        ends_at: datetime,
        match_mode: str,
        privacy_mode: str,
    ) -> LaqtaEvent:
        self.calls.append(
            (
                "create_event",
                {
                    "idempotency_key": idempotency_key,
                    "org_id": org_id,
                    "name_ar": name_ar,
                    "starts_at": starts_at,
                    "ends_at": ends_at,
                    "match_mode": match_mode,
                    "privacy_mode": privacy_mode,
                },
            )
        )
        existing = self._keys.get(idempotency_key)
        if existing is not None:
            # Same key twice returns the same event and creates nothing.
            return self._events[existing]

        event = LaqtaEvent(
            id=uuid.uuid4(),
            org_id=org_id,
            name_ar=name_ar,
            starts_at=starts_at,
            ends_at=ends_at,
            match_mode=match_mode,
            privacy_mode=privacy_mode,
            status=STATUS_DRAFT,
        )
        self._events[event.id] = event
        self._keys[idempotency_key] = event.id
        return event

    def update_event_window(
        self, event_id: uuid.UUID, starts_at: datetime, ends_at: datetime
    ) -> LaqtaEvent:
        self.calls.append(
            ("update_event_window", {"event_id": event_id, "starts_at": starts_at, "ends_at": ends_at})
        )
        event = self._require(event_id)
        updated = LaqtaEvent(
            id=event.id,
            org_id=event.org_id,
            name_ar=event.name_ar,
            starts_at=starts_at,
            ends_at=ends_at,
            match_mode=event.match_mode,
            privacy_mode=event.privacy_mode,
            status=event.status,
        )
        self._events[event_id] = updated
        return updated

    def cancel_event(self, event_id: uuid.UUID) -> None:
        self.calls.append(("cancel_event", {"event_id": event_id}))
        event = self._require(event_id)
        self._events[event_id] = LaqtaEvent(
            id=event.id,
            org_id=event.org_id,
            name_ar=event.name_ar,
            starts_at=event.starts_at,
            ends_at=event.ends_at,
            match_mode=event.match_mode,
            privacy_mode=event.privacy_mode,
            status=STATUS_CLOSED,
        )

    def get_event(self, event_id: uuid.UUID) -> LaqtaEvent:
        self.calls.append(("get_event", {"event_id": event_id}))
        return self._require(event_id)

    # --- test helpers

    def calls_named(self, name: str) -> list[dict]:
        return [args for called, args in self.calls if called == name]

    def _require(self, event_id: uuid.UUID) -> LaqtaEvent:
        try:
            return self._events[event_id]
        except KeyError:
            raise LaqtaNotFound(f"no Laqta event {event_id}") from None
