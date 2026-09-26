"""prepare_* → confirm_action, end to end through the registry (spec §8, §10)."""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy import func, select

from app.domain.availability import ONSITE_FULL, TOO_LONG
from app.domain.booking_state import Trigger, apply
from app.domain.payment import payment_deadline
from app.models import Booking
from app.models.enums import BookingStatus
from app.tools import registry
from tests.factories import REFERENCE_NOW as NOW
from tests.factories import (
    customer_identity,
    make_contact,
    make_onsite_booking,
    make_tool_context,
    make_when,
    register_when,
    riyadh_window,
)

FAR_DAY = date(2026, 10, 15)  # ~34 days out: clears every lead time
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


@pytest.fixture()
def customer(db_session):
    return make_contact(db_session)


@pytest.fixture()
def ctx(db_session, policy, customer):
    return make_tool_context(db_session, policy, identity=customer_identity(customer))


def prepare_booking(ctx, policy, *, day=FAR_DAY, details=None, days=1, **when_kwargs):
    when_id = register_when(ctx, make_when(policy, day, days=days, **when_kwargs))
    payload = {"when_id": when_id, "details": {**DETAILS, **(details or {})}}
    return registry.execute("prepare_booking", payload, ctx=ctx)


def confirm(ctx, confirmation_id, *, turns_later=1):
    ctx.user_turn += turns_later
    return registry.execute("confirm_action", {"confirmation_id": confirmation_id}, ctx=ctx)


# --- The happy path


def test_prepare_then_confirm_creates_one_booking(ctx, db_session, policy):
    prepared = prepare_booking(ctx, policy)
    assert prepared["ok"] is True
    assert prepared["data"]["expires_in_minutes"] == policy.confirmation_ttl_minutes
    assert "ملتقى الريّان" in prepared["data"]["summary_ar"]
    # Nothing exists yet.
    assert db_session.scalar(select(func.count()).select_from(Booking)) == 0

    result = confirm(ctx, prepared["data"]["confirmation_id"])
    assert result["ok"] is True

    booking = db_session.scalars(select(Booking)).one()
    assert booking.status is BookingStatus.tentative
    assert booking.contact_id == ctx.identity.contact_id
    assert booking.event_name == "ملتقى الريّان"
    assert [event.trigger for event in booking.events] == ["confirm_booking"]
    assert booking.payment_due_at == payment_deadline(
        tentative_at=NOW, starts_at=booking.starts_at, policy=policy
    )


def test_confirming_creates_the_laqta_event_with_the_booking_id_as_key(ctx, policy):
    prepared = prepare_booking(ctx, policy)
    result = confirm(ctx, prepared["data"]["confirmation_id"])

    call = ctx.laqta.calls_named("create_event")[0]
    assert call["idempotency_key"] == result["data"]["booking_id"]
    assert call["privacy_mode"] == "standard"
    assert call["name_ar"] == "ملتقى الريّان"


def test_strict_mode_becomes_laqta_strict_privacy_mode(ctx, policy):
    prepared = prepare_booking(ctx, policy, details={"strict_mode": True, "match_mode": "code"})
    confirm(ctx, prepared["data"]["confirmation_id"])
    assert ctx.laqta.calls_named("create_event")[0]["privacy_mode"] == "strict"


# --- §8 enforcement at the tool level


def test_confirming_in_the_same_turn_is_refused(ctx, db_session, policy):
    """The customer has not replied since the summary was read to them."""
    prepared = prepare_booking(ctx, policy)
    result = confirm(ctx, prepared["data"]["confirmation_id"], turns_later=0)

    assert result["ok"] is False
    assert result["error"] == "awaiting_customer_reply"
    assert db_session.scalar(select(func.count()).select_from(Booking)) == 0


def test_a_confirmation_works_once(ctx, policy):
    prepared = prepare_booking(ctx, policy)
    assert confirm(ctx, prepared["data"]["confirmation_id"])["ok"] is True
    assert confirm(ctx, prepared["data"]["confirmation_id"])["error"] == "already_used"


def test_an_expired_confirmation_is_refused(ctx, policy):
    prepared = prepare_booking(ctx, policy)
    ctx.now = NOW + timedelta(minutes=policy.confirmation_ttl_minutes)
    assert confirm(ctx, prepared["data"]["confirmation_id"])["error"] == "expired"


def test_another_sessions_confirmation_is_not_found(ctx, db_session, policy, customer):
    prepared = prepare_booking(ctx, policy)
    other = make_tool_context(db_session, policy, identity=customer_identity(customer))
    other.user_turn = ctx.user_turn + 1

    result = registry.execute(
        "confirm_action", {"confirmation_id": prepared["data"]["confirmation_id"]}, ctx=other
    )
    assert result["error"] == "not_found"


