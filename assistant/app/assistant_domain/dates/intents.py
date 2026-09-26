"""Structured date/time intents (spec §7).

The model never writes a date. It emits one of these, and resolver.resolve()
computes the datetime.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal, Union

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class _Intent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


Weekday = Literal["sat", "sun", "mon", "tue", "wed", "thu", "fri"]


# --- Date ---


class RelativeDay(_Intent):
    """بكرة = +1, بعد بكرة = +2, أمس = -1."""

    kind: Literal["relative_day"] = "relative_day"
    offset: int


class RelativeWeekday(_Intent):
    """الخميس الجاي = next, الخميس اللي بعده = after_next."""

    kind: Literal["relative_weekday"] = "relative_weekday"
    weekday: Weekday
    which: Literal["next", "after_next"]


class AbsoluteDate(_Intent):
    """١٧ نوفمبر = gregorian 11/17, ١ جمادى الآخرة = hijri 6/1."""

    kind: Literal["absolute"] = "absolute"
    calendar: Literal["gregorian", "hijri"]
    month: int = Field(ge=1, le=12)
    day: int = Field(ge=1, le=31)
    # None: the resolver picks the next future occurrence and says so in
    # assumptions. The year is in whatever calendar `calendar` names.
    year: int | None = None


class DayOnly(_Intent):
    """يوم ١٧ — no month."""

    kind: Literal["day_only"] = "day_only"
    day: int = Field(ge=1, le=31)


class EventAnchored(_Intent):
    """ثالث يوم العيد = eid_fitr, offset 2. بعد العيد = eid_fitr, no offset."""

    kind: Literal["event_anchored"] = "event_anchored"
    anchor: Literal["eid_fitr", "eid_adha", "national_day", "founding_day"]
    offset: int | None = None


class Unclear(_Intent):
    kind: Literal["unclear"] = "unclear"
    raw: str


DateIntent = Annotated[
    Union[RelativeDay, RelativeWeekday, AbsoluteDate, DayOnly, EventAnchored, Unclear],
    Field(discriminator="kind"),
]


# --- Time ---


class ClockTime(_Intent):
    """٨ الليل = hour 8, pm. ٨ = hour 8, unspecified."""

    kind: Literal["clock"] = "clock"
    hour: int = Field(ge=0, le=23)
    minute: int = Field(default=0, ge=0, le=59)
    period: Literal["am", "pm", "unspecified"]


class PrayerTime(_Intent):
    """بعد المغرب بنص ساعة = maghrib, +30."""

    kind: Literal["prayer"] = "prayer"
    prayer: Literal["fajr", "dhuhr", "asr", "maghrib", "isha"]
    offset_minutes: int = 0


class PartOfDay(_Intent):
    kind: Literal["part_of_day"] = "part_of_day"
    part: Literal["morning", "afternoon", "evening", "late_night"]


TimeIntent = Annotated[
    Union[ClockTime, PrayerTime, PartOfDay],
    Field(discriminator="kind"),
]


# --- Output ---


class ResolvedWhen(BaseModel):
    model_config = ConfigDict(frozen=True)

    start: AwareDatetime  # Asia/Riyadh
    end: AwareDatetime
    gregorian_text: str  # "الخميس ١٧ سبتمبر ٢٠٢٦"
    hijri_text: str  # "٦ ربيع الثاني ١٤٤٨"
    assumptions: tuple[str, ...] = ()


class Ambiguous(BaseModel):
    model_config = ConfigDict(frozen=True)

    candidates: tuple[date, ...]
    question_ar: str
