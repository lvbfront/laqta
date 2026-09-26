"""Dev seed (spec §3): a staff org chart, three organizers with Laqta
accounts, and one onsite booking in Jeddah that takes one of that day's
onsite slots — so the next booking there fills it.

    python -m scripts.seed           # idempotent: safe to run repeatedly
    python -m scripts.seed --reset   # wipe the CRM tables first, then seed

Idempotent by natural key: staff by email, contacts by Laqta user id, the
booking by its Laqta event id. Running it twice creates nothing new.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.config import Policy, get_policy
from app.db import SessionLocal
from app.domain.booking_state import Trigger, apply, record_creation
from app.domain.payment import payment_deadline
from app.laqta.fixtures import SEED_JEDDAH_EVENT_ID, SEED_ORGANIZERS
from app.models import Booking, Contact, Staff
from app.models.enums import ContactSource, MatchMode, Team

# --- Fixture data. Sample records, not business rules; every business number
# --- comes from policy.yaml, and the booking below is validated against it.

STAFF: dict[Team, tuple[str, tuple[str, str]]] = {
    Team.sales: ("سارة الدوسري", ("خالد المطيري", "ريم الزهراني")),
    Team.ops: ("ماجد الغامدي", ("عبدالله الحربي", "لمى العنزي")),
    Team.support: ("هند السبيعي", ("تركي القرني", "جود الشمري")),
    Team.privacy: ("منيرة العمري", ("سلطان البقمي", "دانة الرشيد")),
}

JEDDAH_DAYS_AHEAD = 14
JEDDAH_LOCAL_START = time(16, 0)
JEDDAH_LOCAL_END = time(23, 0)
JEDDAH_BOOKING = {
    "event_name": "ملتقى الريّان",
    "city": "jeddah",
    "venue": "فندق هيلتون جدة",
    "expected_guests": 400,
    "photographers": 2,
    "match_mode": MatchMode.face,
    "strict_mode": False,
    "package": "premium",
    "addons": [],
    "onsite_support": True,
}

# Everything seed() writes, plus what references it. kb_chunks is left alone:
# it is rebuilt by scripts/index_kb.py, not seeded.
CRM_TABLES = (
    "booking_events",
    "bookings",
    "confirmations",
    "tool_calls",
    "tickets",
    "interactions",
    "contacts",
    "staff",
    "scheduled_actions",
)


@dataclass(frozen=True)
class SeedResult:
    staff: list[Staff]
    contacts: list[Contact]
    jeddah_booking: Booking


def is_seeded(session: Session) -> bool:
    return session.scalar(select(func.count()).select_from(Contact)) > 0


def reset(session: Session) -> None:
    session.execute(text(f"TRUNCATE {', '.join(CRM_TABLES)} RESTART IDENTITY CASCADE"))


def seed(
    session: Session, *, now: datetime, policy: Policy, jeddah_date: date | None = None
) -> SeedResult:
    staff = _seed_staff(session)
    contacts = _seed_contacts(session)
    booking = _seed_jeddah_booking(
        session, contacts[0], now=now, policy=policy, local_date=jeddah_date
    )
    session.flush()
    return SeedResult(staff=staff, contacts=contacts, jeddah_booking=booking)


def _seed_staff(session: Session) -> list[Staff]:
    rows: list[Staff] = []
    for team, (manager_name, member_names) in STAFF.items():
        manager = _staff_by_email(session, f"{team.value}.manager@laqta.test")
        if manager is None:
            manager = Staff(name=manager_name, email=f"{team.value}.manager@laqta.test", team=team)
            session.add(manager)
            session.flush()  # members need manager.id
        rows.append(manager)

        for i, member_name in enumerate(member_names, start=1):
            email = f"{team.value}.{i}@laqta.test"
            member = _staff_by_email(session, email)
            if member is None:
                member = Staff(name=member_name, email=email, team=team, manager_id=manager.id)
                session.add(member)
            rows.append(member)
    session.flush()
    return rows


def _staff_by_email(session: Session, email: str) -> Staff | None:
    return session.scalar(select(Staff).where(Staff.email == email))


def _seed_contacts(session: Session) -> list[Contact]:
    rows: list[Contact] = []
    for organizer in SEED_ORGANIZERS:
        contact = session.scalar(
            select(Contact).where(Contact.laqta_user_id == organizer.user.id)
        )
        if contact is None:
            contact = Contact(
                laqta_user_id=organizer.user.id,
                laqta_org_id=organizer.user.org_id,
                name=organizer.name,
                phone=organizer.phone,
                email=organizer.user.email,
                org_name=organizer.org_name,
                source=ContactSource.staff,
            )
            session.add(contact)
        rows.append(contact)
    session.flush()
    return rows


def _seed_jeddah_booking(
    session: Session, contact: Contact, *, now: datetime, policy: Policy, local_date: date | None
) -> Booking:
    existing = session.scalar(
        select(Booking).where(Booking.laqta_event_id == SEED_JEDDAH_EVENT_ID)
    )
    if existing is not None:
        return existing

    tz = policy.tz
    if local_date is None:
        local_date = now.astimezone(tz).date() + timedelta(days=JEDDAH_DAYS_AHEAD)
    starts_at = datetime.combine(local_date, JEDDAH_LOCAL_START, tzinfo=tz).astimezone(timezone.utc)
    ends_at = datetime.combine(local_date, JEDDAH_LOCAL_END, tzinfo=tz).astimezone(timezone.utc)

    # Fail loudly rather than seed a booking the rules would never have
    # allowed — e.g. after a policy.yaml change.
    if starts_at - now < timedelta(hours=policy.lead_time_hours.onsite):
        raise ValueError(f"seed booking on {local_date} is inside the onsite lead time")
    if JEDDAH_BOOKING["city"] not in policy.onsite.cities:
        raise ValueError("seed booking city does not offer onsite support")
    if JEDDAH_BOOKING["package"] not in policy.onsite.included_in:
        raise ValueError("seed booking package does not include onsite support")

    payment_due_at = payment_deadline(tentative_at=now, starts_at=starts_at, policy=policy)
    booking = Booking(
        contact_id=contact.id,
        laqta_org_id=contact.laqta_org_id,
        laqta_event_id=SEED_JEDDAH_EVENT_ID,
        starts_at=starts_at,
        ends_at=ends_at,
        payment_due_at=payment_due_at,
        **JEDDAH_BOOKING,
    )
    # Through the state machine, so the seeded history is the real thing.
    record_creation(booking, now=now, actor="seed")
    apply(booking, Trigger.mark_paid, now=now, policy=policy, actor="seed")
    session.add(booking)
    session.flush()
    return booking


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--reset", action="store_true", help="wipe CRM tables before seeding")
    args = parser.parse_args(argv)

    policy = get_policy()
    with SessionLocal() as session:
        db_name = session.get_bind().url.database or ""
        if not db_name.startswith("assistant"):
            print(f"refusing to seed {db_name!r}: not an assistant database", file=sys.stderr)
            return 1
        if args.reset:
            reset(session)

        result = seed(session, now=datetime.now(timezone.utc), policy=policy)
        session.commit()

        booking = result.jeddah_booking
        print(f"seeded {db_name}: {len(result.staff)} staff, {len(result.contacts)} contacts")
        for contact in result.contacts:
            print(f"  --as customer:{contact.id}  {contact.name} ({contact.org_name})")
        print(
            f"  onsite booking {booking.id} in {booking.city}, "
            f"{booking.starts_at.astimezone(policy.tz):%Y-%m-%d %H:%M} Riyadh ({booking.status.value})"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
