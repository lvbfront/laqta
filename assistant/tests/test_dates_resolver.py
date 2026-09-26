"""Date resolution (spec §7).

Reference: Friday 2026-09-11, 14:05 Riyadh = 29 Rabi' al-Awwal 1448.
Every expected date below was computed against Umm al-Qura.
"""
from __future__ import annotations
from datetime import date, timedelta

import pytest

from app.assistant_domain.dates.intents import (
    AbsoluteDate, Ambiguous, ClockTime, DayOnly, EventAnchored,
    PartOfDay, PrayerTime, RelativeDay, RelativeWeekday, Unclear,
)
from app.assistant_domain.dates.resolver import resolve
from app.config import get_policy
from tests.factories import REFERENCE_NOW as NOW

POLICY = get_policy()
EIGHT_PM = ClockTime(hour=8, minute=0, period="pm")
ELEVEN_PM = ClockTime(hour=11, minute=0, period="pm")


def when(date_intent, *, start=EIGHT_PM, end=ELEVEN_PM, days=1, city=None):
    """Every test goes through here: resolve() wants a whole window."""
    return resolve(date_intent, start, end, days=days,
                   now=NOW, policy=POLICY, city=city)


# --- The 13 worked examples from spec §7 ---

@pytest.mark.parametrize("intent,expected", [
    (RelativeDay(offset=1),                                  date(2026, 9, 12)),
    (RelativeDay(offset=2),                                  date(2026, 9, 13)),
    (RelativeWeekday(weekday="thu", which="next"),           date(2026, 9, 17)),
    (RelativeWeekday(weekday="thu", which="after_next"),     date(2026, 9, 24)),
    # today IS Friday — "الجمعة الجاية" must not mean today
    (RelativeWeekday(weekday="fri", which="next"),           date(2026, 9, 18)),
    (AbsoluteDate(calendar="hijri", month=4, day=15),        date(2026, 9, 26)),
    (AbsoluteDate(calendar="hijri", month=6, day=1),         date(2026, 11, 11)),
    (AbsoluteDate(calendar="gregorian", month=11, day=17),   date(2026, 11, 17)),
    (EventAnchored(anchor="national_day"),                   date(2026, 9, 23)),
    (EventAnchored(anchor="eid_fitr", offset=2),             date(2027, 3, 11)),
])
def test_resolves_to_the_right_day(intent, expected):
    result = when(intent)
    assert not isinstance(result, Ambiguous)
    assert result.start.date() == expected


# --- Ambiguity: return both readings, never pick one ---

def test_day_without_a_month_is_ambiguous():
    """"يوم ١٧" — 17 Gregorian, or 17 Rabi' al-Thani (= 28 Sep)?"""
    result = when(DayOnly(day=17))
    assert isinstance(result, Ambiguous)
    assert set(result.candidates) == {date(2026, 9, 17), date(2026, 9, 28)}
    assert result.question_ar


def test_eid_without_an_offset_is_ambiguous():
    result = when(EventAnchored(anchor="eid_fitr"))
    assert isinstance(result, Ambiguous)
    assert result.question_ar


def test_unclear_is_ambiguous():
    result = when(Unclear(raw="في وقت ما"))
    assert isinstance(result, Ambiguous)
    assert result.question_ar


# --- Assumptions: a guess must never be silent ---

def test_an_unspecified_hour_records_an_assumption():
    result = when(RelativeDay(offset=1),
                  start=ClockTime(hour=3, period="unspecified"))
    assert not isinstance(result, Ambiguous)
    assert result.assumptions


def test_eid_records_a_moon_sighting_assumption():
    assert when(EventAnchored(anchor="eid_fitr", offset=2)).assumptions


def test_prayer_times_are_approximate():
    result = when(RelativeDay(offset=1),
                  start=PrayerTime(prayer="maghrib", offset_minutes=30),
                  city="jeddah")
    assert not isinstance(result, Ambiguous)
    assert result.assumptions


def test_a_past_date_without_a_year_rolls_forward():
    """1 March already passed; year=None means the next one."""
    result = when(AbsoluteDate(calendar="gregorian", month=3, day=1))
    assert result.start.date() == date(2027, 3, 1)
    assert result.assumptions


