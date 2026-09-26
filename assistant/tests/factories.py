"""Object factories for tests.

Times come from one fixed reference window so guard boundaries are exact:
START is 16:00 Riyadh on 2026-10-01.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy.orm import Session

from app.config import Policy
from app.domain.booking_state import record_creation
from app.assistant_domain.dates.intents import ResolvedWhen
from app.identity.identity import Identity
from app.laqta.adapter import LaqtaAdapter
from app.laqta.mock import MockLaqta
from app.models import Booking, Contact, Interaction
from app.models.enums import BookingStatus, Channel, ContactSource, IdentityKind, MatchMode
from app.tools.registry import ToolContext

START = datetime(2026, 10, 1, 13, 0, tzinfo=timezone.utc)
END = START + timedelta(hours=7)
PAYMENT_DUE = START - timedelta(days=5)
WELL_BEFORE = START - timedelta(days=30)

# Fri 2026-09-11 14:05 Riyadh — the spec's reference "now".
REFERENCE_NOW = datetime(2026, 9, 11, 11, 5, tzinfo=timezone.utc)
LOCAL_START_HOUR = 16
LOCAL_END_HOUR = 23


def make_contact(session: Session, **overrides) -> Contact:
    fields = {
        "laqta_user_id": uuid.uuid4(),
        "laqta_org_id": uuid.uuid4(),
        "name": "عميل تجريبي",
        "source": ContactSource.chat,
    }
    fields.update(overrides)
    contact = Contact(**fields)
    session.add(contact)
    session.flush()
    return contact


def make_booking(status: BookingStatus | None = None, **overrides) -> Booking:
    """Unsaved by default. `status=None` means "not created yet" — the state
    machine's record_creation() sets the first status."""
    fields = {
        "contact_id": 1,
        "laqta_org_id": uuid.uuid4(),
        "event_name": "ملتقى تجريبي",
        "city": "jeddah",
        "venue": "قاعة",
        "starts_at": START,
        "ends_at": END,
        "expected_guests": 100,
        "photographers": 1,
        "match_mode": MatchMode.face,
        "strict_mode": False,
        "package": "standard",
        "addons": [],
        "onsite_support": False,
        "payment_due_at": PAYMENT_DUE,
        "version": 1,
    }
    fields.update(overrides)
    return Booking(status=status, **fields)


def riyadh_window(
    policy: Policy,
    day: date,
    *,
    start_hour: int = LOCAL_START_HOUR,
    end_hour: int = LOCAL_END_HOUR,
    days: int = 1,
) -> tuple[datetime, datetime]:
    """A local-time event window, as a customer would describe it."""
    tz = policy.tz
    starts_at = datetime.combine(day, time(start_hour), tzinfo=tz)
    ends_at = datetime.combine(day + timedelta(days=days - 1), time(end_hour), tzinfo=tz)
    return starts_at, ends_at


def make_onsite_booking(
    session: Session,
    policy: Policy,
    day: date,
    *,
    contact_id: int,
    days: int = 1,
    city: str = "jeddah",
    now: datetime = REFERENCE_NOW,
    **overrides,
) -> Booking:
    """A saved onsite booking occupying `day` (and the days after it, if
    `days` > 1) — i.e. one that consumes onsite capacity."""
    starts_at, ends_at = riyadh_window(policy, day, days=days)
    fields: dict = {
        "contact_id": contact_id,
        "city": city,
        "onsite_support": True,
        "package": "premium",
        "expected_guests": 400,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "payment_due_at": starts_at - timedelta(days=1),
    }
    fields.update(overrides)  # callers may move the window, e.g. overnight
    booking = make_booking(**fields)
    record_creation(booking, now=now, actor="test")
    session.add(booking)
    session.flush()
    return booking


def customer_identity(contact: Contact) -> Identity:
    return Identity(
        kind="customer",
        contact_id=contact.id,
        laqta_user_id=contact.laqta_user_id,
        laqta_org_id=contact.laqta_org_id,
    )


def make_interaction(
    session: Session, *, identity: Identity, now: datetime = REFERENCE_NOW
) -> Interaction:
    interaction = Interaction(
        contact_id=identity.contact_id,
        staff_id=identity.staff_id,
        channel=Channel.chat,
        identity_kind=IdentityKind(identity.kind),
        started_at=now,
    )
    session.add(interaction)
    session.flush()
    return interaction


def make_tool_context(
    session: Session,
    policy: Policy,
    *,
    identity: Identity,
    laqta: LaqtaAdapter | None = None,
    now: datetime = REFERENCE_NOW,
    user_turn: int = 1,
) -> ToolContext:
    interaction = make_interaction(session, identity=identity, now=now)
    return ToolContext(
        db=session,
        identity=identity,
        interaction_id=interaction.id,
        policy=policy,
        laqta=laqta if laqta is not None else MockLaqta.seeded(),
        now=now,
        user_turn=user_turn,
    )


def make_when(
    policy: Policy,
    day: date,
    *,
    days: int = 1,
    start_hour: int = LOCAL_START_HOUR,
    end_hour: int = LOCAL_END_HOUR,
) -> ResolvedWhen:
    """A resolved window, standing in for the resolver the spec leaves to be
    written by hand (§7). The texts are placeholders, not real formatting."""
    starts_at, ends_at = riyadh_window(
        policy, day, days=days, start_hour=start_hour, end_hour=end_hour
    )
    return ResolvedWhen(
        start=starts_at,
        end=ends_at,
        gregorian_text=f"{day:%Y-%m-%d}",
        hijri_text="غير محسوب",
    )


def register_when(ctx: ToolContext, when: ResolvedWhen) -> str:
    when_id = uuid.uuid4().hex[:8]
    ctx.resolved[when_id] = when
    return when_id
