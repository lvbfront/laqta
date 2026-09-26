from __future__ import annotations

import uuid
from datetime import timedelta
from itertools import product

import pytest
from sqlalchemy import text
from sqlalchemy.orm.exc import StaleDataError

from app.domain.booking_state import (
    CREATION_TRIGGER,
    TRANSITIONS,
    GuardFailed,
    InvalidTransition,
    Trigger,
    apply,
    record_creation,
)
from app.models import Booking
from app.models.enums import BookingStatus as Status
from tests.factories import END, PAYMENT_DUE, START, WELL_BEFORE, make_booking, make_contact

ONE_SECOND = timedelta(seconds=1)
NEW_WINDOW = (START + timedelta(days=7), END + timedelta(days=7))

# Spec §5's table, transcribed by hand. If this and TRANSITIONS disagree, one
# of them is wrong — which is the point of test_transition_table_matches_spec.
SPEC_TABLE = {
    (Status.tentative, Trigger.mark_paid): Status.confirmed,
    (Status.tentative, Trigger.payment_expired): Status.cancelled,
    (Status.tentative, Trigger.cancel): Status.cancelled,
    (Status.confirmed, Trigger.cancel): Status.cancelled,
    (Status.tentative, Trigger.reschedule): Status.tentative,
    (Status.confirmed, Trigger.reschedule): Status.confirmed,
    (Status.confirmed, Trigger.window_open): Status.live,
    (Status.live, Trigger.window_close): Status.ended,
}


def now_satisfying(trigger: Trigger, policy) -> object:
    """A `now` where this trigger's guard passes — exactly on the boundary
    where it has one."""
    return {
        Trigger.mark_paid: WELL_BEFORE,
        Trigger.cancel: WELL_BEFORE,
        Trigger.payment_expired: PAYMENT_DUE,
        Trigger.reschedule: START - timedelta(hours=policy.free_reschedule_before_hours),
        Trigger.window_open: START - timedelta(hours=policy.upload_opens_before_hours),
        Trigger.window_close: END + timedelta(hours=policy.upload_closes_after_hours),
    }[trigger]


def kwargs_for(trigger: Trigger) -> dict:
    return {"new_window": NEW_WINDOW} if trigger is Trigger.reschedule else {}


# --- The table itself


def test_transition_table_matches_spec():
    actual = {key: (t.to if t.to is not None else key[0]) for key, t in TRANSITIONS.items()}
    assert actual == SPEC_TABLE


def test_every_trigger_is_a_live_transition():
    """No member of Trigger is dead: each one appears in the table."""
    assert {trigger for _, trigger in TRANSITIONS} == set(Trigger)


def test_creation_trigger_is_not_a_live_trigger():
    # It creates the booking; it never moves an existing one, so it is not a
    # Trigger and apply() has no way to accept it.
    assert CREATION_TRIGGER not in {trigger.value for trigger in Trigger}


@pytest.mark.parametrize("status,trigger", list(product(Status, Trigger)))
def test_every_state_trigger_pair(status, trigger, policy):
    """The full cartesian product: exactly the pairs in the table succeed,
    every other pair raises InvalidTransition and changes nothing."""
    booking = make_booking(status)
    now = now_satisfying(trigger, policy)

    if (status, trigger) in SPEC_TABLE:
        apply(booking, trigger, now=now, policy=policy, actor="test", **kwargs_for(trigger))
        assert booking.status is SPEC_TABLE[(status, trigger)]
        assert booking.version == 2
        assert len(booking.events) == 1
    else:
        with pytest.raises(InvalidTransition):
            apply(booking, trigger, now=now, policy=policy, actor="test", **kwargs_for(trigger))
        assert booking.status is status
        assert booking.version == 1
        assert booking.events == []


# --- Guards


def test_payment_expires_exactly_at_the_deadline(policy):
    booking = make_booking(Status.tentative)
    apply(booking, Trigger.payment_expired, now=PAYMENT_DUE, policy=policy, actor="clock")
    assert booking.status is Status.cancelled


