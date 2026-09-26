"""The race test (spec §6): five threads, one free onsite slot, real
Postgres. Exactly one may win.

This is the test the advisory lock exists for, so it uses committed data and
real concurrent transactions rather than the rolled-back db_session fixture:
the threads have to be able to see each other's work.
"""

from __future__ import annotations

import threading
import time
from datetime import date

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.domain.availability import ONSITE_FULL, AvailabilityRequest
from app.domain.capacity import check_under_lock, count_onsite_per_day
from app.models import Booking
from scripts.seed import CRM_TABLES
from tests.factories import REFERENCE_NOW as NOW
from tests.factories import make_contact, make_onsite_booking, riyadh_window

THREAD_COUNT = 5
EVENT_DAY = date(2026, 10, 5)  # well past the onsite lead time from NOW
THREAD_TIMEOUT = 60

# Held between the capacity check and the insert, to widen the
# read-then-write window. Under the lock this only delays the single winner.
# Without the lock it guarantees every thread reads "one slot left" before
# any of them inserts -- which is what makes a missing lock fail this test
# every time instead of only when the threads fail to serialise by luck.
READ_TO_WRITE_DELAY = 0.2


def truncate(engine) -> None:
    with engine.connect() as connection:
        connection.execute(text(f"TRUNCATE {', '.join(CRM_TABLES)} RESTART IDENTITY CASCADE"))
        connection.commit()


@pytest.fixture()
def contested_day(engine, policy):
    """One committed onsite booking in Jeddah on EVENT_DAY, leaving exactly
    one slot. Yields the contact id the threads book against."""
    truncate(engine)
    session = Session(engine)
    try:
        contact = make_contact(session)
        make_onsite_booking(session, policy, EVENT_DAY, contact_id=contact.id)
        session.commit()
        contact_id = contact.id
    finally:
        session.close()

    yield contact_id
    truncate(engine)


def request_for_the_day(policy) -> AvailabilityRequest:
    starts_at, ends_at = riyadh_window(policy, EVENT_DAY)
    return AvailabilityRequest(
        starts_at=starts_at,
        ends_at=ends_at,
        city="jeddah",
        onsite_support=True,
        expected_guests=400,
        package="premium",
    )


def run_race(engine, policy, contact_id: int) -> dict[int, object]:
    """Five threads all trying to take the last slot at the same moment.
    Each returns its AvailabilityResult, or the exception it died of."""
    barrier = threading.Barrier(THREAD_COUNT, timeout=THREAD_TIMEOUT)
    outcomes: dict[int, object] = {}

    def attempt(index: int) -> None:
        session = Session(engine)
        try:
            barrier.wait()
            # begin → lock → count → check → create → commit (spec §6).
            with session.begin():
                result = check_under_lock(
                    session, request_for_the_day(policy), now=NOW, policy=policy
                )
                if result.ok:
                    time.sleep(READ_TO_WRITE_DELAY)
                    make_onsite_booking(session, policy, EVENT_DAY, contact_id=contact_id)
            outcomes[index] = result
        except BaseException as exc:  # noqa: BLE001 — surfaced in the assertions
            outcomes[index] = exc
        finally:
            session.close()

    threads = [
        threading.Thread(target=attempt, args=(i,), daemon=True) for i in range(THREAD_COUNT)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=THREAD_TIMEOUT)
        assert not thread.is_alive(), "a thread never finished — the lock is stuck"
    return outcomes


def test_five_threads_contend_for_the_last_onsite_slot(engine, policy, contested_day):
    """Both halves of this matter, and for different reasons.

    The per-thread half says four callers were actually told `onsite_full`.
    The database half is the backstop: it asserts the limit was never
    exceeded even if the per-thread outcomes somehow looked right.

    Both halves are load-bearing, and this was checked rather than assumed:
    monkeypatching lock_onsite_days to a no-op fails this test on every run
    (3/3), at `len(winners) == 1` with all five threads holding ok=True,
    because READ_TO_WRITE_DELAY guarantees all five read "one slot left"
    before any of them inserts. Without that delay the same control passed
    roughly half the time, whenever the threads happened to serialise on
    their own — a race test that only fails sometimes is not a race test.
    """
    outcomes = run_race(engine, policy, contested_day)

    errors = [outcome for outcome in outcomes.values() if isinstance(outcome, BaseException)]
    assert errors == [], errors
    assert len(outcomes) == THREAD_COUNT

    winners = [outcome for outcome in outcomes.values() if outcome.ok]
    losers = [outcome for outcome in outcomes.values() if not outcome.ok]
    assert len(winners) == 1
    assert len(losers) == THREAD_COUNT - 1
    assert {loser.reason for loser in losers} == {ONSITE_FULL}

    limit = policy.onsite.max_events_per_city_per_day
    with Session(engine) as session:
        counts = count_onsite_per_day(session, "jeddah", [EVENT_DAY], policy=policy)
        assert counts[EVENT_DAY] == limit
        assert session.scalar(select(func.count()).select_from(Booking)) == limit


def test_losers_are_offered_other_days(engine, policy, contested_day):
    """A rejected caller gets somewhere to go, not just a refusal."""
    outcomes = run_race(engine, policy, contested_day)
    losers = [outcome for outcome in outcomes.values() if not outcome.ok]

    assert losers
    for loser in losers:
        assert loser.suggestions
        assert all(day > EVENT_DAY for day in loser.suggestions)
