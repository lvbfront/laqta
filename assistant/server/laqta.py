"""One Laqta for the whole process.

`MockLaqta` is per-instance state, and the CLI and the eval each build their
own — one conversation at a time, so nobody noticed. A web server runs
several at once, and two browser tabs with an instance each would be two
Laqtas: `MockLaqta.seeded(db)` rehydrates `_events` from the `bookings`
table at construction, so a tab only ever sees events that existed when it
started, and a booking made in the other tab a minute later is a
`LaqtaNotFound` to it.

There is only ever one Laqta, so the server builds one hydrated adapter at
startup and hands every session a view onto it. The real HTTP adapter will
be shared the same way, and for the same reason.

Sharing it makes thread safety the server's problem, because sessions run in
Starlette's threadpool. `MockLaqta` is plain dicts and a list: `create_event`
reads `_keys` and then writes it, which is a lost update if two threads
interleave, and `calls.append` on one list from several threads mixes
different conversations together. Both are handled here rather than in
`app/laqta/`, which is right to stay single-threaded — the real adapter will
be an HTTP client, where neither problem exists.
"""

from __future__ import annotations

import threading
import uuid
from datetime import datetime
from typing import Any

from app.laqta.adapter import LaqtaEvent, LaqtaUser
from app.laqta.mock import MockLaqta
from sqlalchemy.orm import Session


class SharedLaqta:
    """The process-wide adapter, plus the lock serialising access to it."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self._lock = threading.Lock()

    @classmethod
    def seeded(cls, db: Session) -> SharedLaqta:
        return cls(MockLaqta.seeded(db))

    def for_session(self) -> SessionLaqta:
        """A per-session view. Every call goes to the one shared adapter; only
        the call log is private, because the dev panel shows one
        conversation's Laqta traffic and not the whole server's."""
        return SessionLaqta(self)

    def call(self, name: str, *args: Any, **kwargs: Any) -> Any:
        with self._lock:
            return getattr(self._inner, name)(*args, **kwargs)

    @property
    def calls(self) -> list[tuple[str, dict]]:
        """Every session's traffic, in arrival order. For debugging the
        server; a session's own calls are on its SessionLaqta."""
        with self._lock:
            return list(self._inner.calls)


class SessionLaqta:
    """Implements LaqtaAdapter. One per AgentSession."""

    def __init__(self, shared: SharedLaqta) -> None:
        self._shared = shared
        self.calls: list[tuple[str, dict]] = []

    def _call(self, name: str, record: dict, *args: Any, **kwargs: Any) -> Any:
        # Recorded before the call, so a raising call is still on the record —
        # that is exactly the one worth seeing in the dev panel.
        self.calls.append((name, record))
        return self._shared.call(name, *args, **kwargs)

    def get_user(self, user_id: uuid.UUID) -> LaqtaUser:
        return self._call("get_user", {"user_id": user_id}, user_id)

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
        fields = {
            "idempotency_key": idempotency_key,
            "org_id": org_id,
            "name_ar": name_ar,
            "starts_at": starts_at,
            "ends_at": ends_at,
            "match_mode": match_mode,
            "privacy_mode": privacy_mode,
        }
        return self._call("create_event", dict(fields), **fields)

    def update_event_window(
        self, event_id: uuid.UUID, starts_at: datetime, ends_at: datetime
    ) -> LaqtaEvent:
        record = {"event_id": event_id, "starts_at": starts_at, "ends_at": ends_at}
        return self._call("update_event_window", record, event_id, starts_at, ends_at)

    def cancel_event(self, event_id: uuid.UUID) -> None:
        return self._call("cancel_event", {"event_id": event_id}, event_id)

    def get_event(self, event_id: uuid.UUID) -> LaqtaEvent:
        return self._call("get_event", {"event_id": event_id}, event_id)

    def calls_named(self, name: str) -> list[dict]:
        return [args for called, args in self.calls if called == name]