def test_a_day_that_fills_between_prepare_and_confirm_is_refused(ctx, db_session, policy, customer):
    """The recheck under the lock, doing its job."""
    prepared = prepare_booking(ctx, policy, details={"onsite_support": True})
    assert prepared["ok"] is True

    for _ in range(policy.onsite.max_events_per_city_per_day):
        make_onsite_booking(db_session, policy, FAR_DAY, contact_id=customer.id)

    result = confirm(ctx, prepared["data"]["confirmation_id"])
    assert result["ok"] is False
    assert result["error"] == ONSITE_FULL
    assert result["suggestions"]


# --- prepare_booking validation


def test_unknown_package(ctx, policy):
    result = prepare_booking(ctx, policy, details={"package": "platinum"})
    assert result["error"] == "unknown_package"
    assert "premium" in result["packages"]


def test_an_addon_outside_the_catalogue_is_rejected(ctx, policy):
    result = prepare_booking(ctx, policy, details={"addons": ["free_drone_footage"]})
    assert result["error"] == "unknown_addon"
    assert result["addons"] == ["free_drone_footage"]
    assert set(result["available"]) == set(policy.addons)


def test_a_catalogued_addon_is_accepted(ctx, policy):
    allowed = [
        addon for addon in policy.addons if addon not in policy.strict_mode.forbidden_addons
    ]
    assert prepare_booking(ctx, policy, details={"addons": allowed})["ok"] is True


def test_strict_mode_forbids_its_forbidden_addons(ctx, policy):
    addon = policy.strict_mode.forbidden_addons[0]
    result = prepare_booking(ctx, policy, details={"strict_mode": True, "addons": [addon]})
    assert result["error"] == "addon_not_allowed_in_strict_mode"
    assert result["addons"] == [addon]


def test_the_same_addon_is_fine_without_strict_mode(ctx, policy):
    addon = policy.strict_mode.forbidden_addons[0]
    assert prepare_booking(ctx, policy, details={"addons": [addon]})["ok"] is True


def test_onsite_support_needs_a_package_that_offers_it(ctx, policy):
    result = prepare_booking(
        ctx, policy, details={"package": "starter", "expected_guests": 100, "onsite_support": True}
    )
    assert result["error"] == "onsite_not_available_for_package"


def test_guests_over_the_package_limit_suggest_a_bigger_one(ctx, policy):
    result = prepare_booking(
        ctx,
        policy,
        details={"package": "starter", "expected_guests": policy.packages["starter"].max_guests + 1},
    )
    assert result["error"] == "guests_exceed_package"
    assert result["suggested_package"] == "standard"


def test_a_too_long_event_asks_for_sales(ctx, policy):
    result = prepare_booking(ctx, policy, days=policy.max_event_days + 1)
    assert result["error"] == TOO_LONG
    assert result["handoff"] == {"reason_code": "long_event", "team": "sales", "team_ar": "المبيعات"}


def test_a_when_id_is_required(ctx):
    result = registry.execute(
        "prepare_booking", {"when_id": "made-up", "details": DETAILS}, ctx=ctx
    )
    assert result["error"] == "unknown_when_id"


# --- Reschedule


@pytest.fixture()
def tentative_booking(ctx, db_session, policy, customer):
    prepared = prepare_booking(ctx, policy)
    confirm(ctx, prepared["data"]["confirmation_id"])
    return db_session.scalars(select(Booking)).one()


def test_rescheduling_recalculates_the_payment_deadline(ctx, db_session, policy, tentative_booking):
    """The bug: a deadline anchored to the old start can fall after the new
    event date once the booking moves closer."""
    # Two days out: clear of the remote lead time, but close enough that the
    # deadline anchored to the old start (booking + 72h) falls *after* the
    # new event date. That is the bug.
    new_day = (NOW + timedelta(days=2)).date()
    old_deadline = tentative_booking.payment_due_at
    new_start, _ = riyadh_window(policy, new_day)
    assert old_deadline > new_start  # would have been after the event

    when_id = register_when(ctx, make_when(policy, new_day))
    prepared = registry.execute(
        "prepare_reschedule",
        {"booking_id": str(tentative_booking.id), "when_id": when_id},
        ctx=ctx,
    )
    assert prepared["ok"] is True
    result = confirm(ctx, prepared["data"]["confirmation_id"])
    assert result["ok"] is True

    db_session.refresh(tentative_booking)
    assert tentative_booking.starts_at == new_start
    assert tentative_booking.payment_due_at == payment_deadline(
        tentative_at=NOW, starts_at=new_start, policy=policy
    )
    assert tentative_booking.payment_due_at < tentative_booking.starts_at


