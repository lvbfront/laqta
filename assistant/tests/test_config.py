from __future__ import annotations

import pytest
import yaml
from pydantic import ValidationError

from app.config import POLICY_PATH, Policy, load_policy


def _raw() -> dict:
    with POLICY_PATH.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def test_policy_yaml_loads_with_spec_values(policy: Policy):
    assert policy.timezone == "Asia/Riyadh"
    assert policy.lead_time_hours.remote == 48
    assert policy.lead_time_hours.onsite == 168
    assert policy.max_event_days == 3
    assert policy.onsite.max_events_per_city_per_day == 2
    assert policy.onsite.cities == ("jeddah", "riyadh", "dammam")
    assert [(t.min_hours_before, t.percent) for t in policy.refunds] == [(168, 100), (48, 50), (0, 0)]
    assert policy.refunds_apply_to == ("confirmed",)
    assert policy.packages["premium"].max_guests is None
    assert policy.packages["starter"].max_guests == 300
    assert policy.strict_mode.forbidden_addons == ("extended_retention",)
    assert "extended_retention" in policy.addons
    assert "onsite_support" not in policy.addons  # it is a booking field, not an add-on
    assert policy.confirmation_ttl_minutes == 10
    assert policy.availability.suggestion_count == 3
    assert policy.availability.suggestion_search_days == 30


def test_strict_mode_exclusions_are_real_addons(policy: Policy):
    """A forbidden add-on that is not in the catalogue could never be
    submitted anyway, so the exclusion would be silently dead."""
    assert set(policy.strict_mode.forbidden_addons) <= set(policy.addons)


def test_an_exclusion_outside_the_catalogue_is_rejected():
    raw = _raw()
    raw["strict_mode"]["forbidden_addons"] = ["gold_plated_drone"]
    with pytest.raises(ValidationError, match="gold_plated_drone"):
        Policy.model_validate(raw)


def test_handoff_routing_covers_every_reason_code(policy: Policy):
    """Every reason the assistant can hand off with must have a team, or the
    handoff tool raises at runtime."""
    from app.models.enums import Team, TicketPriority, TicketReason

    assert set(policy.handoff.routing) == {reason.value for reason in TicketReason}
    assert {Team(team) for team in policy.handoff.routing.values()}
    assert set(policy.handoff.to_team_manager) <= set(policy.handoff.routing)
    assert {TicketPriority(p) for p in policy.handoff.priority_by_reason.values()}
    assert set(policy.handoff.priority_by_reason) <= set(policy.handoff.routing)


def test_handoff_response_times_are_defined_for_every_priority(policy: Policy):
    from app.models.enums import TicketPriority

    for priority in TicketPriority:
        assert policy.handoff.acknowledge_within_minutes.for_priority(priority.value) > 0
        assert policy.handoff.escalate_after_reminder_minutes.for_priority(priority.value) > 0


def test_policy_is_immutable(policy: Policy):
    with pytest.raises(ValidationError):
        policy.max_event_days = 99


def test_unknown_key_is_rejected(tmp_path):
    raw = _raw()
    raw["max_event_dayz"] = 5
    path = tmp_path / "policy.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(ValidationError, match="max_event_dayz"):
        load_policy(path)


def test_refund_tiers_must_descend():
    raw = _raw()
    raw["refunds"] = list(reversed(raw["refunds"]))
    with pytest.raises(ValidationError, match="descending"):
        Policy.model_validate(raw)


def test_refund_tiers_must_end_at_zero():
    raw = _raw()
    raw["refunds"] = raw["refunds"][:-1]
    with pytest.raises(ValidationError, match="min_hours_before: 0"):
        Policy.model_validate(raw)


def test_onsite_package_references_must_exist():
    raw = _raw()
    raw["onsite"]["included_in"] = ["platinum"]
    with pytest.raises(ValidationError, match="platinum"):
        Policy.model_validate(raw)


def test_unknown_timezone_is_rejected():
    raw = _raw()
    raw["timezone"] = "Asia/Nowhere"
    with pytest.raises(Exception):
        Policy.model_validate(raw)


def test_refunds_apply_to_real_statuses_and_never_an_unpaid_one(policy: Policy):
    """The KB: an unpaid tentative booking cancels at any time without fees."""
    from app.models.enums import BookingStatus

    assert {BookingStatus(status) for status in policy.refunds_apply_to}
    assert BookingStatus.tentative.value not in policy.refunds_apply_to
