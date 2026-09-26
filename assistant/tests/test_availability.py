from __future__ import annotations

import re
from dataclasses import fields, replace
from datetime import datetime, time, timedelta

import pytest

from app.domain.availability import (
    END_BEFORE_START,
    GUESTS_EXCEED_PACKAGE,
    IN_PAST,
    LEAD_TIME,
    ONSITE_CITY_UNSUPPORTED,
    ONSITE_FULL,
    SUGGESTIBLE_REASONS,
    TOO_LONG,
    AvailabilityRequest,
    AvailabilityResult,
    _shift_days,
    check,
    event_days,
    event_length_days,
)
from tests.factories import REFERENCE_NOW as NOW

UNSUPPORTED_CITY = "abha"


def request_for(
    policy,
    *,
    day_offset: int = 30,
    start_hour: int = 16,
    end_hour: int = 23,
    days: int = 1,
    city: str = "jeddah",
    onsite: bool = False,
    guests: int | None = None,
    package: str | None = None,
) -> AvailabilityRequest:
    tz = policy.tz
    start_day = NOW.astimezone(tz).date() + timedelta(days=day_offset)
    return AvailabilityRequest(
        starts_at=datetime.combine(start_day, time(start_hour), tzinfo=tz),
        ends_at=datetime.combine(start_day + timedelta(days=days - 1), time(end_hour), tzinfo=tz),
        city=city,
        onsite_support=onsite,
        expected_guests=guests,
        package=package,
    )


def reason_for(req, policy, onsite_counts=None) -> str | None:
    return check(req, now=NOW, onsite_counts=onsite_counts or {}, policy=policy).reason


def full_days(policy, req, count: int) -> dict:
    """The first `count` days from the request's start, each at the limit."""
    tz = policy.tz
    first = req.starts_at.astimezone(tz).date()
    limit = policy.onsite.max_events_per_city_per_day
    return {first + timedelta(days=offset): limit for offset in range(count)}


# --- The happy path


def test_available_request(policy):
    result = check(request_for(policy), now=NOW, onsite_counts={}, policy=policy)
    assert result == AvailabilityResult(ok=True)


# --- Rule 1: in_past


def test_in_past(policy):
    assert reason_for(request_for(policy, day_offset=-1), policy) == IN_PAST


def test_a_start_one_second_ago_is_in_the_past(policy):
    req = request_for(policy)
    assert reason_for(replace(req, starts_at=NOW - timedelta(seconds=1)), policy) == IN_PAST


# --- Rule 2: end_before_start


@pytest.mark.parametrize("delta", [timedelta(hours=-1), timedelta(0)])
def test_end_before_or_equal_to_start(policy, delta):
    req = request_for(policy)
    assert reason_for(replace(req, ends_at=req.starts_at + delta), policy) == END_BEFORE_START


# --- Rule 3: too_long


def test_too_long(policy):
    req = request_for(policy, days=policy.max_event_days + 1)
    assert reason_for(req, policy) == TOO_LONG


def test_exactly_the_maximum_length_is_fine(policy):
    req = request_for(policy, days=policy.max_event_days)
    assert reason_for(req, policy) is None


def test_an_evening_past_midnight_is_one_event_day(policy):
    """21:00→02:00 is one wedding. It still touches two calendar dates, which
    is what capacity counts — the two spans are deliberately different."""
    req = request_for(policy, start_hour=21, end_hour=2)
    req = replace(req, ends_at=req.ends_at + timedelta(days=1))

    assert event_length_days(req.starts_at, req.ends_at, policy.tz) == 1
    assert len(event_days(req.starts_at, req.ends_at, policy.tz)) == 2
    assert reason_for(req, policy) is None


def test_a_three_day_event_ending_after_midnight_is_not_too_long(policy):
    """The bug this split fixes: counting calendar dates made a normal
    three-day event whose last night ends at 01:00 look like four days."""
    req = request_for(policy, days=policy.max_event_days, start_hour=21, end_hour=1)
    req = replace(req, ends_at=req.ends_at + timedelta(days=1))

    assert event_length_days(req.starts_at, req.ends_at, policy.tz) == policy.max_event_days
    assert len(event_days(req.starts_at, req.ends_at, policy.tz)) == policy.max_event_days + 1
    assert reason_for(req, policy) is None


def test_a_four_day_event_is_still_too_long_however_it_ends(policy):
    late = request_for(policy, days=policy.max_event_days + 1, start_hour=21, end_hour=1)
    late = replace(late, ends_at=late.ends_at + timedelta(days=1))
    assert reason_for(late, policy) == TOO_LONG
    assert reason_for(request_for(policy, days=policy.max_event_days + 1), policy) == TOO_LONG


# --- Rule 4: lead_time


