"""What prepare_* reads to the customer (taxonomy 3, 5, 6, 9).

Through the registry, like test_tools_booking, so the alias handling and the
summary text are tested exactly as the model reaches them.
"""

from __future__ import annotations

import itertools
import re
from datetime import date, timedelta

import pytest
from sqlalchemy import select

from app.models import Booking, Confirmation
from app.domain.booking_state import Trigger, apply
from app.models.enums import BookingStatus, MatchMode
from app.tools import registry
from app.tools.labels import (
    ADDON_ALIASES,
    ADDON_AR,
    CITY_ALIASES,
    CITY_AR,
    MATCH_MODE_ALIASES,
    MATCH_MODE_AR,
    PACKAGE_ALIASES,
    PACKAGE_AR,
)
from tests.factories import REFERENCE_NOW as NOW
from tests.factories import (
    customer_identity,
    make_contact,
    make_tool_context,
    make_when,
    register_when,
)

FAR_DAY = date(2026, 10, 15)
DETAILS = {
    "event_name": "ملتقى الريّان",
    "city": "jeddah",
    "venue": "فندق هيلتون جدة",
    "expected_guests": 100,
    "photographers": 2,
    "match_mode": "face",
    "strict_mode": False,
    "package": "standard",
    "addons": [],
    "onsite_support": False,
}


@pytest.fixture()
def ctx(db_session, policy):
    return make_tool_context(db_session, policy, identity=customer_identity(make_contact(db_session)))


def prepare(ctx, policy, **details):
    when_id = register_when(ctx, make_when(policy, FAR_DAY))
    return registry.execute(
        "prepare_booking", {"when_id": when_id, "details": {**DETAILS, **details}}, ctx=ctx
    )


def stored_details(db_session, result) -> dict:
    confirmation = db_session.get(Confirmation, result["data"]["confirmation_id"])
    return confirmation.params["details"]


def confirm(ctx, result):
    ctx.user_turn += 1
    return registry.execute(
        "confirm_action", {"confirmation_id": result["data"]["confirmation_id"]}, ctx=ctx
    )


# --- 3: Arabic names are accepted, and stored as the English key


@pytest.mark.parametrize(
    ("name", "key"),
    [(label, key) for key, label in PACKAGE_AR.items()]
    + [(alias, key) for key, aliases in PACKAGE_ALIASES.items() for alias in aliases],
)
def test_each_package_alias(ctx, db_session, policy, name, key):
    result = prepare(ctx, policy, package=name)
    assert result["ok"] is True, result
    assert stored_details(db_session, result)["package"] == key


@pytest.mark.parametrize(
    ("name", "key"),
    [(label, key) for key, label in MATCH_MODE_AR.items()]
    + [(alias, key) for key, aliases in MATCH_MODE_ALIASES.items() for alias in aliases],
)
def test_each_match_mode_alias(ctx, db_session, policy, name, key):
    result = prepare(ctx, policy, match_mode=name)
    assert result["ok"] is True, result
    assert stored_details(db_session, result)["match_mode"] == key


@pytest.mark.parametrize(
    ("name", "key"),
    [(label, key) for key, label in ADDON_AR.items()]
    + [(alias, key) for key, aliases in ADDON_ALIASES.items() for alias in aliases],
)
def test_each_addon_alias(ctx, db_session, policy, name, key):
    result = prepare(ctx, policy, addons=[name])
    assert result["ok"] is True, result
    assert stored_details(db_session, result)["addons"] == [key]


@pytest.mark.parametrize(
    ("name", "slug"),
    [(label, slug) for slug, label in CITY_AR.items()]
    + [(alias, slug) for slug, aliases in CITY_ALIASES.items() for alias in aliases],
)
def test_each_city_alias(ctx, db_session, policy, name, slug):
    """Onsite, so a name that failed to resolve would be refused rather than
    slipping through as free text."""
    result = prepare(ctx, policy, city=name, onsite_support=True)
    assert result["ok"] is True, result
    assert stored_details(db_session, result)["city"] == slug


