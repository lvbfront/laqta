"""The Arabic label table (taxonomy 3 and 5): complete, KB-consistent, and
the aliases resolve where they should and nowhere else. No database."""

from __future__ import annotations

import pytest

from app.config import KB_PATH
from app.models.enums import BookingStatus, MatchMode, Team
from app.tools.labels import (
    ADDON_ALIASES,
    ADDON_AR,
    CITY_ALIASES,
    CITY_AR,
    MATCH_MODE_ALIASES,
    MATCH_MODE_AR,
    PACKAGE_ALIASES,
    PACKAGE_AR,
    STATUS_AR,
    TEAM_AR,
    canonical_addon,
    canonical_city,
    canonical_match_mode,
    canonical_package,
    days_ar,
    duration_ar,
)

KB = KB_PATH.read_text(encoding="utf-8")


def test_every_key_the_tools_use_has_an_arabic_label(policy):
    """A key without a label would raise inside prepare_booking — or, worse,
    be tempting to fall back to the English key."""
    assert set(PACKAGE_AR) == set(policy.packages)
    assert set(ADDON_AR) == set(policy.addons)
    assert set(MATCH_MODE_AR) == {mode.value for mode in MatchMode}
    assert set(CITY_AR) == set(policy.onsite.cities)
    assert set(PACKAGE_ALIASES) <= set(PACKAGE_AR)
    assert set(MATCH_MODE_ALIASES) <= set(MATCH_MODE_AR)
    assert set(ADDON_ALIASES) <= set(ADDON_AR)
    assert set(CITY_ALIASES) <= set(CITY_AR)
    # Out-only tables: every value a tool result can carry has a name.
    assert set(STATUS_AR) == {status.value for status in BookingStatus}
    assert set(TEAM_AR) == {team.value for team in Team}


@pytest.mark.parametrize(
    "label",
    [
        *PACKAGE_AR.values(), *MATCH_MODE_AR.values(), *ADDON_AR.values(), *CITY_AR.values(),
        *TEAM_AR.values(),
    ],
)
def test_labels_are_the_names_the_kb_uses(label):
    """The model reads the KB and the customer hears the summary; they must
    call things by the same name."""
    assert label in KB


@pytest.mark.parametrize(
    ("canonical", "table", "aliases", "resolve"),
    [
        ("package", PACKAGE_AR, PACKAGE_ALIASES, canonical_package),
        ("match_mode", MATCH_MODE_AR, MATCH_MODE_ALIASES, canonical_match_mode),
        ("addon", ADDON_AR, ADDON_ALIASES, canonical_addon),
        ("city", CITY_AR, CITY_ALIASES, canonical_city),
    ],
)
def test_no_name_resolves_to_two_different_keys(canonical, table, aliases, resolve):
    for key, label in table.items():
        for name in (key, label, *aliases.get(key, ())):
            assert resolve(name) == key, f"{canonical} name {name!r}"


def test_the_three_package_names_from_the_kb():
    assert canonical_package("الأساسية") == "starter"
    assert canonical_package("القياسية") == "standard"
    assert canonical_package("المميزة") == "premium"


@pytest.mark.parametrize(
    ("spelling", "key"),
    [
        (" الأساسية ", "starter"),       # stray whitespace
        ("الاساسية", "starter"),         # hamza dropped, as people type it
        ("الباقة  القياسية", "standard"),  # double space
        ("الوجه والرمز معا", "both"),     # tanween dropped
        ("STARTER", "starter"),
    ],
)
def test_harmless_spelling_differences_still_resolve(spelling, key):
    assert (canonical_package(spelling) if key in PACKAGE_AR else canonical_match_mode(spelling)) == key


@pytest.mark.parametrize("unknown", ["الذهبية", "باقة كبيرة", "platinum", "", 3, None])
def test_an_unknown_name_is_passed_through_for_validation_to_reject(unknown):
    assert canonical_package(unknown) == unknown


def test_day_and_hour_wording():
    assert days_ar(7) == "7 أيام"
    assert days_ar(14) == "14 يوم"
    assert days_ar(2) == "يومين"
    assert duration_ar(168) == "7 أيام"
    assert duration_ar(48) == "48 ساعة"


@pytest.mark.parametrize(
    ("spelling", "slug"),
    [
        ("جدة", "jeddah"), ("جده", "jeddah"), ("جدّة", "jeddah"), ("Jeddah", "jeddah"),
        ("الرياض", "riyadh"), ("رياض", "riyadh"), ("مدينة الرياض", "riyadh"),
        ("الدمام", "dammam"), ("دمام", "dammam"), ("DAMMAM", "dammam"),
    ],
)
def test_city_spellings_and_article_variants_resolve(spelling, slug):
    assert canonical_city(spelling) == slug


@pytest.mark.parametrize("city", ["الخبر", "الظهران", "مكة", "الطائف", "جدة الجديدة", "abha"])
def test_any_other_city_is_returned_as_given_never_the_nearest_supported(city):
    """الخبر and الظهران sit next to الدمام; mapping them there would book a
    crew into the wrong city and the summary would hide it."""
    assert canonical_city(f"  {city} ") == city
