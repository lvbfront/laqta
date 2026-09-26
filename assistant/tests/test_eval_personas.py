"""The persona set is itself checked, because a wrong expected value makes the
scorer fail a correct agent — or pass a wrong one.

Everything time- or rule-dependent in `expected` is recomputed here from the
raw policy.yaml by plain arithmetic. Nothing is imported from app/domain or
app/assistant_domain: the expectations must not inherit the agent's bugs.
No database, no model, no API.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
import yaml
from hijridate import Hijri

from app.config import POLICY_PATH
from eval.personas import (
    ADVERSARIAL_KINDS,
    CUSTOMER_ONLY_TOOLS,
    SEED_BOOKING_KEY,
    SPEC_TOOLS,
    TAXONOMY,
    load_fixtures,
    load_personas,
)

RIYADH = ZoneInfo("Asia/Riyadh")
POLICY = yaml.safe_load(POLICY_PATH.read_text(encoding="utf-8"))
PERSONAS = load_personas()
FIXTURES = load_fixtures()
BY_ID = {p.id: p for p in PERSONAS}

# scripts/seed.py: contact 1's onsite booking, 14 days out, 16:00–23:00, premium.
# Duplicated here rather than imported so that a change to the seed shows up
# as a failing expectation instead of silently moving it.
SEED_CONTACT_GENDER = {1: "male", 2: "female", 3: "male"}
SEED_BOOKING_CONTACT = 1


def seed_booking(now: datetime) -> dict:
    day = now.astimezone(RIYADH).date() + timedelta(days=14)
    return {
        "contact": SEED_BOOKING_CONTACT,
        "city": "jeddah",
        "onsite_support": True,
        "status": "confirmed",
        "starts_at": datetime.combine(day, time(16, 0), tzinfo=RIYADH),
        "ends_at": datetime.combine(day, time(23, 0), tzinfo=RIYADH),
    }


def booking_by_key(key: str, now: datetime) -> dict:
    if key == SEED_BOOKING_KEY:
        return seed_booking(now)
    return FIXTURES[key].model_dump()


def hours(delta: timedelta) -> float:
    return delta / timedelta(hours=1)


def refund_tier(starts_at: datetime, now: datetime) -> int:
    before = hours(starts_at - now)
    for tier in POLICY["refunds"]:
        if before >= tier["min_hours_before"]:
            return tier["percent"]
    raise AssertionError("policy has no zero tier")


def customer_length_days(starts_at: datetime, ends_at: datetime) -> int:
    s, e = starts_at.astimezone(RIYADH), ends_at.astimezone(RIYADH)
    spanned = (e.date() - s.date()).days + 1
    return max(spanned - (1 if e.time() < s.time() else 0), 1)


def onsite_days_taken(personas_fixture_keys: list[str], now: datetime, city: str) -> dict[date, int]:
    counts: dict[date, int] = {}
    rows = [seed_booking(now)] + [FIXTURES[k].model_dump() for k in personas_fixture_keys]
    for row in rows:
        if not row["onsite_support"] or row["city"] != city:
            continue
        day = row["starts_at"].astimezone(RIYADH).date()
        end = row["ends_at"].astimezone(RIYADH).date()
        while day <= end:
            counts[day] = counts.get(day, 0) + 1
            day += timedelta(days=1)
    return counts


# --- the set as a whole


def test_there_are_between_20_and_31_personas():
    # The brief asked for 20–30; a6 was added on top of the full set to
    # provoke taxonomy 4 more reliably than a2 alone.
    assert 20 <= len(PERSONAS) <= 31
    assert len(BY_ID) == len(PERSONAS)


def test_every_taxonomy_entry_is_provoked_by_at_least_one_persona():
    covered = {entry for p in PERSONAS for entry in p.taxonomy}
    missing = set(TAXONOMY) - covered
    assert not missing, f"no persona provokes taxonomy entries {sorted(missing)}"


def test_every_adversarial_case_exists_once():
    kinds = sorted(p.adversarial for p in PERSONAS if p.adversarial)
    assert kinds == sorted(ADVERSARIAL_KINDS)


def test_handoff_metrics_have_positives_and_negatives():
    required = [p for p in PERSONAS if p.expected.handoff == "required"]
    forbidden = [p for p in PERSONAS if p.expected.handoff == "forbidden"]
    assert len(required) >= 5 and len(forbidden) >= 5
    reasons = {r for p in required for r in p.expected.handoff_reasons}
    assert reasons == set(POLICY["handoff"]["routing"]), "every reason code needs a required-handoff persona"


def test_spec_tool_list_matches_the_registry():
    """If a tool is renamed, personas must be updated deliberately."""
    from app.tools import registry  # the package import registers every tool

    assert {t.name for t in registry.all_tools()} == SPEC_TOOLS


# --- per persona


@pytest.mark.parametrize("persona", PERSONAS, ids=lambda p: p.id)
class TestPersona:
    def test_everything_it_references_exists(self, persona):
        assert set(persona.fixtures) <= FIXTURES.keys()
        known = set(persona.fixtures) | {SEED_BOOKING_KEY}
        assert persona.template_keys() <= known
        assert set(persona.expected.booking_changes) <= known

    def test_it_only_changes_its_own_bookings(self, persona):
        for key in persona.expected.booking_changes:
            assert booking_by_key(key, persona.now)["contact"] == persona.contact_id

    def test_seeded_identities_keep_their_seeded_gender(self, persona):
        if persona.contact_id is not None:
            assert persona.contact_id in SEED_CONTACT_GENDER
            assert persona.voice.gender == SEED_CONTACT_GENDER[persona.contact_id]

    def test_anonymous_personas_are_not_expected_to_use_customer_tools(self, persona):
        if persona.identity == "anon":
            assert not CUSTOMER_ONLY_TOOLS & set(persona.expected.tools_required)
            assert not persona.expected.booking_changes

    def test_the_simulator_never_sees_english_package_or_enum_names(self, persona):
        """Taxonomy 3 and 5 only mean something if the customer speaks Arabic.
        Checks what the customer literally says; `goal` and `rules` are
        English instructions to the simulator, not lines."""
        visible = " ".join(
            [persona.opening, *persona.hidden_state.values(), *(t.say for t in persona.script)]
        )
        for word in (*POLICY["packages"], *POLICY["addons"], "face", "code", "sequential", "both", "strict"):
            assert word not in visible, f"{word!r} is visible to the simulator"

    def test_a_handoff_team_follows_policy_routing(self, persona):
        exp = persona.expected
        if exp.ticket_team is not None:
            for reason in exp.handoff_reasons:
                assert POLICY["handoff"]["routing"][reason] == exp.ticket_team
        if exp.ticket_priority is not None:
            for reason in exp.handoff_reasons:
                assert POLICY["handoff"]["priority_by_reason"].get(reason, "normal") == exp.ticket_priority

    def test_a_created_booking_is_one_the_spec_allows(self, persona):
        b = persona.expected.created_booking
        if b is None:
            return
        now = persona.now
        assert b.ends_at > b.starts_at
        assert b.starts_at.utcoffset() == timedelta(hours=3), "expected times are Riyadh-local"
        assert customer_length_days(b.starts_at, b.ends_at) <= POLICY["max_event_days"]

        lead = POLICY["lead_time_hours"]["onsite" if b.onsite_support else "remote"]
        assert hours(b.starts_at - now) >= lead

        package = POLICY["packages"][b.package]
        assert package["max_guests"] is None or b.expected_guests <= package["max_guests"]
        assert set(b.addons) <= set(POLICY["addons"])
        if b.strict_mode:
            assert not set(b.addons) & set(POLICY["strict_mode"]["forbidden_addons"])
        if b.onsite_support:
            assert b.city in POLICY["onsite"]["cities"]
            assert b.package in POLICY["onsite"]["included_in"] + POLICY["onsite"]["addon_for"]
            taken = onsite_days_taken(persona.fixtures, now, b.city)
            assert taken.get(b.starts_at.date(), 0) < POLICY["onsite"]["max_events_per_city_per_day"]

        due = min(
            now + timedelta(hours=POLICY["payment_deadline"]["after_tentative_hours"]),
            b.starts_at - timedelta(hours=POLICY["payment_deadline"]["before_start_hours"]),
        )
        assert b.payment_due_at == due

    def test_a_reschedule_is_free_and_the_new_window_is_allowed(self, persona):
        for key, change in persona.expected.booking_changes.items():
            if change.starts_at is None:
                continue
            row = booking_by_key(key, persona.now)
            assert hours(row["starts_at"] - persona.now) >= POLICY["free_reschedule_before_hours"]
            lead = POLICY["lead_time_hours"]["onsite" if row["onsite_support"] else "remote"]
            assert hours(change.starts_at - persona.now) >= lead
            # same clock times, as every reschedule persona asks
            assert change.starts_at.astimezone(RIYADH).time() == row["starts_at"].astimezone(RIYADH).time()
            assert change.ends_at.astimezone(RIYADH).time() == row["ends_at"].astimezone(RIYADH).time()

    def test_the_refund_figure_is_the_policy_tier(self, persona):
        exp = persona.expected
        if exp.refund_percent is None:
            return
        cancelled = [k for k, c in exp.booking_changes.items() if c.status == "cancelled"]
        assert len(cancelled) == 1
        row = booking_by_key(cancelled[0], persona.now)
        assert exp.refund_percent == refund_tier(row["starts_at"], persona.now)


# --- specific claims the persona files make in prose


NOW = datetime(2026, 9, 11, 14, 5, tzinfo=RIYADH)


def test_every_persona_runs_at_the_spec_reference_moment():
    assert {p.now for p in PERSONAS} == {NOW}
    assert NOW.astimezone(timezone.utc) == datetime(2026, 9, 11, 11, 5, tzinfo=timezone.utc)


def test_the_onsite_full_day_really_is_full():
    persona = BY_ID["p03_onsite_full_jeddah"]
    taken = onsite_days_taken(persona.fixtures, NOW, "jeddah")
    assert taken[date(2026, 9, 25)] == POLICY["onsite"]["max_events_per_city_per_day"]


def test_the_onsite_lead_time_persona_is_inside_the_onsite_window_only():
    b = BY_ID["p04_onsite_lead_time"].expected.created_booking
    assert POLICY["lead_time_hours"]["remote"] <= hours(b.starts_at - NOW) < POLICY["lead_time_hours"]["onsite"]


def test_the_late_change_persona_is_inside_the_free_reschedule_cutoff():
    row = FIXTURES["fahad_gala"]
    assert 0 < hours(row.starts_at - NOW) < POLICY["free_reschedule_before_hours"]


def test_the_unpaid_tentative_booking_sits_in_a_nonzero_refund_tier():
    """Otherwise p25 could not tell 'no fee' apart from 'refund 0%'."""
    row = FIXTURES["fahad_workshop_tentative"]
    assert row.status == "tentative"
    assert refund_tier(row.starts_at, NOW) not in (0, 100)


def test_relative_weekday_expectations_land_on_thursday():
    # الخميس الجاي from Friday 11 Sep = 17 Sep; الخميس اللي بعده = 24 Sep.
    for pid, day in [
        ("p01_booking_remote_arabic_package", date(2026, 9, 17)),
        ("p04_onsite_lead_time", date(2026, 9, 17)),
        ("a1_date_change_mid_conversation", date(2026, 9, 24)),
    ]:
        start = BY_ID[pid].expected.created_booking.starts_at
        assert start.date() == day and start.weekday() == 3


def test_hijri_expectations_via_hijridate():
    assert Hijri(1448, 4, 15).to_gregorian().datetuple() == (2026, 9, 26)
    assert BY_ID["p22_hijri_date_assumed_time"].expected.created_booking.starts_at.date() == date(2026, 9, 26)


def test_the_bare_day_really_is_ambiguous():
    """Both readings of يوم ٢٨ are in the future and differ."""
    gregorian = date(2026, 9, 28)
    hijri = date(*Hijri(1448, 4, 28).to_gregorian().datetuple())  # ربيع الأول 28 has passed
    assert gregorian > NOW.date() and hijri > NOW.date() and gregorian != hijri
    assert BY_ID["p21_ambiguous_day"].expected.created_booking.starts_at.date() == gregorian


def test_the_cross_customer_probe_targets_someone_elses_booking():
    persona = BY_ID["p24_cross_customer_probe"]
    assert persona.contact_id != SEED_BOOKING_CONTACT
    assert SEED_BOOKING_KEY in persona.template_keys()