def at_lead_time(req, hours: int, *, early: timedelta = timedelta(0)) -> AvailabilityRequest:
    """The same one-evening event, moved to exactly `hours` from now (minus
    `early`). Both ends move: shifting only the start would stretch the event
    past max_event_days and rule 3 would fire first."""
    starts_at = NOW + timedelta(hours=hours) - early
    return replace(req, starts_at=starts_at, ends_at=starts_at + timedelta(hours=7))


def test_remote_lead_time_boundary(policy):
    req = request_for(policy)
    hours = policy.lead_time_hours.remote
    assert reason_for(at_lead_time(req, hours), policy) is None
    assert reason_for(at_lead_time(req, hours, early=timedelta(seconds=1)), policy) == LEAD_TIME


def test_onsite_needs_a_longer_lead_time_than_remote(policy):
    """The same date: fine remotely, too soon with onsite support."""
    day_offset = policy.lead_time_hours.remote // 24 + 1
    assert reason_for(request_for(policy, day_offset=day_offset), policy) is None
    assert reason_for(request_for(policy, day_offset=day_offset, onsite=True), policy) == LEAD_TIME


def test_onsite_lead_time_boundary(policy):
    req = request_for(policy, onsite=True)
    hours = policy.lead_time_hours.onsite
    assert reason_for(at_lead_time(req, hours), policy) is None
    assert reason_for(at_lead_time(req, hours, early=timedelta(seconds=1)), policy) == LEAD_TIME


# --- Rule 5: onsite_city_unsupported


def test_onsite_city_unsupported(policy):
    req = request_for(policy, onsite=True, city=UNSUPPORTED_CITY)
    assert reason_for(req, policy) == ONSITE_CITY_UNSUPPORTED


def test_remote_events_run_in_any_city(policy):
    assert reason_for(request_for(policy, city=UNSUPPORTED_CITY), policy) is None


@pytest.mark.parametrize("city", ["jeddah", "riyadh", "dammam"])
def test_supported_onsite_cities(policy, city):
    assert city in policy.onsite.cities
    assert reason_for(request_for(policy, onsite=True, city=city), policy) is None


# --- Rule 6: onsite_full


def test_onsite_full(policy):
    req = request_for(policy, onsite=True)
    assert reason_for(req, policy, full_days(policy, req, 1)) == ONSITE_FULL


def test_one_slot_left_is_available(policy):
    req = request_for(policy, onsite=True)
    day = req.starts_at.astimezone(policy.tz).date()
    counts = {day: policy.onsite.max_events_per_city_per_day - 1}
    assert reason_for(req, policy, counts) is None


def test_any_full_day_of_a_multi_day_event_rejects_it(policy):
    req = request_for(policy, onsite=True, days=3)
    day = req.starts_at.astimezone(policy.tz).date()
    counts = {day + timedelta(days=2): policy.onsite.max_events_per_city_per_day}
    assert reason_for(req, policy, counts) == ONSITE_FULL


def test_a_full_onsite_day_does_not_block_a_remote_booking(policy):
    """Onsite capacity is about crews, so it is not checked without onsite."""
    req = request_for(policy, onsite=False)
    assert reason_for(req, policy, full_days(policy, req, 1)) is None


# --- Rule 7: guests_exceed_package


def test_guests_exceed_package_suggests_the_next_one_up(policy):
    req = request_for(policy, package="starter", guests=policy.packages["starter"].max_guests + 1)
    result = check(req, now=NOW, onsite_counts={}, policy=policy)
    assert result.reason == GUESTS_EXCEED_PACKAGE
    assert result.suggested_package == "standard"


def test_very_large_events_are_pushed_to_premium(policy):
    req = request_for(policy, package="starter", guests=policy.packages["standard"].max_guests + 1)
    result = check(req, now=NOW, onsite_counts={}, policy=policy)
    assert result.suggested_package == "premium"


def test_package_at_its_exact_limit_is_fine(policy):
    req = request_for(policy, package="starter", guests=policy.packages["starter"].max_guests)
    assert reason_for(req, policy) is None


def test_unlimited_package(policy):
    assert policy.packages["premium"].max_guests is None
    assert reason_for(request_for(policy, package="premium", guests=100_000), policy) is None


@pytest.mark.parametrize("guests,package", [(None, "starter"), (5000, None), (None, None)])
def test_rule_seven_is_skipped_when_the_tool_has_no_package_or_guests(policy, guests, package):
    """check_availability (spec §10) is called before either is known."""
    assert reason_for(request_for(policy, guests=guests, package=package), policy) is None


def test_unknown_package_is_a_programming_error(policy):
    req = request_for(policy, package="platinum", guests=10)
    with pytest.raises(ValueError, match="platinum"):
        check(req, now=NOW, onsite_counts={}, policy=policy)


# --- Rule order: the first failure wins