def test_check_availability_accepts_an_arabic_onsite_city(ctx, policy):
    when_id = register_when(ctx, make_when(policy, FAR_DAY))
    result = registry.execute(
        "check_availability", {"when_id": when_id, "city": "جدة", "onsite_support": True}, ctx=ctx
    )
    assert result["ok"] is True, result


@pytest.mark.parametrize("city", ["مكة", "الخبر", "الظهران", "abha"])
def test_an_onsite_city_outside_the_list_is_refused_with_the_list(ctx, db_session, policy, city):
    """Refused explicitly — including الخبر and الظهران, next to الدمام — and
    nothing prepared, so there is no summary a customer could agree to."""
    result = prepare(ctx, policy, city=city, onsite_support=True)

    assert result["ok"] is False
    assert result["error"] == "onsite_city_unsupported"
    assert result["supported_cities"] == list(policy.onsite.cities)
    assert result["supported_cities_ar"] == [CITY_AR[c] for c in policy.onsite.cities]
    assert db_session.scalar(select(Confirmation)) is None


def test_check_availability_refuses_the_same_way(ctx, policy):
    when_id = register_when(ctx, make_when(policy, FAR_DAY))
    result = registry.execute(
        "check_availability", {"when_id": when_id, "city": "الخبر", "onsite_support": True}, ctx=ctx
    )
    assert result["error"] == "onsite_city_unsupported"
    assert result["supported_cities"] == list(policy.onsite.cities)


def test_a_remote_booking_keeps_any_city_exactly_as_given(ctx, db_session, policy):
    """The KB: service without onsite support is available in every city.
    The city is stored and read back unchanged — never swapped for a
    supported one."""
    result = prepare(ctx, policy, city="الخبر", venue="قاعة الواجهة البحرية")  # no city in the venue
    assert result["ok"] is True, result
    assert stored_details(db_session, result)["city"] == "الخبر"

    summary = result["data"]["summary_ar"]
    assert "بـالخبر" in summary
    assert not any(label in summary for label in CITY_AR.values())


def test_an_arabic_booking_is_created_with_english_keys(ctx, db_session, policy):
    """The whole point: the row and the Laqta event carry the keys, whatever
    language the model passed."""
    result = prepare(ctx, policy, package="القياسية", match_mode="الوجه والرمز", addons=["شعار الراعي"])
    assert confirm(ctx, result)["ok"] is True

    booking = db_session.scalars(select(Booking)).one()
    assert booking.package == "standard"
    assert booking.match_mode is MatchMode.both
    assert booking.addons == ["sponsor_overlay"]
    assert ctx.laqta.calls_named("create_event")[0]["match_mode"] == "both"


def test_an_unknown_arabic_package_is_still_unknown(ctx, policy):
    result = prepare(ctx, policy, package="الذهبية")
    assert result["error"] == "unknown_package"


def test_an_unknown_arabic_match_mode_is_invalid_input(ctx, policy):
    assert prepare(ctx, policy, match_mode="بصمة الإصبع")["error"] == "invalid_input"


# --- 5: no enum value reaches the customer


def enum_values(policy) -> set[str]:
    return {
        *policy.packages,
        *policy.addons,
        *policy.onsite.cities,
        *(mode.value for mode in MatchMode),
        *(status.value for status in BookingStatus),
        "strict",
        "onsite",
        "True",
        "False",
        "None",
    }


def assert_no_enum(summary: str, policy) -> None:
    for value in enum_values(policy):
        assert not re.search(rf"(?<![A-Za-z]){re.escape(value)}(?![A-Za-z])", summary, re.IGNORECASE), (
            f"{value!r} in: {summary}"
        )
    # Every input here is Arabic, so any Latin letter at all is a leak.
    assert not re.search(r"[A-Za-z]", summary), summary