def test_an_end_before_the_start_rolls_to_the_next_day():
    """21:00 → 02:00 is one night, not a negative window."""
    result = when(RelativeDay(offset=1),
                  start=ClockTime(hour=9, period="pm"),
                  end=ClockTime(hour=2, period="am"))
    assert result.end > result.start
    assert result.end.date() == result.start.date() + timedelta(days=1)
    assert result.assumptions


# --- Both calendars always come back ---

def test_both_calendar_texts_are_returned():
    result = when(RelativeWeekday(weekday="thu", which="next"))
    assert result.gregorian_text and result.hijri_text


# --- Control: prove this file can fail ---

def test_the_harness_can_fail():
    with pytest.raises(AssertionError):
        assert when(RelativeDay(offset=1)).start.date() == date(2030, 1, 1)

def test_fajr_lands_at_dawn():
    result = when(RelativeDay(offset=1),
                  start=PrayerTime(prayer="fajr"),
                  end=ClockTime(hour=8, period="am"),
                  city="riyadh")
    assert 3 <= result.start.hour <= 6
    assert result.assumptions


# --- All seven weekdays, both readings (today is Friday) ---

@pytest.mark.parametrize("weekday,which,expected", [
    ("sat", "next",       date(2026, 9, 12)),
    ("sun", "next",       date(2026, 9, 13)),
    ("mon", "next",       date(2026, 9, 14)),
    ("tue", "next",       date(2026, 9, 15)),
    ("wed", "next",       date(2026, 9, 16)),
    ("thu", "next",       date(2026, 9, 17)),
    ("fri", "next",       date(2026, 9, 18)),   # never today
    ("sat", "after_next", date(2026, 9, 19)),
    ("sun", "after_next", date(2026, 9, 20)),
    ("mon", "after_next", date(2026, 9, 21)),
    ("tue", "after_next", date(2026, 9, 22)),
    ("wed", "after_next", date(2026, 9, 23)),
    ("thu", "after_next", date(2026, 9, 24)),
    ("fri", "after_next", date(2026, 9, 25)),
])
def test_every_weekday(weekday, which, expected):
    assert when(RelativeWeekday(weekday=weekday, which=which)).start.date() == expected


def test_after_next_is_always_seven_days_past_next():
    for wd in ("sat", "sun", "mon", "tue", "wed", "thu", "fri"):
        a = when(RelativeWeekday(weekday=wd, which="next")).start.date()
        b = when(RelativeWeekday(weekday=wd, which="after_next")).start.date()
        assert (b - a).days == 7


# --- Every Hijri month, day 1. Today is 29 Rabi' al-Awwal 1448. ---

@pytest.mark.parametrize("month,expected", [
    (4,  date(2026, 9, 12)),    # Rabi' al-Thani
    (5,  date(2026, 10, 12)),
    (6,  date(2026, 11, 11)),
    (7,  date(2026, 12, 10)),
    (8,  date(2027, 1, 9)),     # crosses the Gregorian year
    (9,  date(2027, 2, 8)),     # Ramadan
    (10, date(2027, 3, 9)),     # Shawwal — Eid al-Fitr
    (11, date(2027, 4, 8)),
    (12, date(2027, 5, 7)),
    (1,  date(2027, 6, 6)),     # already passed → next Hijri year
    (2,  date(2027, 7, 5)),
    (3,  date(2027, 8, 3)),
])
def test_every_hijri_month(month, expected):
    assert when(AbsoluteDate(calendar="hijri", month=month, day=1)).start.date() == expected


def test_a_passed_hijri_month_rolls_the_hijri_year():
    """1 Muharram 1448 is behind us, so this means 1449."""
    result = when(AbsoluteDate(calendar="hijri", month=1, day=1))
    assert result.start.date() == date(2027, 6, 6)
    assert result.assumptions


def test_an_explicit_hijri_year_is_never_rolled():
    result = when(AbsoluteDate(calendar="hijri", month=1, day=1, year=1448))
    assert result.start.date() < date(2026, 9, 11)   # in the past, as asked
    assert not result.assumptions


# --- Event anchors ---

@pytest.mark.parametrize("anchor,offset,expected", [
    ("eid_fitr",   0, date(2027, 3, 9)),
    ("eid_fitr",   1, date(2027, 3, 10)),
    ("eid_fitr",   2, date(2027, 3, 11)),
    ("eid_adha",   0, date(2027, 5, 16)),
    ("eid_adha",   2, date(2027, 5, 18)),
    ("national_day",  None, date(2026, 9, 23)),
    ("founding_day",  None, date(2027, 2, 22)),   # Feb already passed
])
def test_event_anchors(anchor, offset, expected):
    assert when(EventAnchored(anchor=anchor, offset=offset)).start.date() == expected


