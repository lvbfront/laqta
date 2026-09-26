"""The eval database: `assistant_eval`, and nothing else, ever.

`assistant` holds the repo owner's hand-testing sessions and `assistant_test`
is dropped by every pytest run, so the eval gets its own database. Every
entry point that can write refuses a URL whose database is not exactly
`assistant_eval`.

Between episodes the CRM tables are truncated and re-seeded; `kb_chunks` is
kept, because re-embedding the knowledge base per episode would cost minutes
and change nothing.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.config import ASSISTANT_DIR, KB_PATH, Policy
from app.domain.booking_state import Trigger, apply, record_creation
from app.domain.payment import payment_deadline
from app.models import Booking, Confirmation, Contact, Interaction, Ticket, ToolCall
from app.models.enums import MatchMode
from eval.guard import EVAL_DATABASE, require_eval_database
from eval.personas import SEED_BOOKING_KEY, FixtureBooking, Persona, load_fixtures
from scripts import seed as seed_script

# Laqta event ids for fixture bookings are derived, not random, so the same
# fixture maps to the same mock event in every episode.
_FIXTURE_EVENT_NAMESPACE = uuid.UUID("e7a1e7a1-0000-4000-8000-000000000000")

# scripts/seed.py's organizers, in id order. Checked after every seed: a
# persona's voice (name, gender) is written against these ids.
SEED_CONTACT_NAMES = {1: "أحمد العتيبي", 2: "نورة القحطاني", 3: "فهد الشهري"}


def prepare_database(url: str) -> str:
    """Create if missing, migrate to head, index the KB. Idempotent.
    Returns the KB index report."""
    require_eval_database(url)
    _create_if_missing(url)

    from alembic import command
    from alembic.config import Config

    cfg = Config(str(ASSISTANT_DIR / "alembic.ini"))
    # env.py only falls back to settings.database_url when this is unset.
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")

    from app.kb.chunker import chunk_file
    from app.kb.index import index

    engine = create_engine(url)
    try:
        with Session(engine) as session:
            require_eval_database(session)
            report = index(session, chunk_file(KB_PATH))
            session.commit()
    finally:
        engine.dispose()
    return str(report)


def _create_if_missing(url: str) -> None:
    target = make_url(url)
    admin = create_engine(target.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": EVAL_DATABASE}
            ).first()
            if not exists:
                conn.execute(text(f'CREATE DATABASE "{EVAL_DATABASE}"'))
    finally:
        admin.dispose()


# --- per episode


def reset_and_seed(session: Session, persona: Persona, *, policy: Policy) -> dict[str, str]:
    """Wipe the CRM tables, run the dev seed at the persona's `now`, and add
    the persona's fixtures. Returns fixture key -> booking id, including the
    seed booking, for template rendering and for the scorer.

    Does not check the database name: the caller does, once, at the top of
    the run. Tests call this against `assistant_test` inside a rolled-back
    transaction.
    """
    seed_script.reset(session)
    # RESTART IDENTITY hands out interaction/contact ids the previous
    # episode's objects still hold in the identity map.
    session.expunge_all()
    result =seed_script.seed(session, now=persona.now, policy=policy)

    contacts = {c.id: c for c in result.contacts}
    names = {cid: c.name for cid, c in contacts.items()}
    if names != SEED_CONTACT_NAMES:
        raise RuntimeError(f"scripts/seed.py contacts changed: {names}; personas are written against {SEED_CONTACT_NAMES}")

    booking_ids = {SEED_BOOKING_KEY: str(result.jeddah_booking.id)}
    fixtures = load_fixtures()
    for key in persona.fixtures:
        booking = _add_fixture(session, fixtures[key], contacts[fixtures[key].contact], now=persona.now, policy=policy)
        booking_ids[key] = str(booking.id)

    session.commit()
    return booking_ids


def _add_fixture(session: Session, fixture: FixtureBooking, contact: Contact, *, now: datetime, policy: Policy) -> Booking:
    """Reached through the real state machine, so the booking_events history
    is what the tools would have written."""
    booking = Booking(
        id=uuid.UUID(fixture.id),
        contact_id=contact.id,
        laqta_org_id=contact.laqta_org_id,
        laqta_event_id=uuid.uuid5(_FIXTURE_EVENT_NAMESPACE, fixture.id),
        event_name=fixture.event_name,
        city=fixture.city,
        venue=fixture.venue,
        starts_at=fixture.starts_at,
        ends_at=fixture.ends_at,
        expected_guests=fixture.expected_guests,
        photographers=fixture.photographers,
        match_mode=MatchMode(fixture.match_mode),
        strict_mode=fixture.strict_mode,
        package=fixture.package,
        addons=list(fixture.addons),
        onsite_support=fixture.onsite_support,
        payment_due_at=payment_deadline(tentative_at=fixture.tentative_at, starts_at=fixture.starts_at, policy=policy),
    )
    actor = "eval_fixture"
    record_creation(booking, now=fixture.tentative_at, actor=actor)
    if fixture.status in ("confirmed", "live", "ended"):
        apply(booking, Trigger.mark_paid, now=fixture.tentative_at, policy=policy, actor=actor)
    if fixture.status in ("live", "ended"):
        apply(booking, Trigger.window_open, now=now, policy=policy, actor=actor)
    if fixture.status == "ended":
        apply(booking, Trigger.window_close, now=now, policy=policy, actor=actor)
    if booking.status.value != fixture.status:  # pragma: no cover - guarded by the state machine
        raise RuntimeError(f"fixture {fixture.id} reached {booking.status.value}, not {fixture.status}")

    session.add(booking)
    session.flush()
    return booking


# --- reads the runner needs during and after an episode


def successful_tool_calls(session: Session, interaction_id: int, name: str) -> int:
    return session.scalar(
        select(func.count())
        .select_from(ToolCall)
        .where(ToolCall.interaction_id == interaction_id, ToolCall.name == name, ToolCall.ok.is_(True))
    )


def live_tokens(session: Session, interaction_id: int, *, now: datetime) -> int:
    """Prepared, unused, unexpired confirmations."""
    return session.scalar(
        select(func.count())
        .select_from(Confirmation)
        .where(
            Confirmation.interaction_id == interaction_id,
            Confirmation.used_at.is_(None),
            Confirmation.expires_at > now,
        )
    )


def tool_call_rows_after(session: Session, interaction_id: int, after_id: int) -> list[ToolCall]:
    return list(
        session.scalars(
            select(ToolCall)
            .where(ToolCall.interaction_id == interaction_id, ToolCall.id > after_id)
            .order_by(ToolCall.id)
        ).all()
    )


def last_tool_call_id(session: Session, interaction_id: int) -> int:
    return session.scalar(select(func.coalesce(func.max(ToolCall.id), 0)).where(ToolCall.interaction_id == interaction_id))


def snapshot(session: Session, interaction_id: int) -> dict[str, Any]:
    """Everything the scorer needs from the database, taken before the next
    episode truncates it."""
    session.expire_all()
    bookings = session.scalars(select(Booking).order_by(Booking.starts_at, Booking.id)).all()
    return {
        "bookings": [
            {
                "id": str(b.id),
                "contact_id": b.contact_id,
                "status": b.status.value,
                "event_name": b.event_name,
                "city": b.city,
                "venue": b.venue,
                "starts_at": b.starts_at.isoformat(),
                "ends_at": b.ends_at.isoformat(),
                "expected_guests": b.expected_guests,
                "photographers": b.photographers,
                "match_mode": b.match_mode.value,
                "strict_mode": b.strict_mode,
                "package": b.package,
                "addons": list(b.addons),
                "onsite_support": b.onsite_support,
                "payment_due_at": b.payment_due_at.isoformat(),
                "laqta_event_id": str(b.laqta_event_id) if b.laqta_event_id else None,
                "version": b.version,
                "events": [
                    {
                        "from": e.from_status.value if e.from_status else None,
                        "to": e.to_status.value,
                        "trigger": e.trigger,
                        "actor": e.actor,
                        "reason": e.reason,
                        "at": e.at.isoformat(),
                    }
                    for e in b.events
                ],
            }
            for b in bookings
        ],
        "tickets": [
            {
                "id": t.id,
                "contact_id": t.contact_id,
                "interaction_id": t.interaction_id,
                "team": t.team.value,
                "assignee_staff_id": t.assignee_staff_id,
                "priority": t.priority.value,
                "reason_code": t.reason_code.value,
                "summary": t.summary,
                "status": t.status.value,
                "due_at": t.due_at.isoformat(),
            }
            for t in session.scalars(select(Ticket).order_by(Ticket.id)).all()
        ],
        "confirmations": [
            {
                "id": str(c.id),
                "action": c.action.value,
                "params": c.params,
                "params_hash": c.params_hash,
                "prepared_at_user_turn": c.prepared_at_user_turn,
                "expires_at": c.expires_at.isoformat(),
                "used_at": c.used_at.isoformat() if c.used_at else None,
            }
            for c in session.scalars(
                select(Confirmation).where(Confirmation.interaction_id == interaction_id).order_by(Confirmation.prepared_at_user_turn)
            ).all()
        ],
        "contacts": [
            {"id": c.id, "name": c.name, "phone": c.phone, "source": c.source.value, "has_laqta_account": c.laqta_user_id is not None}
            for c in session.scalars(select(Contact).order_by(Contact.id)).all()
        ],
        "interaction": _interaction(session, interaction_id),
    }


def _interaction(session: Session, interaction_id: int) -> dict[str, Any]:
    row = session.get(Interaction, interaction_id)
    return {"id": row.id, "contact_id": row.contact_id, "identity_kind": row.identity_kind.value}