def test_no_bare_enum_value_appears_in_any_booking_summary(ctx, policy):
    checked = 0
    for package, mode, strict, onsite, city in itertools.product(
        policy.packages,
        MatchMode,
        (False, True),
        (False, True),
        policy.onsite.cities,
    ):
        if onsite and package not in (*policy.onsite.included_in, *policy.onsite.addon_for):
            continue
        addons = [a for a in policy.addons if not (strict and a in policy.strict_mode.forbidden_addons)]
        result = prepare(
            ctx, policy,
            package=package, match_mode=mode.value, strict_mode=strict,
            onsite_support=onsite, city=city, addons=addons,
        )
        assert result["ok"] is True, result
        assert_no_enum(result["data"]["summary_ar"], policy)
        checked += 1
    assert checked > 100  # the product did not quietly collapse


@pytest.fixture()
def booking(ctx, db_session, policy):
    confirm(ctx, prepare(ctx, policy, match_mode="both", package="premium"))
    return db_session.scalars(select(Booking)).one()


@pytest.fixture()
def paid_booking(db_session, policy, booking):
    apply(booking, Trigger.mark_paid, now=NOW, policy=policy, actor="staff:1")
    db_session.flush()
    return booking


def test_no_bare_enum_value_appears_in_reschedule_or_cancel_summaries(ctx, db_session, policy, booking):
    when_id = register_when(ctx, make_when(policy, FAR_DAY + timedelta(days=7)))
    rescheduled = registry.execute(
        "prepare_reschedule", {"booking_id": str(booking.id), "when_id": when_id}, ctx=ctx
    )
    cancelled_unpaid = registry.execute("prepare_cancel", {"booking_id": str(booking.id)}, ctx=ctx)
    apply(booking, Trigger.mark_paid, now=NOW, policy=policy, actor="staff:1")
    db_session.flush()
    cancelled_paid = registry.execute("prepare_cancel", {"booking_id": str(booking.id)}, ctx=ctx)
    for result in (rescheduled, cancelled_unpaid, cancelled_paid):
        assert result["ok"] is True, result
        assert_no_enum(result["data"]["summary_ar"], policy)


def test_the_enum_check_catches_a_leak(policy):
    """Control: the checker must fire on the pre-fix summary shape."""
    with pytest.raises(AssertionError):
        assert_no_enum("طريقة التعرّف: both، الباقة: starter", policy)


# --- 6: strict mode states its retention, and that it overrides the package's


@pytest.mark.parametrize("package", ["starter", "standard", "premium"])
def test_strict_mode_states_its_retention_and_the_package_it_replaces(ctx, policy, package):
    summary = prepare(ctx, policy, package=package, strict_mode=True, match_mode="code")["data"]["summary_ar"]
    strict_days = policy.strict_mode.retention_days
    package_days = policy.packages[package].retention_days

    assert f"مدة حفظ الصور {strict_days} أيام بسبب الوضع المشدد" in summary
    assert f"وتلغي مدة الباقة {PACKAGE_AR[package]} ({package_days} يوم)" in summary


def test_without_strict_mode_no_retention_is_claimed(ctx, policy):
    assert "مدة حفظ الصور" not in prepare(ctx, policy)["data"]["summary_ar"]


# --- 9: a paid booking's cancel summary says why the tier applies

