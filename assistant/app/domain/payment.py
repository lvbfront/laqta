"""Payment deadlines and refunds (policy.yaml's payment_deadline / refunds).

Pure: both take `now` (or the anchor time) from the caller.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from app.config import Policy, RefundTier


def payment_deadline(*, tentative_at: datetime, starts_at: datetime, policy: Policy) -> datetime:
    """The earlier of "N hours after the booking went tentative" and "M hours
    before the event starts" — whichever comes first (spec §2).

    Recomputed whenever `starts_at` moves, which is why prepare_reschedule
    passes the new start: a deadline anchored to the old start can otherwise
    fall after the new event date.
    """
    return min(
        tentative_at + timedelta(hours=policy.payment_deadline.after_tentative_hours),
        starts_at - timedelta(hours=policy.payment_deadline.before_start_hours),
    )


def refund_applies(status: str, policy: Policy) -> bool:
    """Whether cancelling a booking in `status` falls under policy.refunds at
    all. An unpaid booking has nothing to refund and nothing is kept from it:
    no tier, no percentage — not 0%, not 100% (taxonomy 11)."""
    return status in policy.refunds_apply_to


def refund_tier(*, starts_at: datetime, now: datetime, policy: Policy) -> RefundTier:
    """The tier that applies to cancelling at `now`. Tiers are ordered
    descending and the last one is 0, both enforced when policy.yaml loads.

    Returned whole, not just its percent, so a caller can say which cutoff
    produced the figure — a number that changes overnight with no reason
    given reads as arbitrary (taxonomy 9)."""
    hours_before = (starts_at - now) / timedelta(hours=1)
    for tier in policy.refunds:
        if hours_before >= tier.min_hours_before:
            return tier
    return policy.refunds[-1]


def refund_percent(*, starts_at: datetime, now: datetime, policy: Policy) -> int:
    return refund_tier(starts_at=starts_at, now=now, policy=policy).percent