def test_payment_does_not_expire_a_second_early(policy):
    booking = make_booking(Status.tentative)
    with pytest.raises(GuardFailed, match="payment_deadline_passed"):
        apply(
            booking, Trigger.payment_expired, now=PAYMENT_DUE - ONE_SECOND, policy=policy, actor="clock"
        )
    assert booking.status is Status.tentative
    assert booking.version == 1
    assert booking.events == []


def test_reschedule_refused_past_the_free_cutoff(policy):
    booking = make_booking(Status.confirmed)
    cutoff = START - timedelta(hours=policy.free_reschedule_before_hours)
    with pytest.raises(GuardFailed, match="before_free_reschedule_cutoff"):
        apply(
            booking,
            Trigger.reschedule,
            now=cutoff + ONE_SECOND,
            policy=policy,
            actor="customer:1",
            new_window=NEW_WINDOW,
        )
    assert booking.starts_at == START


def test_window_opens_exactly_at_the_policy_offset(policy):
    booking = make_booking(Status.confirmed)
    opens = START - timedelta(hours=policy.upload_opens_before_hours)
    with pytest.raises(GuardFailed, match="upload_window_due_to_open"):
        apply(booking, Trigger.window_open, now=opens - ONE_SECOND, policy=policy, actor="clock")
    apply(booking, Trigger.window_open, now=opens, policy=policy, actor="clock")
    assert booking.status is Status.live


def test_window_closes_exactly_at_the_policy_offset(policy):
    booking = make_booking(Status.live)
    closes = END + timedelta(hours=policy.upload_closes_after_hours)
    with pytest.raises(GuardFailed, match="upload_window_due_to_close"):
        apply(booking, Trigger.window_close, now=closes - ONE_SECOND, policy=policy, actor="clock")
    apply(booking, Trigger.window_close, now=closes, policy=policy, actor="clock")
    assert booking.status is Status.ended


# --- Reschedule specifics


def test_reschedule_keeps_status_and_writes_the_new_window(policy):
    booking = make_booking(Status.confirmed)
    now = START - timedelta(hours=policy.free_reschedule_before_hours)
    apply(
        booking, Trigger.reschedule, now=now, policy=policy, actor="customer:1", new_window=NEW_WINDOW
    )
    assert booking.status is Status.confirmed
    assert (booking.starts_at, booking.ends_at) == NEW_WINDOW
    event = booking.events[-1]
    assert (event.from_status, event.to_status) == (Status.confirmed, Status.confirmed)
    # The default reason records what moved, since booking_events has no
    # columns for the window.
    assert START.isoformat() in event.reason and NEW_WINDOW[0].isoformat() in event.reason


def test_reschedule_cutoff_is_measured_against_the_old_start(policy):
    """Moving to a far-future date does not buy you a later cutoff."""
    booking = make_booking(Status.confirmed)
    too_late = START - timedelta(hours=policy.free_reschedule_before_hours) + ONE_SECOND
    with pytest.raises(GuardFailed):
        apply(
            booking,
            Trigger.reschedule,
            now=too_late,
            policy=policy,
            actor="customer:1",
            new_window=(START + timedelta(days=90), END + timedelta(days=90)),
        )


def test_reschedule_needs_a_window(policy):
    booking = make_booking(Status.confirmed)
    with pytest.raises(ValueError, match="new_window"):
        apply(booking, Trigger.reschedule, now=WELL_BEFORE, policy=policy, actor="customer:1")


def test_other_triggers_reject_a_window(policy):
    booking = make_booking(Status.tentative)
    with pytest.raises(ValueError, match="new_window"):
        apply(
            booking, Trigger.mark_paid, now=WELL_BEFORE, policy=policy, actor="staff:1",
            new_window=NEW_WINDOW,
        )


def test_reversed_window_is_rejected(policy):
    booking = make_booking(Status.confirmed)
    now = START - timedelta(hours=policy.free_reschedule_before_hours)
    with pytest.raises(ValueError, match="ends before"):
        apply(
            booking, Trigger.reschedule, now=now, policy=policy, actor="customer:1",
            new_window=(NEW_WINDOW[1], NEW_WINDOW[0]),
        )


