"""The booking state machine (spec §5).

No I/O and no clock: `now` is always a parameter, which is what makes a fake
clock possible in layer 4. apply() mutates the booking and appends its
BookingEvent to booking.events; persisting is the caller's transaction.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Callable, Final, TypeAlias

from app.config import Policy
from app.models.booking import Booking
from app.models.booking_event import BookingEvent
from app.models.enums import BookingStatus as Status

# The trigger written on the creating event. Deliberately NOT a Trigger
# member: creation is not a transition out of anything, record_creation() is
# the only thing that writes it, and apply() cannot be called with it at all.
CREATION_TRIGGER: Final = "confirm_booking"


class Trigger(str, Enum):
    """Live transitions only — every member appears in TRANSITIONS."""

    mark_paid = "mark_paid"
    payment_expired = "payment_expired"
    cancel = "cancel"
    reschedule = "reschedule"
    window_open = "window_open"
    window_close = "window_close"


class InvalidTransition(Exception):
    def __init__(self, status: Status | None, trigger: Trigger | str) -> None:
        self.status = status
        self.trigger = trigger
        current = status.value if status is not None else "a new booking"
        name = getattr(trigger, "value", trigger)
        super().__init__(f"{name} is not allowed from {current}")


class GuardFailed(Exception):
    def __init__(self, trigger: Trigger, guard_name: str) -> None:
        self.trigger = trigger
        self.guard_name = guard_name
        super().__init__(f"{trigger.value} refused by {guard_name}")


Guard: TypeAlias = Callable[[Booking, datetime, Policy], bool]


# --- Guards. Every number comes from policy.yaml.


def payment_deadline_passed(booking: Booking, now: datetime, policy: Policy) -> bool:
    return now >= booking.payment_due_at


def before_free_reschedule_cutoff(booking: Booking, now: datetime, policy: Policy) -> bool:
    # Measured against the booking's *current* start, so apply() checks this
    # before it writes the new window.
    return now <= booking.starts_at - timedelta(hours=policy.free_reschedule_before_hours)


def upload_window_due_to_open(booking: Booking, now: datetime, policy: Policy) -> bool:
    return now >= booking.starts_at - timedelta(hours=policy.upload_opens_before_hours)


def upload_window_due_to_close(booking: Booking, now: datetime, policy: Policy) -> bool:
    return now >= booking.ends_at + timedelta(hours=policy.upload_closes_after_hours)


@dataclass(frozen=True)
class Transition:
    # None = stay in the current status (reschedule).
    to: Status | None = None
    guard: Guard | None = None


TRANSITIONS: dict[tuple[Status, Trigger], Transition] = {
    (Status.tentative, Trigger.mark_paid): Transition(to=Status.confirmed),
    (Status.tentative, Trigger.payment_expired): Transition(
        to=Status.cancelled, guard=payment_deadline_passed
    ),
    # No before_live guard on cancel: the table is the guard. There is no
    # (live, cancel) or (ended, cancel) key, so those raise InvalidTransition.
    (Status.tentative, Trigger.cancel): Transition(to=Status.cancelled),
    (Status.confirmed, Trigger.cancel): Transition(to=Status.cancelled),
    (Status.tentative, Trigger.reschedule): Transition(guard=before_free_reschedule_cutoff),
    (Status.confirmed, Trigger.reschedule): Transition(guard=before_free_reschedule_cutoff),
    # Not reachable from tentative: an unpaid booking never goes live.
    (Status.confirmed, Trigger.window_open): Transition(
        to=Status.live, guard=upload_window_due_to_open
    ),
    (Status.live, Trigger.window_close): Transition(
        to=Status.ended, guard=upload_window_due_to_close
    ),
}


def record_creation(
    booking: Booking, *, now: datetime, actor: str, reason: str | None = None
) -> Booking:
    """First saved state is `tentative` — a draft lives in a confirmation
    token, never as a row (spec §5)."""
    if booking.status is not None:
        raise InvalidTransition(booking.status, CREATION_TRIGGER)
    booking.status = Status.tentative
    booking.version = 1
    booking.events.append(
        BookingEvent(
            from_status=None,
            to_status=Status.tentative,
            trigger=CREATION_TRIGGER,
            actor=actor,
            reason=reason,
            at=now,
        )
    )
    return booking


def can_apply(booking: Booking, trigger: Trigger, *, now: datetime, policy: Policy) -> Transition:
    """Would apply() succeed? Raises exactly what apply() would raise and
    changes nothing.

    This is what the prepare_* tools use: a prepare must verify everything
    without touching the booking (spec §8), so it cannot call apply() and
    undo it.
    """
    transition = TRANSITIONS.get((booking.status, trigger))
    if transition is None:
        raise InvalidTransition(booking.status, trigger)
    if transition.guard is not None and not transition.guard(booking, now, policy):
        raise GuardFailed(trigger, transition.guard.__name__)
    return transition


def apply(
    booking: Booking,
    trigger: Trigger,
    *,
    now: datetime,
    policy: Policy,
    actor: str,
    reason: str | None = None,
    new_window: tuple[datetime, datetime] | None = None,
) -> Booking:
    """Apply `trigger` to `booking`, or raise.

    InvalidTransition: the pair is not in TRANSITIONS.
    GuardFailed: the pair is allowed but its time condition is not met.

    `new_window` is required for reschedule and rejected otherwise. Whether
    the new window is *available* is not decided here — that is checked
    under the capacity lock by the caller (spec §6), because it needs the DB.
    """
    if (new_window is not None) != (trigger is Trigger.reschedule):
        raise ValueError("new_window is required for reschedule and rejected for every other trigger")

    transition = can_apply(booking, trigger, now=now, policy=policy)

    from_status = booking.status
    to_status = transition.to if transition.to is not None else from_status

    if new_window is not None:
        starts_at, ends_at = new_window
        if ends_at <= starts_at:
            raise ValueError("new_window ends before it starts")
        if reason is None:
            reason = f"{booking.starts_at.isoformat()} → {starts_at.isoformat()}"
        booking.starts_at = starts_at
        booking.ends_at = ends_at

    booking.status = to_status
    booking.version += 1
    booking.events.append(
        BookingEvent(
            from_status=from_status,
            to_status=to_status,
            trigger=trigger.value,
            actor=actor,
            reason=reason,
            at=now,
        )
    )
    return booking