# Both edges of every tier, and the 74.9h case p25 was written around.
TIER_EDGES = [
    (200, 100, "لأن الإلغاء قبل الفعالية بـ7 أيام أو أكثر"),
    (168, 100, "لأن الإلغاء قبل الفعالية بـ7 أيام أو أكثر"),  # the boundary itself
    (167.9, 50, "لأن الإلغاء قبل الفعالية بأقل من 7 أيام وبـ48 ساعة أو أكثر"),
    (100, 50, "لأن الإلغاء قبل الفعالية بأقل من 7 أيام وبـ48 ساعة أو أكثر"),
    (74.9, 50, "لأن الإلغاء قبل الفعالية بأقل من 7 أيام وبـ48 ساعة أو أكثر"),
    (48, 50, "لأن الإلغاء قبل الفعالية بأقل من 7 أيام وبـ48 ساعة أو أكثر"),
    (47.9, 0, "لأن الإلغاء خلال آخر 48 ساعة قبل الفعالية"),
    (47, 0, "لأن الإلغاء خلال آخر 48 ساعة قبل الفعالية"),
    (1, 0, "لأن الإلغاء خلال آخر 48 ساعة قبل الفعالية"),
]


def cancel_at(ctx, booking, hours_before):
    ctx.now = booking.starts_at - timedelta(hours=hours_before)
    return registry.execute("prepare_cancel", {"booking_id": str(booking.id)}, ctx=ctx)


@pytest.mark.parametrize(("hours_before", "percent", "reason"), TIER_EDGES)
def test_the_cancel_summary_explains_the_tier(ctx, policy, paid_booking, hours_before, percent, reason):
    result = cancel_at(ctx, paid_booking, hours_before)

    assert result["data"]["refund_percent"] == percent
    assert f"نسبة الاسترداد {percent}% {reason}." in result["data"]["summary_ar"]


@pytest.mark.parametrize(("hours_before", "percent", "reason"), TIER_EDGES)
def test_a_paid_cancellation_carries_its_percent_into_params_and_result(
    ctx, db_session, policy, paid_booking, hours_before, percent, reason
):
    prepared = cancel_at(ctx, paid_booking, hours_before)
    stored = db_session.get(Confirmation, prepared["data"]["confirmation_id"]).params
    assert stored == {"booking_id": str(paid_booking.id), "refund_percent": percent}

    result = confirm(ctx, prepared)
    assert result["ok"] is True, result
    assert result["data"]["status"] == "cancelled"
    assert result["data"]["refund_percent"] == percent


# --- 11: an unpaid tentative booking cancels without fees, and no percentage


@pytest.mark.parametrize("hours_before", [edge[0] for edge in TIER_EDGES])
def test_an_unpaid_cancellation_states_no_fee_and_no_percentage(ctx, db_session, policy, booking, hours_before):
    """At every tier edge — 74.9h is the 50% tier p25 hit — the summary, the
    stored params and both results carry no refund figure at all."""
    assert booking.status is BookingStatus.tentative
    prepared = cancel_at(ctx, booking, hours_before)
    assert prepared["ok"] is True, prepared
    data = prepared["data"]

    assert "بدون رسوم" in data["summary_ar"]
    assert "%" not in data["summary_ar"]
    assert "استرداد" not in data["summary_ar"]
    assert "refund_percent" not in data
    stored = db_session.get(Confirmation, data["confirmation_id"]).params
    assert stored == {"booking_id": str(booking.id)}

    result = confirm(ctx, prepared)
    assert result["ok"] is True, result
    assert result["data"]["status"] == "cancelled"
    assert "refund_percent" not in result["data"]
    db_session.refresh(booking)
    assert booking.status is BookingStatus.cancelled


def test_a_booking_paid_between_prepare_and_confirm_is_not_cancelled(ctx, db_session, policy, booking):
    """The customer agreed to "بدون رسوم". Once it is paid a refund tier
    applies, so confirming would cancel on terms nobody read to them."""
    prepared = cancel_at(ctx, booking, 74.9)
    apply(booking, Trigger.mark_paid, now=ctx.now, policy=policy, actor="staff:1")
    db_session.flush()

    result = confirm(ctx, prepared)
    assert result["error"] == "booking_changed"
    db_session.refresh(booking)
    assert booking.status is BookingStatus.confirmed
    assert ctx.laqta.calls_named("cancel_event") == []

    again = cancel_at(ctx, booking, 74.9)
    assert again["data"]["refund_percent"] == 50