# --- Creation and history


def test_record_creation_starts_at_tentative():
    booking = make_booking()
    record_creation(booking, now=WELL_BEFORE, actor="customer:1")
    assert booking.status is Status.tentative
    assert booking.version == 1
    event = booking.events[0]
    assert (event.from_status, event.to_status) == (None, Status.tentative)
    assert event.trigger == CREATION_TRIGGER
    assert event.at == WELL_BEFORE


def test_record_creation_refuses_an_existing_booking():
    booking = make_booking(Status.tentative)
    with pytest.raises(InvalidTransition):
        record_creation(booking, now=WELL_BEFORE, actor="customer:1")


def test_full_lifecycle(policy):
    booking = make_booking()
    record_creation(booking, now=WELL_BEFORE, actor="customer:1")
    apply(booking, Trigger.mark_paid, now=WELL_BEFORE, policy=policy, actor="staff:1")
    apply(
        booking, Trigger.window_open,
        now=START - timedelta(hours=policy.upload_opens_before_hours), policy=policy, actor="clock",
    )
    apply(
        booking, Trigger.window_close,
        now=END + timedelta(hours=policy.upload_closes_after_hours), policy=policy, actor="clock",
    )
    assert booking.status is Status.ended
    assert booking.version == 4
    assert [e.trigger for e in booking.events] == [
        "confirm_booking", "mark_paid", "window_open", "window_close",
    ]
    assert [(e.from_status, e.to_status) for e in booking.events] == [
        (None, Status.tentative),
        (Status.tentative, Status.confirmed),
        (Status.confirmed, Status.live),
        (Status.live, Status.ended),
    ]


def test_event_records_actor_reason_and_time(policy):
    booking = make_booking(Status.confirmed)
    apply(
        booking, Trigger.cancel, now=WELL_BEFORE, policy=policy, actor="customer:7",
        reason="العميل ألغى الفعالية",
    )
    event = booking.events[-1]
    assert (event.actor, event.reason, event.at) == ("customer:7", "العميل ألغى الفعالية", WELL_BEFORE)


# --- Persistence and optimistic locking


@pytest.fixture()
def saved_booking(db_session) -> Booking:
    contact = make_contact(db_session)
    booking = make_booking(contact_id=contact.id, laqta_org_id=contact.laqta_org_id)
    record_creation(booking, now=WELL_BEFORE, actor="seed")
    db_session.add(booking)
    db_session.flush()
    return booking


def test_events_are_persisted_with_the_booking(db_session, saved_booking, policy):
    apply(saved_booking, Trigger.mark_paid, now=WELL_BEFORE, policy=policy, actor="staff:1")
    db_session.flush()
    db_session.expire_all()

    reloaded = db_session.get(Booking, saved_booking.id)
    assert reloaded.status is Status.confirmed
    assert reloaded.version == 2
    assert [e.trigger for e in reloaded.events] == ["confirm_booking", "mark_paid"]


def test_a_stale_writer_is_rejected(db_session, saved_booking, policy):
    """Another writer advanced the row after we read it: our UPDATE must fail
    rather than silently overwrite theirs.

    Raw SQL, deliberately: an ORM-enabled update() would synchronize the new
    version back into this session's identity map, which is exactly the
    staleness the test is trying to create.
    """
    db_session.execute(
        text("UPDATE bookings SET version = version + 1 WHERE id = :id"),
        {"id": saved_booking.id},
    )
    apply(saved_booking, Trigger.mark_paid, now=WELL_BEFORE, policy=policy, actor="staff:1")
    with pytest.raises(StaleDataError):
        db_session.flush()


def test_a_plain_field_update_needs_no_version_bump(db_session, saved_booking):
    """version_id_generator=False means we supply the counter, but an update
    that is not a transition (here: recording the Laqta event id) is still a
    normal write."""
    saved_booking.laqta_event_id = uuid.uuid4()
    db_session.flush()
    assert saved_booking.version == 1
