from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from hijridate import Gregorian, Hijri

from app.config import Policy
from app.assistant_domain.dates.intents import (
    AbsoluteDate, Ambiguous, ClockTime, DateIntent, DayOnly, EventAnchored,
    PartOfDay, PrayerTime, RelativeDay, RelativeWeekday, ResolvedWhen,
    TimeIntent, Unclear,
)

RIYADH = ZoneInfo("Asia/Riyadh")

# Your intents use "sat".."fri"; Python's weekday() is Monday=0.
WEEKDAY_INDEX = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}

# For reading the date back to the customer. The weekday matters: hearing
# "الخميس" is how someone catches a date that's a day off.
WEEKDAYS_AR = {
    0: "الاثنين", 1: "الثلاثاء", 2: "الأربعاء", 3: "الخميس",
    4: "الجمعة", 5: "السبت", 6: "الأحد",
}
GREGORIAN_MONTHS_AR = {
    1: "يناير", 2: "فبراير", 3: "مارس", 4: "أبريل", 5: "مايو", 6: "يونيو",
    7: "يوليو", 8: "أغسطس", 9: "سبتمبر", 10: "أكتوبر", 11: "نوفمبر", 12: "ديسمبر",
}

# Approximate prayer times, derived from a maghrib table by city and month.
# Every use appends "وقت الصلاة تقريبي" — precise Umm al-Qura calculation is a
# later refinement, and the assistant confirms the time with the customer.
MAGHRIB_BY_MONTH = {          # Riyadh; Jeddah is ~20 minutes later
    1: (17, 30), 2: (17, 55), 3: (18, 15), 4: (18, 30), 5: (18, 45), 6: (18, 55),
    7: (18, 55), 8: (18, 40), 9: (18, 15), 10: (17, 50), 11: (17, 30), 12: (17, 25),
}
CITY_OFFSET_MINUTES = {"riyadh": 0, "dammam": -10, "jeddah": 20}

# Prayer times relative to maghrib, in minutes.
PRAYER_OFFSET_FROM_MAGHRIB = {
    "fajr": -13 * 60 - 30,   # ~dawn; the widest seasonal error of the five
    "dhuhr": -6 * 60,
    "asr": -3 * 60,
    "maghrib": 0,
    "isha": 90,
}

PART_OF_DAY_HOUR = {
    "morning": 9, "afternoon": 15, "evening": 20, "late_night": 23,
}


def _resolve_date(intent, *, today: date, assumptions: list[str]) -> date | Ambiguous:
    """One day, or a question. No times involved.

    Appends to `assumptions` whenever it has to guess.
    """
    if isinstance(intent, RelativeDay):
        return today + timedelta(days=intent.offset)

    if isinstance(intent, RelativeWeekday):
        gap = (WEEKDAY_INDEX[intent.weekday] - today.weekday()) % 7
        if gap == 0:
            gap = 7          # "الجمعة الجاية" on a Friday means next week
        if intent.which == "after_next":
            gap += 7
        return today + timedelta(days=gap)

    if isinstance(intent, AbsoluteDate):
        if intent.calendar == "gregorian":
            if intent.year is not None:
                return date(intent.year, intent.month, intent.day)
            # No year: this year if it's still ahead, otherwise next.
            candidate = date(today.year, intent.month, intent.day)
            if candidate < today:
                candidate = date(today.year + 1, intent.month, intent.day)
                assumptions.append(f"افترضت سنة {candidate.year}")
            return candidate

        # hijri — same rule, in the Hijri calendar
        hijri_today = Gregorian.fromdate(today).to_hijri()
        year = intent.year if intent.year is not None else hijri_today.year
        candidate = date(*Hijri(year, intent.month, intent.day).to_gregorian().datetuple())
        if intent.year is None and candidate < today:
            year += 1
            candidate = date(*Hijri(year, intent.month, intent.day).to_gregorian().datetuple())
            assumptions.append(f"افترضت سنة {year} هجرية")
        return candidate

    if isinstance(intent, DayOnly):
        # "يوم ١٧" is genuinely two dates. Never pick one.
        # Roll to the next MONTH when the day has passed, not the next year.
        month, year = today.month, today.year
        if intent.day < today.day:
            month, year = (1, year + 1) if month == 12 else (month + 1, year)
        gregorian = date(year, month, intent.day)

        h = Gregorian.fromdate(today).to_hijri()
        h_month, h_year = h.month, h.year
        if intent.day < h.day:
            h_month, h_year = (1, h_year + 1) if h_month == 12 else (h_month + 1, h_year)
        hijri = date(*Hijri(h_year, h_month, intent.day).to_gregorian().datetuple())

        return Ambiguous(
            candidates=tuple(sorted({gregorian, hijri})),
            question_ar=f"تقصد {intent.day} ميلادي ({gregorian}) ولا {intent.day} هجري ({hijri})؟",
        )

    if isinstance(intent, EventAnchored):
        if intent.anchor == "national_day":
            return _resolve_date(
                AbsoluteDate(calendar="gregorian", month=9, day=23),
                today=today, assumptions=assumptions,
            )
        if intent.anchor == "founding_day":
            return _resolve_date(
                AbsoluteDate(calendar="gregorian", month=2, day=22),
                today=today, assumptions=assumptions,
            )

        # Eid: "بعد العيد" without a day number is a question, not a date.
        if intent.offset is None:
            return Ambiguous(
                candidates=(),
                question_ar="أي يوم من أيام العيد بالضبط؟ أول يوم، ثاني يوم، ولا ثالث يوم؟",
            )
        month, day = (10, 1) if intent.anchor == "eid_fitr" else (12, 10)
        first_day = _resolve_date(
            AbsoluteDate(calendar="hijri", month=month, day=day),
            today=today, assumptions=assumptions,
        )
        assumptions.append("موعد العيد يعتمد على رؤية الهلال، فقد يتغير يوم")
        return first_day + timedelta(days=intent.offset)

    if isinstance(intent, Unclear):
        return Ambiguous(
            candidates=(),
            question_ar="ما قدرت أفهم التاريخ. تقدر تحدده لي؟",
        )

    raise NotImplementedError(f"date intent not handled yet: {intent.kind}")