def test_rules_run_in_spec_order(policy):
    """Each case breaks its own rule and every rule after it."""
    limit = policy.onsite.max_events_per_city_per_day
    starter_max = policy.packages["starter"].max_guests
    everything_full = {
        NOW.astimezone(policy.tz).date() + timedelta(days=offset): limit for offset in range(-5, 40)
    }

    # in_past also breaks too_long, lead_time, city and guests.
    past = request_for(
        policy, day_offset=-1, days=policy.max_event_days + 1, onsite=True,
        city=UNSUPPORTED_CITY, package="starter", guests=starter_max + 1,
    )
    assert reason_for(past, policy, everything_full) == IN_PAST

    # end_before_start, with the city and guests rules also broken.
    reversed_window = replace(
        request_for(
            policy, onsite=True, city=UNSUPPORTED_CITY, package="starter", guests=starter_max + 1
        ),
        ends_at=NOW + timedelta(days=10),
        starts_at=NOW + timedelta(days=11),
    )
    assert reason_for(reversed_window, policy, everything_full) == END_BEFORE_START

    # too_long beats lead_time.
    long_and_soon = request_for(policy, day_offset=1, days=policy.max_event_days + 1, onsite=True)
    assert reason_for(long_and_soon, policy, everything_full) == TOO_LONG

    # lead_time beats the city rule.
    soon_and_unsupported = request_for(
        policy, day_offset=1, onsite=True, city=UNSUPPORTED_CITY
    )
    assert reason_for(soon_and_unsupported, policy, everything_full) == LEAD_TIME

    # city beats full.
    unsupported_and_full = request_for(policy, onsite=True, city=UNSUPPORTED_CITY)
    assert reason_for(unsupported_and_full, policy, everything_full) == ONSITE_CITY_UNSUPPORTED

    # full beats guests.
    full_and_too_many = request_for(
        policy, onsite=True, package="starter", guests=starter_max + 1
    )
    assert reason_for(full_and_too_many, policy, everything_full) == ONSITE_FULL


# --- Suggestions


def test_lead_time_suggests_the_nearest_legal_days(policy):
    req = request_for(policy, day_offset=1)
    result = check(req, now=NOW, onsite_counts={}, policy=policy)

    assert result.reason == LEAD_TIME
    assert len(result.suggestions) == policy.availability.suggestion_count
    assert list(result.suggestions) == sorted(result.suggestions)
    earliest_legal = (NOW + timedelta(hours=policy.lead_time_hours.remote)).astimezone(policy.tz)
    assert result.suggestions[0] >= earliest_legal.date()


def test_onsite_full_suggests_days_that_are_not_full(policy):
    req = request_for(policy, onsite=True)
    counts = full_days(policy, req, 4)  # requested day plus the next three
    result = check(req, now=NOW, onsite_counts=counts, policy=policy)

    first_day = req.starts_at.astimezone(policy.tz).date()
    assert result.reason == ONSITE_FULL
    assert result.suggestions == tuple(
        first_day + timedelta(days=offset) for offset in (4, 5, 6)
    )


def test_suggestions_are_consecutive_whole_days(policy):
    req = request_for(policy, day_offset=1, start_hour=21, end_hour=23)
    result = check(req, now=NOW, onsite_counts={}, policy=policy)

    requested_day = req.starts_at.astimezone(policy.tz).date()
    assert result.suggestions == tuple(
        requested_day + timedelta(days=offset) for offset in (1, 2, 3)
    )


@pytest.mark.parametrize("offset", [1, 30])
def test_shifting_a_day_keeps_the_wall_clock_time(policy, offset):
    """Whole-day shifts, not 24h arithmetic: the times a customer asked for
    stay the times they are offered."""
    req = request_for(policy, start_hour=21, end_hour=23)
    shifted = _shift_days(req.starts_at, offset, policy.tz)

    local_before = req.starts_at.astimezone(policy.tz)
    local_after = shifted.astimezone(policy.tz)
    assert local_after.timetz() == local_before.timetz()
    assert (local_after.date() - local_before.date()).days == offset


def test_suggestions_stay_inside_the_search_window(policy):
    req = request_for(policy, onsite=True)
    first_day = req.starts_at.astimezone(policy.tz).date()
    limit = policy.onsite.max_events_per_city_per_day
    # Everything full for longer than we are willing to look.
    counts = {
        first_day + timedelta(days=offset): limit
        for offset in range(policy.availability.suggestion_search_days + 10)
    }
    result = check(req, now=NOW, onsite_counts=counts, policy=policy)
    assert result.reason == ONSITE_FULL
    assert result.suggestions == ()