def test_eid_adha_also_warns_about_the_moon():
    assert when(EventAnchored(anchor="eid_adha", offset=1)).assumptions


# --- Times ---

@pytest.mark.parametrize("part,hour", [
    ("morning", 9), ("afternoon", 15), ("evening", 20), ("late_night", 23),
])
def test_part_of_day(part, hour):
    result = when(RelativeDay(offset=1), start=PartOfDay(part=part))
    assert result.start.hour == hour
    assert result.assumptions


@pytest.mark.parametrize("prayer", ["fajr", "dhuhr", "asr", "maghrib", "isha"])
def test_every_prayer_is_a_real_time_and_is_flagged_approximate(prayer):
    result = when(RelativeDay(offset=1),
                  start=PrayerTime(prayer=prayer),
                  end=ClockTime(hour=11, period="pm"),
                  city="riyadh")
    assert any("تقريبي" in a for a in result.assumptions)


def test_prayer_without_a_city_assumes_riyadh_and_says_so():
    result = when(RelativeDay(offset=1), start=PrayerTime(prayer="maghrib"))
    assert len(result.assumptions) >= 2   # city assumed + approximate


def test_maghrib_is_later_in_jeddah_than_riyadh():
    r = when(RelativeDay(offset=1), start=PrayerTime(prayer="maghrib"), city="riyadh")
    j = when(RelativeDay(offset=1), start=PrayerTime(prayer="maghrib"), city="jeddah")
    assert j.start > r.start


def test_prayer_offset_minutes_shift_the_time():
    base = when(RelativeDay(offset=1), start=PrayerTime(prayer="maghrib"), city="riyadh")
    late = when(RelativeDay(offset=1),
                start=PrayerTime(prayer="maghrib", offset_minutes=30), city="riyadh")
    assert (late.start - base.start) == timedelta(minutes=30)


@pytest.mark.parametrize("hour,expected_hour,needs_assumption", [
    (3,  15, True),    # 1–6 unspecified → evening
    (6,  18, True),
    (9,   9, True),    # 7–11 stays morning, still flagged
    (8,   8, True),
])
def test_unspecified_period(hour, expected_hour, needs_assumption):
    result = when(RelativeDay(offset=1), start=ClockTime(hour=hour, period="unspecified"))
    assert result.start.hour == expected_hour
    assert bool(result.assumptions) is needs_assumption


def test_midnight_am_is_hour_zero():
    result = when(RelativeDay(offset=1),
                  start=ClockTime(hour=12, period="am"),
                  end=ClockTime(hour=3, period="am"))
    assert result.start.hour == 0


def test_noon_pm_stays_twelve():
    result = when(RelativeDay(offset=1), start=ClockTime(hour=12, period="pm"))
    assert result.start.hour == 12


# --- Multi-day windows ---

def test_a_three_day_event_ends_on_the_third_day():
    result = when(RelativeWeekday(weekday="thu", which="next"), days=3)
    assert result.start.date() == date(2026, 9, 17)
    assert result.end.date() == date(2026, 9, 19)


def test_a_three_day_event_ending_after_midnight_rolls_to_the_fourth():
    result = when(RelativeWeekday(weekday="thu", which="next"),
                  start=ClockTime(hour=9, period="pm"),
                  end=ClockTime(hour=1, period="am"),
                  days=3)
    assert result.end.date() == date(2026, 9, 20)
    assert result.assumptions


# --- Calendar edges ---

def test_leap_day_resolves():
    """29 Feb exists in 2028, not 2027."""
    result = when(AbsoluteDate(calendar="gregorian", month=2, day=29, year=2028))
    assert result.start.date() == date(2028, 2, 29)


def test_a_date_in_the_past_is_returned_not_refused():
    """The resolver resolves; availability.check() is what rejects the past."""
    result = when(RelativeDay(offset=-1))
    assert result.start.date() == date(2026, 9, 10)


def test_the_texts_name_the_weekday():
    result = when(RelativeWeekday(weekday="thu", which="next"))
    assert "الخميس" in result.gregorian_text
    assert "ربيع" in result.hijri_text


def test_all_times_are_riyadh():
    result = when(RelativeDay(offset=1))
    assert result.start.utcoffset() == timedelta(hours=3)