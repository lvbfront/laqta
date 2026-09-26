from __future__ import annotations

from datetime import timedelta

import pytest

from app.domain.payment import payment_deadline, refund_applies, refund_percent
from tests.factories import REFERENCE_NOW as NOW


def test_deadline_is_the_earlier_of_the_two_rules(policy):
    """A far-off event: the "N hours after booking" rule bites first."""
    starts_at = NOW + timedelta(days=60)
    assert payment_deadline(tentative_at=NOW, starts_at=starts_at, policy=policy) == NOW + timedelta(
        hours=policy.payment_deadline.after_tentative_hours
    )


def test_a_soon_event_uses_the_before_start_rule(policy):
    starts_at = NOW + timedelta(hours=policy.payment_deadline.after_tentative_hours)
    assert payment_deadline(tentative_at=NOW, starts_at=starts_at, policy=policy) == (
        starts_at - timedelta(hours=policy.payment_deadline.before_start_hours)
    )


def test_the_deadline_always_precedes_the_event(policy):
    """The property that matters: a deadline after the event is useless."""
    for days in (2, 3, 5, 10, 60):
        starts_at = NOW + timedelta(days=days)
        assert payment_deadline(tentative_at=NOW, starts_at=starts_at, policy=policy) < starts_at


@pytest.mark.parametrize(
    "hours_before,expected",
    [
        (24 * 30, 100),
        (168, 100),  # exactly the top tier's boundary
        (167, 50),
        (72, 50),
        (48, 50),  # exactly the middle tier's boundary
        (47, 0),
        (1, 0),
        (0, 0),
        (-5, 0),  # already started
    ],
)
def test_refund_tiers(policy, hours_before, expected):
    starts_at = NOW + timedelta(hours=hours_before)
    assert refund_percent(starts_at=starts_at, now=NOW, policy=policy) == expected


def test_refund_tiers_come_from_policy(policy):
    """Spot-check against policy rather than hardcoded numbers, so changing
    policy.yaml changes the expectation."""
    top = policy.refunds[0]
    starts_at = NOW + timedelta(hours=top.min_hours_before)
    assert refund_percent(starts_at=starts_at, now=NOW, policy=policy) == top.percent


def test_refunds_apply_only_to_paid_bookings(policy):
    """Taxonomy 11: an unpaid tentative booking is outside the table
    altogether, not in its 0% tier."""
    assert refund_applies("confirmed", policy)
    assert not refund_applies("tentative", policy)
