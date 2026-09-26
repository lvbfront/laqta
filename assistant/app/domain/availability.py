"""Availability rules (spec §6).

Pure: no database and no clock. `now` and the per-day onsite counts are
passed in, which is what lets one function serve both the read-only
check_availability tool and the final check under the capacity lock.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.config import Policy

# Reason codes, in the order the rules run.
IN_PAST = "in_past"
END_BEFORE_START = "end_before_start"
TOO_LONG = "too_long"
LEAD_TIME = "lead_time"
ONSITE_CITY_UNSUPPORTED = "onsite_city_unsupported"
ONSITE_FULL = "onsite_full"
GUESTS_EXCEED_PACKAGE = "guests_exceed_package"

# The two a different date can fix.
SUGGESTIBLE_REASONS = frozenset({LEAD_TIME, ONSITE_FULL})


@dataclass(frozen=True)
class AvailabilityRequest:
    starts_at: datetime
    ends_at: datetime
    city: str
    onsite_support: bool
    # Rule 7 runs only when both are known: check_availability (spec §10) has
    # neither, prepare_booking has both.
    expected_guests: int | None = None
    package: str | None = None


@dataclass(frozen=True)
class AvailabilityResult:
    """Carries no counts, limits or remaining-slot numbers, deliberately: a
    rejection is read back to the customer by the model, and the model must
    not be able to leak a capacity number it never saw (spec §6)."""

    ok: bool
    reason: str | None = None
    suggestions: tuple[date, ...] = ()
    suggested_package: str | None = None


def event_days(starts_at: datetime, ends_at: datetime, tz: ZoneInfo) -> tuple[date, ...]:
    """Every local date the event touches — a 21:00→02:00 wedding occupies
    two, because an onsite crew is unavailable on both.

    This is the capacity span. For how long the event *is*, see
    event_length_days: the two are deliberately different. The same helper
    is used for counting and for checking, so those can never disagree.
    """
    start = starts_at.astimezone(tz).date()
    end = ends_at.astimezone(tz).date()
    if end < start:  # rule 2 rejects this; don't blow up before reaching it
        return (start,)
    return tuple(start + timedelta(days=offset) for offset in range((end - start).days + 1))


def event_length_days(starts_at: datetime, ends_at: datetime, tz: ZoneInfo) -> int:
    """How many days the customer would say they booked, which is what
    max_event_days limits.

    An evening running past midnight is one day, not two: 21:00→02:00 is a
    single wedding, and a three-day conference whose last night ends at
    01:00 is three days, not four. Calendar dates spanned, minus the final
    one when the event ends earlier in the day than it started.
    """
    local_start = starts_at.astimezone(tz)
    local_end = ends_at.astimezone(tz)
    spanned = (local_end.date() - local_start.date()).days + 1
    if local_end.time() < local_start.time():
        spanned -= 1
    return max(spanned, 1)


def check(
    req: AvailabilityRequest,
    *,
    now: datetime,
    onsite_counts: dict[date, int],
    policy: Policy,
) -> AvailabilityResult:
    """Run the seven rules in order; the first failure wins.

    `onsite_counts` maps a local date to how many onsite bookings already
    occupy it. For suggestions to be any good it should also cover the
    lookahead window (see capacity.check_under_lock); missing days count 0.
    """
    reason, suggested_package = _first_failure(
        req, now=now, onsite_counts=onsite_counts, policy=policy
    )
    if reason is None:
        return AvailabilityResult(ok=True)

    suggestions: tuple[date, ...] = ()
    if reason in SUGGESTIBLE_REASONS:
        suggestions = _suggest(req, now=now, onsite_counts=onsite_counts, policy=policy)
    return AvailabilityResult(
        ok=False, reason=reason, suggestions=suggestions, suggested_package=suggested_package
    )


def _first_failure(
    req: AvailabilityRequest,
    *,
    now: datetime,
    onsite_counts: dict[date, int],
    policy: Policy,
) -> tuple[str | None, str | None]:
    # 1
    if req.starts_at < now:
        return IN_PAST, None
    # 2
    if req.ends_at <= req.starts_at:
        return END_BEFORE_START, None
    # 3 — length as the customer counts it, not calendar dates touched
    if event_length_days(req.starts_at, req.ends_at, policy.tz) > policy.max_event_days:
        return TOO_LONG, None
    days = event_days(req.starts_at, req.ends_at, policy.tz)
    # 4
    lead_hours = (
        policy.lead_time_hours.onsite if req.onsite_support else policy.lead_time_hours.remote
    )
    if req.starts_at - now < timedelta(hours=lead_hours):
        return LEAD_TIME, None

    if req.onsite_support:
        # 5
        if req.city not in policy.onsite.cities:
            return ONSITE_CITY_UNSUPPORTED, None
        # 6
        limit = policy.onsite.max_events_per_city_per_day
        if any(onsite_counts.get(day, 0) >= limit for day in days):
            return ONSITE_FULL, None

    # 7
    if req.package is not None and req.expected_guests is not None:
        if req.package not in policy.packages:
            raise ValueError(f"unknown package: {req.package!r}")
        max_guests = policy.packages[req.package].max_guests
        if max_guests is not None and req.expected_guests > max_guests:
            return GUESTS_EXCEED_PACKAGE, _smallest_package_for(req.expected_guests, policy)

    return None, None


def _smallest_package_for(guests: int, policy: Policy) -> str | None:
    """Cheapest package that fits, by capacity rather than by the order the
    packages happen to appear in policy.yaml. None (unlimited) sorts last."""
    ordered = sorted(
        policy.packages.items(),
        key=lambda item: (item[1].max_guests is None, item[1].max_guests or 0),
    )
    for name, package in ordered:
        if package.max_guests is None or package.max_guests >= guests:
            return name
    return None


def _suggest(
    req: AvailabilityRequest,
    *,
    now: datetime,
    onsite_counts: dict[date, int],
    policy: Policy,
) -> tuple[date, ...]:
    """The nearest available days at the same clock times, looking forward."""
    found: list[date] = []
    for offset in range(1, policy.availability.suggestion_search_days + 1):
        candidate = replace(
            req,
            starts_at=_shift_days(req.starts_at, offset, policy.tz),
            ends_at=_shift_days(req.ends_at, offset, policy.tz),
        )
        reason, _ = _first_failure(
            candidate, now=now, onsite_counts=onsite_counts, policy=policy
        )
        if reason is None:
            found.append(candidate.starts_at.astimezone(policy.tz).date())
            if len(found) == policy.availability.suggestion_count:
                break
    return tuple(found)


def _shift_days(moment: datetime, days: int, tz: ZoneInfo) -> datetime:
    """Same wall-clock time, `days` later — not a raw 24h addition, so the
    times a customer asked for stay the times they get."""
    local = moment.astimezone(tz)
    return datetime.combine(local.date() + timedelta(days=days), local.time(), tzinfo=tz)