def _resolve_time(intent, *, on: date, city: str | None) -> tuple[time, list[str]]:
    """A clock time plus any assumptions made to get there."""
    assumptions: list[str] = []

    if isinstance(intent, ClockTime):
        hour = intent.hour
        if intent.period == "pm" and hour < 12:
            hour += 12
        elif intent.period == "am" and hour == 12:
            hour = 0
        elif intent.period == "unspecified":
            # 1–6 almost always means the evening for an event.
            if 1 <= hour <= 6:
                hour += 12
                assumptions.append(f"افترضت {intent.hour} مساءً")
            else:
                assumptions.append(f"افترضت {hour}:00")
        return time(hour, intent.minute), assumptions

    if isinstance(intent, PartOfDay):
        hour = PART_OF_DAY_HOUR[intent.part]
        assumptions.append(f"افترضت الساعة {hour}:00")
        return time(hour), assumptions

    if isinstance(intent, PrayerTime):
        if city is None:
            city = "riyadh"
            assumptions.append("افترضت توقيت الرياض")
        h, m = MAGHRIB_BY_MONTH[on.month]
        total = (
            h * 60 + m
            + CITY_OFFSET_MINUTES.get(city, 0)
            + PRAYER_OFFSET_FROM_MAGHRIB[intent.prayer]
            + intent.offset_minutes
        )
        total %= 24 * 60
        assumptions.append("وقت الصلاة تقريبي")
        return time(total // 60, total % 60), assumptions

    raise NotImplementedError(f"time intent not handled yet: {intent.kind}")


def resolve(date_intent, start_time, end_time, *, days, now, policy, city=None):
    today = now.astimezone(RIYADH).date()

    assumptions: list[str] = []

    day = _resolve_date(date_intent, today=today, assumptions=assumptions)
    if isinstance(day, Ambiguous):
        return day

    start_t, a = _resolve_time(start_time, on=day, city=city); assumptions += a
    end_t, a = _resolve_time(end_time, on=day, city=city); assumptions += a

    start = datetime.combine(day, start_t, tzinfo=RIYADH)
    end = datetime.combine(day + timedelta(days=days - 1), end_t, tzinfo=RIYADH)
    if end_t <= start_t:
        end += timedelta(days=1)
        assumptions.append("النهاية بعد منتصف الليل، فاعتبرت أنها في اليوم اللي بعده")

    hijri = Gregorian.fromdate(day).to_hijri()
    gregorian_text = (
        f"{WEEKDAYS_AR[day.weekday()]} {day.day} {GREGORIAN_MONTHS_AR[day.month]} {day.year}"
    )
    hijri_text = f"{hijri.day} {hijri.month_name('ar')} {hijri.year}"

    return ResolvedWhen(
        start=start, end=end,
        gregorian_text=gregorian_text, hijri_text=hijri_text,
        assumptions=tuple(assumptions),
    )