def test_a_confirmed_booking_keeps_its_deadline(ctx, db_session, policy, tentative_booking):
    """It is already paid; the deadline is history, not a live constraint."""
    apply(tentative_booking, Trigger.mark_paid, now=NOW, policy=policy, actor="staff:1")
    db_session.flush()
    paid_deadline = tentative_booking.payment_due_at

    when_id = register_when(ctx, make_when(policy, (NOW + timedelta(days=20)).date()))
    prepared = registry.execute(
        "prepare_reschedule",
        {"booking_id": str(tentative_booking.id), "when_id": when_id},
        ctx=ctx,
    )
    confirm(ctx, prepared["data"]["confirmation_id"])

    db_session.refresh(tentative_booking)
    assert tentative_booking.status is BookingStatus.confirmed
    assert tentative_booking.payment_due_at == paid_deadline


def test_rescheduling_updates_the_laqta_window(ctx, db_session, policy, tentative_booking):
    when = make_when(policy, (NOW + timedelta(days=20)).date())
    when_id = register_when(ctx, when)
    prepared = registry.execute(
        "prepare_reschedule",
        {"booking_id": str(tentative_booking.id), "when_id": when_id},
        ctx=ctx,
    )
    confirm(ctx, prepared["data"]["confirmation_id"])

    call = ctx.laqta.calls_named("update_event_window")[0]
    assert call["event_id"] == tentative_booking.laqta_event_id
    assert call["starts_at"] == when.start


def test_a_change_inside_the_free_window_asks_for_ops(ctx, policy, tentative_booking):
    """The KB: changes in the last 48 hours need the team's approval. That is
    a handoff, not a failure."""
    ctx.now = tentative_booking.starts_at - timedelta(
        hours=policy.free_reschedule_before_hours - 1
    )
    when_id = register_when(ctx, make_when(policy, (ctx.now + timedelta(days=40)).date()))

    result = registry.execute(
        "prepare_reschedule",
        {"booking_id": str(tentative_booking.id), "when_id": when_id},
        ctx=ctx,
    )
    assert result["error"] == "needs_staff_approval"
    assert result["handoff"] == {"reason_code": "late_change", "team": "ops", "team_ar": "العمليات"}


def test_a_live_event_cannot_be_rescheduled(ctx, db_session, policy, tentative_booking):
    apply(tentative_booking, Trigger.mark_paid, now=NOW, policy=policy, actor="staff:1")
    apply(
        tentative_booking,
        Trigger.window_open,
        now=tentative_booking.starts_at - timedelta(hours=policy.upload_opens_before_hours),
        policy=policy,
        actor="clock",
    )
    db_session.flush()

    when_id = register_when(ctx, make_when(policy, (NOW + timedelta(days=60)).date()))
    result = registry.execute(
        "prepare_reschedule",
        {"booking_id": str(tentative_booking.id), "when_id": when_id},
        ctx=ctx,
    )
    assert result["error"] == "not_reschedulable"
    assert result["handoff"]["team"] == "ops"


# --- Cancel


def test_cancelling_reports_the_refund_and_closes_the_laqta_event(
    ctx, db_session, policy, tentative_booking
):
    # Paid: an unpaid booking has no refund at all (taxonomy 11, test_summaries).
    apply(tentative_booking, Trigger.mark_paid, now=NOW, policy=policy, actor="staff:1")
    db_session.flush()
    prepared = registry.execute(
        "prepare_cancel", {"booking_id": str(tentative_booking.id)}, ctx=ctx
    )
    assert prepared["ok"] is True
    assert prepared["data"]["refund_percent"] == 100  # more than a week out
    assert "100%" in prepared["data"]["summary_ar"]

    result = confirm(ctx, prepared["data"]["confirmation_id"])
    assert result["data"]["refund_percent"] == 100

    db_session.refresh(tentative_booking)
    assert tentative_booking.status is BookingStatus.cancelled
    assert ctx.laqta.calls_named("cancel_event")[0]["event_id"] == tentative_booking.laqta_event_id


def test_the_refund_tier_follows_the_cancellation_time(ctx, db_session, policy, tentative_booking):
    apply(tentative_booking, Trigger.mark_paid, now=NOW, policy=policy, actor="staff:1")
    db_session.flush()
    ctx.now = tentative_booking.starts_at - timedelta(hours=72)
    prepared = registry.execute(
        "prepare_cancel", {"booking_id": str(tentative_booking.id)}, ctx=ctx
    )
    assert prepared["data"]["refund_percent"] == 50


def test_an_unknown_booking_is_not_found(ctx):
    result = registry.execute("prepare_cancel", {"booking_id": str(uuid.uuid4())}, ctx=ctx)
    assert result["error"] == "not_found"
