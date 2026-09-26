"""One Laqta for the whole process, reached from several threads.

Two claims, and they need different kinds of test. That the adapter is
*shared* is a claim about what one session can see of another's work, and
it is tested by booking in one session and reading the event from a session
that started first. That access to it is *serialised* is a claim about two
threads, and a test that only fires threads at it would pass without a lock
most of the time — so the stand-in adapter pauses between its read and its
write, the way `test_capacity_race` does, and makes the failure certain.
"""

from __future__ import annotations

import threading
import time
import uuid
from datetime import date

import pytest
from sqlalchemy import select

from app.agent.loop import run_turn
from app.agent.session import AgentSession
from app.laqta.adapter import LaqtaNotFound
from app.laqta.mock import MockLaqta
from app.models import Booking, Confirmation
from server.laqta import SharedLaqta
from tests.factories import REFERENCE_NOW as NOW
from tests.factories import customer_identity, make_contact, make_when
from tests.fakes import FakeClient, calls_tool, says

FAR_DAY = date(2026, 10, 15)
WHEN_ID = "w0000001"
DETAILS = {
    "event_name": "ملتقى الريّان",
    "city": "jeddah",
    "venue": "فندق هيلتون جدة",
    "expected_guests": 400,
    "photographers": 2,
    "match_mode": "face",
    "strict_mode": False,
    "package": "premium",
    "addons": [],
    "onsite_support": False,
}

# Long enough that an unlocked interleaving is certain rather than likely.
READ_TO_WRITE_DELAY = 0.05


def start_session(db_session, policy, laqta):
    contact = make_contact(db_session)
    agent = AgentSession.start(
        db_session,
        identity=customer_identity(contact),
        policy=policy,
        laqta=laqta,
        now=NOW,
    )
    agent.resolved[WHEN_ID] = make_when(policy, FAR_DAY)
    return agent


def book(session, db_session):
    """Two turns, because one is what the confirmation rule forbids."""
    run_turn(
        session,
        "أبي أحجز",
        now=NOW,
        client=FakeClient(
            calls_tool("prepare_booking", {"when_id": WHEN_ID, "details": DETAILS}),
            says("الملخص: … أأكد؟"),
        ),
    )
    token = db_session.scalars(
        select(Confirmation).order_by(Confirmation.prepared_at_user_turn.desc())
    ).first()
    run_turn(
        session,
        "نعم",
        now=NOW,
        client=FakeClient(
            calls_tool("confirm_action", {"confirmation_id": str(token.id)}),
            says("تم."),
        ),
    )
    booking = db_session.scalars(select(Booking)).all()[-1]
    assert booking.laqta_event_id is not None, "the booking never reached Laqta"
    return booking


# --- Shared state


def test_a_session_sees_an_event_another_session_created(db_session, policy):
    """Session B starts first, so nothing it hydrated at startup could
    contain A's event. It still has to find it."""
    shared = SharedLaqta.seeded(db_session)
    session_b = start_session(db_session, policy, shared.for_session())
    session_a = start_session(db_session, policy, shared.for_session())

    booking = book(session_a, db_session)

    event = session_b.laqta.get_event(booking.laqta_event_id)
    assert event.name_ar == DETAILS["event_name"]
    assert event.id == booking.laqta_event_id


def test_the_old_per_session_adapter_is_what_this_replaces(db_session, policy):
    """The control, pinning why the sharing exists. Give each session its own
    MockLaqta — what the CLI and the eval do, one conversation at a time —
    and B cannot see A's event at all."""
    session_b = start_session(db_session, policy, MockLaqta.seeded(db_session))
    session_a = start_session(db_session, policy, MockLaqta.seeded(db_session))

    booking = book(session_a, db_session)

    with pytest.raises(LaqtaNotFound):
        session_b.laqta.get_event(booking.laqta_event_id)


def test_each_session_keeps_its_own_call_log(db_session, policy):
    """The adapter is shared; the record of who asked for what is not, or the
    dev panel would show every conversation on the server."""
    shared = SharedLaqta.seeded(db_session)
    session_a = start_session(db_session, policy, shared.for_session())
    session_b = start_session(db_session, policy, shared.for_session())

    booking = book(session_a, db_session)
    session_b.laqta.get_event(booking.laqta_event_id)

    assert [name for name, _ in session_b.laqta.calls] == ["get_event"]
    assert "create_event" in [name for name, _ in session_a.laqta.calls]
    assert len(shared.calls) == len(session_a.laqta.calls) + len(session_b.laqta.calls)


# --- Serialised access


class PausesBetweenReadAndWrite:
    """A stand-in for the adapter whose read-then-write is the shape of
    MockLaqta.create_event: it looks up the idempotency key, then stores one.
    Unlocked, two threads both read the same value and one write is lost."""

    def __init__(self) -> None:
        self.value = 0
        self.calls: list[tuple[str, dict]] = []

    def get_user(self, user_id):
        seen = self.value
        time.sleep(READ_TO_WRITE_DELAY)
        self.value = seen + 1
        self.calls.append(("get_user", {"user_id": user_id}))
        return seen


def test_threads_do_not_interleave_inside_the_adapter():
    shared = SharedLaqta(PausesBetweenReadAndWrite())
    threads = [
        threading.Thread(target=lambda: shared.for_session().get_user(uuid.uuid4()))
        for _ in range(5)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert shared._inner.value == 5, "a write was lost: the calls overlapped"
    assert len(shared.calls) == 5
