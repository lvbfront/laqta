"""Only confirm_action and handoff_to_staff may change anything (spec §8).

The prepare_* tools do write one row — their confirmation token, which is
the mechanism itself (§8) — and nothing else: no booking, no ticket, no
transition, no contact, and no call to Laqta. That is what this pins down.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy import func, select

from app.config import EMBEDDING_DIM
from app.identity.identity import Identity
from app.models import (
    Booking,
    BookingEvent,
    Confirmation,
    Contact,
    Interaction,
    KBChunk,
    ScheduledAction,
    Staff,
    Ticket,
)
from app.tools import registry
from tests.factories import REFERENCE_NOW as NOW
from tests.factories import (
    customer_identity,
    make_contact,
    make_onsite_booking,
    make_tool_context,
    make_when,
    register_when,
)

# Everything a tool could touch. tool_calls is excluded: every call is logged
# by design, and confirmations is counted separately below.
WATCHED = (Booking, BookingEvent, Contact, Interaction, Staff, Ticket, ScheduledAction, KBChunk)

FAR_DAY = date(2026, 10, 15)
DETAILS = {
    "event_name": "فعالية",
    "city": "jeddah",
    "venue": "قاعة",
    "expected_guests": 200,
    "photographers": 1,
    "match_mode": "face",
    "strict_mode": False,
    "package": "standard",
    "addons": [],
    "onsite_support": False,
}


# Server-set clocks, not something a tool decides.
IGNORED_COLUMNS = {"created_at", "updated_at"}


def booking_rows(db) -> list[tuple[str, ...]]:
    """Every column of every booking.

    Deliberately not a handful of fields: a tool quietly rewriting a venue or
    a payment deadline would slip past a narrower check, and because the
    version counter is application-supplied it would not move either.
    """
    names = [
        column.name for column in Booking.__table__.columns if column.name not in IGNORED_COLUMNS
    ]
    rows = db.execute(select(*(getattr(Booking, name) for name in names))).all()
    return sorted(tuple(str(value) for value in row) for row in rows)


@pytest.fixture(autouse=True)
def stub_embeddings(monkeypatch):
    """This file is about writes, not relevance — keep the 2GB model out of
    it. tests/test_kb_retrieval.py uses the real one."""
    monkeypatch.setattr(
        "app.kb.search.embed_query", lambda text: [1.0] + [0.0] * (EMBEDDING_DIM - 1)
    )


def snapshot(db) -> dict:
    counts = {
        model.__name__: db.scalar(select(func.count()).select_from(model)) for model in WATCHED
    }
    # Bookings can be mutated rather than added, so compare their contents.
    counts["bookings_content"] = booking_rows(db)
    return counts


@pytest.fixture()
def scene(db_session, policy):
    """A customer with one existing booking, and a when_id to aim at."""
    contact = make_contact(db_session)
    booking = make_onsite_booking(
        db_session, policy, date(2026, 11, 10), contact_id=contact.id, onsite_support=False
    )
    ctx = make_tool_context(db_session, policy, identity=customer_identity(contact))
    when_id = register_when(ctx, make_when(policy, FAR_DAY))
    db_session.flush()
    return ctx, booking, when_id


READ_ONLY_CALLS = {
    "search_kb": lambda booking, when_id: {"query": "وش الباقات المتوفرة؟"},
    "get_my_bookings": lambda booking, when_id: {},
    "check_availability": lambda booking, when_id: {"when_id": when_id, "city": "jeddah"},
    "prepare_booking": lambda booking, when_id: {"when_id": when_id, "details": DETAILS},
    "prepare_reschedule": lambda booking, when_id: {
        "booking_id": str(booking.id),
        "when_id": when_id,
    },
    "prepare_cancel": lambda booking, when_id: {"booking_id": str(booking.id)},
    # Crashes (the resolver is hand-written and not implemented yet), which
    # is itself worth pinning: the rollback must leave nothing behind.
    "resolve_when": lambda booking, when_id: {
        "date": {"kind": "relative_day", "offset": 1},
        "start_time": {"kind": "clock", "hour": 8, "minute": 0, "period": "pm"},
        "end_time": {"kind": "clock", "hour": 11, "minute": 0, "period": "pm"},
    },
}

PREPARE_TOOLS = {"prepare_booking", "prepare_reschedule", "prepare_cancel"}


def test_the_registry_agrees_about_which_tools_have_side_effects():
    declared = {tool.name for tool in registry.all_tools() if tool.side_effects}
    assert declared == {"confirm_action", "handoff_to_staff"}
    assert declared.isdisjoint(READ_ONLY_CALLS)


@pytest.mark.parametrize("tool_name", sorted(READ_ONLY_CALLS))
def test_read_only_tools_change_nothing(scene, db_session, tool_name):
    ctx, booking, when_id = scene
    before = snapshot(db_session)
    confirmations_before = db_session.scalar(select(func.count()).select_from(Confirmation))

    result = registry.execute(tool_name, READ_ONLY_CALLS[tool_name](booking, when_id), ctx=ctx)

    assert snapshot(db_session) == before
    assert ctx.laqta.calls == []

    confirmations_after = db_session.scalar(select(func.count()).select_from(Confirmation))
    expected_tokens = 1 if (tool_name in PREPARE_TOOLS and result["ok"]) else 0
    assert confirmations_after - confirmations_before == expected_tokens


def test_a_refused_prepare_writes_no_token(scene, db_session, policy):
    """An unavailable date must not leave a confirmation lying around."""
    ctx, booking, _ = scene
    past = register_when(ctx, make_when(policy, (NOW - timedelta(days=1)).date()))
    before = db_session.scalar(select(func.count()).select_from(Confirmation))

    result = registry.execute(
        "prepare_booking", {"when_id": past, "details": DETAILS}, ctx=ctx
    )
    assert result["ok"] is False
    assert db_session.scalar(select(func.count()).select_from(Confirmation)) == before


def test_a_forbidden_call_changes_nothing(db_session, policy):
    anon_ctx = make_tool_context(db_session, policy, identity=Identity(kind="anonymous"))
    before = snapshot(db_session)
    registry.execute("prepare_cancel", {"booking_id": str(uuid.uuid4())}, ctx=anon_ctx)
    assert snapshot(db_session) == before


def test_confirm_action_is_the_one_that_writes(scene, db_session, policy):
    """The counterpart: the tools above change nothing, and this one does."""
    ctx, _, when_id = scene
    prepared = registry.execute(
        "prepare_booking", {"when_id": when_id, "details": DETAILS}, ctx=ctx
    )
    before = snapshot(db_session)

    ctx.user_turn += 1
    result = registry.execute(
        "confirm_action", {"confirmation_id": prepared["data"]["confirmation_id"]}, ctx=ctx
    )

    assert result["ok"] is True
    after = snapshot(db_session)
    assert after["Booking"] == before["Booking"] + 1
    assert after["BookingEvent"] == before["BookingEvent"] + 1
    assert ctx.laqta.calls_named("create_event")
