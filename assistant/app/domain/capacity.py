"""Onsite capacity counting and locking (spec §6).

Why an advisory lock and not SELECT ... FOR UPDATE: the row that would
breach the limit does not exist yet. Row locks can only lock rows that are
already there, so two transactions both counting "1 of 2" would both insert
and both be right about what they saw — a phantom. Locking the *key*
(onsite:{city}:{day}) instead serialises the count-then-insert, and
pg_advisory_xact_lock releases automatically when the transaction ends.

This is the one module in app/domain/ that touches the database. It still
takes `now` from the caller and never reads a clock.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import date, datetime, timedelta

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.config import Policy
from app.domain.availability import (
    AvailabilityRequest,
    AvailabilityResult,
    check,
    event_days,
)
from app.models.booking import Booking
from app.models.enums import BookingStatus

# Cancelled and ended bookings give their slot back.
OCCUPYING_STATUSES = (BookingStatus.tentative, BookingStatus.confirmed, BookingStatus.live)

MIDNIGHT = datetime.min.time()


def onsite_day_key(city: str, day: date) -> str:
    return f"onsite:{city}:{day.isoformat()}"


def lock_onsite_days(session: Session, city: str, days: Iterable[date]) -> None:
    """Take the per-day advisory locks, always in ascending day order.

    The sort is the deadlock prevention: two multi-day events wanting the
    same days in opposite orders would otherwise each hold what the other
    needs next. Callers must be inside a transaction — the locks last until
    it commits or rolls back.
    """
    for day in sorted(set(days)):
        session.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
            {"key": onsite_day_key(city, day)},
        )


def count_onsite_per_day(
    session: Session,
    city: str,
    days: Iterable[date],
    *,
    policy: Policy,
    exclude_booking_id: uuid.UUID | None = None,
) -> dict[date, int]:
    """How many onsite bookings already occupy each of `days` (local dates).

    `exclude_booking_id` is for reschedules: a booking must not count against
    itself when it is the one being moved.
    """
    wanted = set(days)
    if not wanted:
        return {}

    tz = policy.tz
    window_start = datetime.combine(min(wanted), MIDNIGHT, tzinfo=tz)
    window_end = datetime.combine(max(wanted) + timedelta(days=1), MIDNIGHT, tzinfo=tz)

    stmt = select(Booking.starts_at, Booking.ends_at).where(
        Booking.city == city,
        Booking.onsite_support.is_(True),
        Booking.status.in_(OCCUPYING_STATUSES),
        Booking.starts_at < window_end,
        Booking.ends_at >= window_start,
    )
    if exclude_booking_id is not None:
        stmt = stmt.where(Booking.id != exclude_booking_id)

    counts = dict.fromkeys(wanted, 0)
    for starts_at, ends_at in session.execute(stmt):
        for day in event_days(starts_at, ends_at, tz):
            if day in counts:
                counts[day] += 1
    return counts


def check_without_lock(
    session: Session,
    req: AvailabilityRequest,
    *,
    now: datetime,
    policy: Policy,
    exclude_booking_id: uuid.UUID | None = None,
) -> AvailabilityResult:
    """Read-only availability, taking no locks.

    This is what the prepare_* tools use: a prepare must not hold a capacity
    lock across the customer's reply. The answer is therefore advisory, and
    confirm_action rechecks under the lock before committing anything.
    """
    days = event_days(req.starts_at, req.ends_at, policy.tz)
    counts: dict[date, int] = {}
    if req.onsite_support and req.city in policy.onsite.cities:
        counts = count_onsite_per_day(
            session,
            req.city,
            _suggestion_window(days, policy),
            policy=policy,
            exclude_booking_id=exclude_booking_id,
        )
    return check(req, now=now, onsite_counts=counts, policy=policy)


def check_under_lock(
    session: Session,
    req: AvailabilityRequest,
    *,
    now: datetime,
    policy: Policy,
    exclude_booking_id: uuid.UUID | None = None,
) -> AvailabilityResult:
    """Lock the request's onsite days, then count and check (spec §6).

    Call this inside a transaction, and create the booking before committing:
    an ok result is only guaranteed while the locks are held. The sequence is
    begin → lock → count → check → create → adapter → commit.

    Only onsite requests in a supported city take locks; a remote booking has
    no capacity to contend for and must not serialise behind one.

    The counts behind `suggestions` come from a window read outside the
    locked days, so a suggestion is advisory, never a reservation.
    """
    if req.onsite_support and req.city in policy.onsite.cities:
        lock_onsite_days(session, req.city, event_days(req.starts_at, req.ends_at, policy.tz))
    # Counted after the locks are held, so the answer holds until commit.
    return check_without_lock(
        session, req, now=now, policy=policy, exclude_booking_id=exclude_booking_id
    )


def _suggestion_window(days: tuple[date, ...], policy: Policy) -> tuple[date, ...]:
    """The event's own days plus the lookahead suggestions may reach into."""
    first = min(days)
    last = max(days) + timedelta(days=policy.availability.suggestion_search_days)
    return tuple(first + timedelta(days=offset) for offset in range((last - first).days + 1))