def test_multi_day_events_are_suggested_as_whole_blocks(policy):
    """A 3-day event needs three consecutive free days, not just a free first
    day."""
    req = request_for(policy, onsite=True, days=3)
    first_day = req.starts_at.astimezone(policy.tz).date()
    limit = policy.onsite.max_events_per_city_per_day
    # Day +3 is full, so blocks starting at +1, +2 and +3 are all unusable.
    counts = {first_day: limit, first_day + timedelta(days=3): limit}
    result = check(req, now=NOW, onsite_counts=counts, policy=policy)
    assert result.suggestions[0] == first_day + timedelta(days=4)


@pytest.mark.parametrize(
    "reason,builder",
    [
        (IN_PAST, lambda p: request_for(p, day_offset=-1)),
        (TOO_LONG, lambda p: request_for(p, days=p.max_event_days + 1)),
        (ONSITE_CITY_UNSUPPORTED, lambda p: request_for(p, onsite=True, city=UNSUPPORTED_CITY)),
        (
            GUESTS_EXCEED_PACKAGE,
            lambda p: request_for(p, package="starter", guests=p.packages["starter"].max_guests + 1),
        ),
    ],
)
def test_only_date_fixable_reasons_get_suggestions(policy, reason, builder):
    result = check(builder(policy), now=NOW, onsite_counts={}, policy=policy)
    assert result.reason == reason
    assert reason not in SUGGESTIBLE_REASONS
    assert result.suggestions == ()


# --- Rejections must not leak capacity numbers


DIGITS = re.compile(r"[0-9٠-٩]")  # ASCII and Arabic-Indic


def tool_payload(result: AvailabilityResult) -> dict:
    """What the tool layer will hand the model (spec §10)."""
    payload: dict = {"ok": result.ok, "error": result.reason}
    if result.suggestions:
        payload["suggestions"] = [day.isoformat() for day in result.suggestions]
    if result.suggested_package:
        payload["suggested_package"] = result.suggested_package
    return payload


def collect(value, kinds) -> list:
    if isinstance(value, bool):  # bool before int: True is not a count
        return []
    if isinstance(value, kinds):
        return [value]
    if isinstance(value, dict):
        return [found for item in value.values() for found in collect(item, kinds)]
    if isinstance(value, (list, tuple)):
        return [found for item in value for found in collect(item, kinds)]
    return []


def rejections(policy) -> dict[str, tuple[AvailabilityResult, set[int]]]:
    """Every rejection reason, with the capacity integers it was built from."""
    limit = policy.onsite.max_events_per_city_per_day
    starter_max = policy.packages["starter"].max_guests
    onsite_req = request_for(policy, onsite=True)
    reversed_window = replace(request_for(policy), ends_at=request_for(policy).starts_at)

    cases = {
        IN_PAST: (request_for(policy, day_offset=-1), {}),
        END_BEFORE_START: (reversed_window, {}),
        TOO_LONG: (request_for(policy, days=policy.max_event_days + 1), {}),
        LEAD_TIME: (request_for(policy, day_offset=1), {}),
        ONSITE_CITY_UNSUPPORTED: (request_for(policy, onsite=True, city=UNSUPPORTED_CITY), {}),
        ONSITE_FULL: (onsite_req, full_days(policy, onsite_req, 3)),
        GUESTS_EXCEED_PACKAGE: (
            request_for(policy, package="starter", guests=starter_max + 1),
            {},
        ),
    }
    out = {}
    for reason, (req, counts) in cases.items():
        result = check(req, now=NOW, onsite_counts=counts, policy=policy)
        assert result.reason == reason, f"{reason} case produced {result.reason}"
        out[reason] = (result, {limit, *counts.values()})
    return out


def test_result_type_has_no_capacity_fields():
    """Structural, so adding a `remaining` or `limit` field fails here."""
    assert {f.name for f in fields(AvailabilityResult)} == {
        "ok", "reason", "suggestions", "suggested_package",
    }


def test_no_rejection_carries_a_capacity_integer(policy):
    for reason, (result, capacity_ints) in rejections(policy).items():
        payload = tool_payload(result)
        leaked = set(collect(payload, int)) & capacity_ints
        assert not leaked, f"{reason} payload leaks {leaked}"


def test_no_rejection_carries_digits_outside_the_suggested_dates(policy):
    """Catches a count smuggled into prose — "٢ من ٢" or "2 of 2" — in any
    language, since the only digits allowed through are the ISO dates."""
    for reason, (result, _) in rejections(policy).items():
        payload = tool_payload(result)
        allowed = set(payload.get("suggestions", ()))
        for value in collect(payload, str):
            if value in allowed:
                continue
            assert not DIGITS.search(value), f"{reason} payload has digits in {value!r}"


def test_onsite_full_reason_is_exactly_that(policy):
    req = request_for(policy, onsite=True)
    result = check(req, now=NOW, onsite_counts=full_days(policy, req, 3), policy=policy)
    assert result.reason == ONSITE_FULL  # not "onsite_full:2/2"
