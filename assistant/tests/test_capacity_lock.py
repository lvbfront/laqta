"""The capacity lock (spec §6): key shape, acquisition order, deadlock
behaviour, and the reschedule recheck. Real Postgres throughout — advisory
locks have no SQLite equivalent.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta

from sqlalchemy import event, text
from sqlalchemy.orm import Session

from app.domain.availability import ONSITE_FULL, AvailabilityRequest
from app.domain.capacity import (
    check_under_lock,
    count_onsite_per_day,
    lock_onsite_days,
    onsite_day_key,
)
from app.domain.booking_state import Trigger, apply
from app.models.enums import BookingStatus
from tests.factories import REFERENCE_NOW as NOW
from tests.factories import make_contact, make_onsite_booking, riyadh_window

DAY_A = date(2026, 10, 5)
DAY_B = date(2026, 10, 6)
DAY_C = date(2026, 10, 7)

LOCK_SQL = "pg_advisory_xact_lock"
THREAD_TIMEOUT = 30


def onsite_request(policy, day: date, *, days: int = 1, city: str = "jeddah", **window) -> AvailabilityRequest:
    starts_at, ends_at = riyadh_window(policy, day, days=days, **window)
    return AvailabilityRequest(
        starts_at=starts_at,
        ends_at=ends_at,
        city=city,
        onsite_support=True,
        expected_guests=400,
        package="premium",
    )


@contextmanager
def captured_locks(session: Session):
    """The advisory-lock keys the session asks for, in order."""
    keys: list[str] = []
    connection = session.connection()

    def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        if LOCK_SQL in statement:
            keys.append(parameters["key"] if isinstance(parameters, dict) else parameters[0])

    event.listen(connection, "before_cursor_execute", before_cursor_execute)
    try:
        yield keys
    finally:
        event.remove(connection, "before_cursor_execute", before_cursor_execute)


# --- The key


def test_lock_key_is_the_city_and_day():
    assert onsite_day_key("jeddah", DAY_A) == "onsite:jeddah:2026-10-05"


def test_different_cities_and_days_are_different_keys():
    keys = {
        onsite_day_key("jeddah", DAY_A),
        onsite_day_key("riyadh", DAY_A),
        onsite_day_key("jeddah", DAY_B),
    }
    assert len(keys) == 3


# --- Acquisition order


def test_locks_are_acquired_in_sorted_day_order(db_session):
    """However the days arrive, they are locked ascending — this is the
    deadlock prevention, tested directly."""
    with captured_locks(db_session) as keys:
        lock_onsite_days(db_session, "jeddah", [DAY_C, DAY_A, DAY_B])
    assert keys == [onsite_day_key("jeddah", day) for day in (DAY_A, DAY_B, DAY_C)]


def test_duplicate_days_are_locked_once(db_session):
    with captured_locks(db_session) as keys:
        lock_onsite_days(db_session, "jeddah", [DAY_A, DAY_A, DAY_B])
    assert keys == [onsite_day_key("jeddah", day) for day in (DAY_A, DAY_B)]


def test_onsite_requests_lock_every_day_they_touch(db_session, policy):
    with captured_locks(db_session) as keys:
        check_under_lock(db_session, onsite_request(policy, DAY_A, days=3), now=NOW, policy=policy)
    assert keys == [onsite_day_key("jeddah", day) for day in (DAY_A, DAY_B, DAY_C)]


def test_an_overnight_multi_day_event_locks_every_date_it_touches(db_session, policy):
    """Three event days ending at 01:00 on the fourth: one day short of
    too_long, but four dates of onsite capacity."""
    starts_at, _ = riyadh_window(policy, DAY_A, start_hour=21)
    ends_at = datetime.combine(
        DAY_A + timedelta(days=policy.max_event_days), time(1), tzinfo=policy.tz
    )
    req = AvailabilityRequest(
        starts_at=starts_at, ends_at=ends_at, city="jeddah", onsite_support=True
    )

    with captured_locks(db_session) as keys:
        result = check_under_lock(db_session, req, now=NOW, policy=policy)

    assert result.ok  # not too_long
    assert len(keys) == policy.max_event_days + 1


def test_remote_requests_take_no_locks(db_session, policy):
    """A remote booking has no capacity to contend for and must not
    serialise behind an onsite one."""
    remote = AvailabilityRequest(
        starts_at=riyadh_window(policy, DAY_A)[0],
        ends_at=riyadh_window(policy, DAY_A)[1],
        city="jeddah",
        onsite_support=False,
    )
    with captured_locks(db_session) as keys:
        result = check_under_lock(db_session, remote, now=NOW, policy=policy)
    assert keys == []
    assert result.ok


def test_unsupported_onsite_city_takes_no_locks(db_session, policy):
    with captured_locks(db_session) as keys:
        check_under_lock(db_session, onsite_request(policy, DAY_A, city="abha"), now=NOW, policy=policy)
    assert keys == []


# --- Counting


def test_counts_only_the_days_an_event_occupies(db_session, policy):
    contact = make_contact(db_session)
    make_onsite_booking(db_session, policy, DAY_A, contact_id=contact.id)

    counts = count_onsite_per_day(db_session, "jeddah", [DAY_A, DAY_B], policy=policy)
    assert counts == {DAY_A: 1, DAY_B: 0}


def test_an_overnight_event_occupies_both_of_its_days(db_session, policy):
    contact = make_contact(db_session)
    starts_at, _ = riyadh_window(policy, DAY_A, start_hour=21)
    ends_at = datetime.combine(DAY_B, time(2), tzinfo=policy.tz)
    make_onsite_booking(
        db_session, policy, DAY_A, contact_id=contact.id, starts_at=starts_at, ends_at=ends_at
    )

    counts = count_onsite_per_day(db_session, "jeddah", [DAY_A, DAY_B], policy=policy)
    assert counts == {DAY_A: 1, DAY_B: 1}


def test_multi_day_events_occupy_every_day(db_session, policy):
    contact = make_contact(db_session)
    make_onsite_booking(db_session, policy, DAY_A, contact_id=contact.id, days=3)

    counts = count_onsite_per_day(db_session, "jeddah", [DAY_A, DAY_B, DAY_C], policy=policy)
    assert counts == {DAY_A: 1, DAY_B: 1, DAY_C: 1}


def test_cancelled_bookings_give_their_slot_back(db_session, policy):
    contact = make_contact(db_session)
    booking = make_onsite_booking(db_session, policy, DAY_A, contact_id=contact.id)
    apply(booking, Trigger.cancel, now=NOW, policy=policy, actor="customer:1")
    db_session.flush()

    assert booking.status is BookingStatus.cancelled
    assert count_onsite_per_day(db_session, "jeddah", [DAY_A], policy=policy) == {DAY_A: 0}


def test_other_cities_do_not_share_capacity(db_session, policy):
    contact = make_contact(db_session)
    make_onsite_booking(db_session, policy, DAY_A, contact_id=contact.id, city="riyadh")

    assert count_onsite_per_day(db_session, "jeddah", [DAY_A], policy=policy) == {DAY_A: 0}


# --- The reschedule recheck


def fill_day(db_session, policy, day: date, *, contact_id: int) -> None:
    for _ in range(policy.onsite.max_events_per_city_per_day):
        make_onsite_booking(db_session, policy, day, contact_id=contact_id)


def test_reschedule_into_a_full_day_is_rejected(db_session, policy):
    """Capacity is rechecked under the lock at the *new* date."""
    contact = make_contact(db_session)
    moving = make_onsite_booking(db_session, policy, DAY_A, contact_id=contact.id)
    fill_day(db_session, policy, DAY_B, contact_id=contact.id)

    result = check_under_lock(
        db_session,
        onsite_request(policy, DAY_B),
        now=NOW,
        policy=policy,
        exclude_booking_id=moving.id,
    )
    assert result.reason == ONSITE_FULL


def test_reschedule_locks_the_new_day(db_session, policy):
    contact = make_contact(db_session)
    moving = make_onsite_booking(db_session, policy, DAY_A, contact_id=contact.id)

    with captured_locks(db_session) as keys:
        check_under_lock(
            db_session, onsite_request(policy, DAY_B), now=NOW, policy=policy,
            exclude_booking_id=moving.id,
        )
    assert keys == [onsite_day_key("jeddah", DAY_B)]


def test_a_booking_does_not_count_against_itself(db_session, policy):
    """Moving to different hours on a day that is at its limit *including*
    this booking must be allowed."""
    contact = make_contact(db_session)
    moving = make_onsite_booking(db_session, policy, DAY_A, contact_id=contact.id)
    for _ in range(policy.onsite.max_events_per_city_per_day - 1):
        make_onsite_booking(db_session, policy, DAY_A, contact_id=contact.id)

    later = onsite_request(policy, DAY_A, start_hour=18, end_hour=23)
    assert check_under_lock(
        db_session, later, now=NOW, policy=policy, exclude_booking_id=moving.id
    ).ok
    # Without the exclusion the same request is full, which is what makes the
    # exclusion necessary rather than cosmetic.
    assert check_under_lock(db_session, later, now=NOW, policy=policy).reason == ONSITE_FULL


# --- Deadlock behaviour


def run_in_threads(targets) -> dict[int, BaseException | None]:
    """Run each target in its own thread, all starting together."""
    barrier = threading.Barrier(len(targets), timeout=THREAD_TIMEOUT)
    outcomes: dict[int, BaseException | None] = {}

    def wrapper(index, target):
        try:
            barrier.wait()
            target()
            outcomes[index] = None
        except BaseException as exc:  # noqa: BLE001 — reported, not swallowed
            outcomes[index] = exc

    threads = [
        threading.Thread(target=wrapper, args=(i, t), daemon=True) for i, t in enumerate(targets)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=THREAD_TIMEOUT)
        assert not thread.is_alive(), "thread did not finish — locks are stuck"
    return outcomes


def is_deadlock(exc: BaseException | None) -> bool:
    return exc is not None and (
        getattr(getattr(exc, "orig", None), "sqlstate", None) == "40P01"
        or "deadlock" in str(exc).lower()
    )


def test_opposite_order_requests_do_not_deadlock(engine, policy):
    """Two overlapping multi-day bookings, asked for in opposite orders. With
    sorted acquisition they serialise; both finish."""

    def attempt(days):
        def run():
            session = Session(engine)
            try:
                with session.begin():
                    lock_onsite_days(session, "jeddah", days)
                    # Hold both locks briefly so the two really contend.
                    session.execute(text("SELECT pg_sleep(0.2)"))
            finally:
                session.close()

        return run

    outcomes = run_in_threads([attempt([DAY_A, DAY_B]), attempt([DAY_B, DAY_A])])
    assert all(exc is None for exc in outcomes.values()), outcomes


def test_unsorted_acquisition_would_deadlock(engine):
    """The control for the test above: acquiring the same two days in
    opposite orders is a real deadlock, so the sort is what prevents it, not
    luck. Postgres kills one side with SQLSTATE 40P01."""
    mid = threading.Barrier(2, timeout=THREAD_TIMEOUT)

    def attempt(first: date, second: date):
        def run():
            session = Session(engine)
            try:
                with session.begin():
                    for day in (first, second):
                        if day is second:
                            mid.wait()  # both now hold their first lock
                        session.execute(
                            text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
                            {"key": onsite_day_key("jeddah", day)},
                        )
            finally:
                session.close()

        return run

    outcomes = run_in_threads([attempt(DAY_A, DAY_B), attempt(DAY_B, DAY_A)])
    assert any(is_deadlock(exc) for exc in outcomes.values()), outcomes
