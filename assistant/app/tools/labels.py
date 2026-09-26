"""Arabic names for the English keys the booking tools use internally.

Two directions, one table:
  - in:  a customer says "الأساسية", the model passes that back, and it is
         accepted as `starter` (taxonomy 3);
  - out: summary_ar says "الأساسية", never `starter` (taxonomy 5).

The Arabic names are the ones the KB uses (kb/laqta-kb.md "الباقات",
"الإضافات", "طرق التعرّف على الضيوف"), because that is what the model reads
and what the customer is told. Keys must match policy.yaml exactly;
tests/test_labels.py enforces both.
"""

from __future__ import annotations

import re

PACKAGE_AR: dict[str, str] = {
    "starter": "الأساسية",
    "standard": "القياسية",
    "premium": "المميزة",
}

MATCH_MODE_AR: dict[str, str] = {
    "face": "مطابقة الوجه",
    "code": "مطابقة الرمز",
    "sequential": "الترقيم التسلسلي",
    "both": "الوجه والرمز معاً",
}

# Without the KB's "30 يوم": that number belongs to policy, not to a label.
ADDON_AR: dict[str, str] = {
    "extra_photographer_seat": "مقعد مصور إضافي",
    "sponsor_overlay": "شعار الراعي على كل صورة",
    "extended_retention": "تمديد مدة الحفظ",
    "same_day_highlight_video": "فيديو ملخص في نفس اليوم",
}

CITY_AR: dict[str, str] = {
    "jeddah": "جدة",
    "riyadh": "الرياض",
    "dammam": "الدمام",
}

# Out only: a status is never model input.
STATUS_AR: dict[str, str] = {
    "tentative": "مبدئي",
    "confirmed": "مؤكد",
    "live": "شغالة الآن",
    "ended": "انتهت",
    "cancelled": "ملغي",
}

# Out only, like STATUS_AR. The KB's own team names ("الفرق والمسؤوليات").
TEAM_AR: dict[str, str] = {
    "sales": "المبيعات",
    "ops": "العمليات",
    "support": "الدعم الفني",
    "privacy": "البيانات والخصوصية",
}

# The KB's name for privacy_mode = strict ("الفعاليات النسائية والوضع المشدد").
STRICT_MODE_AR = "الوضع المشدد"

# Other ways a customer (and so the model) names the same thing. Explicit
# lists rather than fuzzy matching: a near-miss must stay an error the model
# can see, not silently become a different package.
PACKAGE_ALIASES: dict[str, tuple[str, ...]] = {
    "starter": ("الباقة الأساسية", "أساسية"),
    "standard": ("الباقة القياسية", "قياسية"),
    "premium": ("الباقة المميزة", "مميزة"),
}
MATCH_MODE_ALIASES: dict[str, tuple[str, ...]] = {
    "face": ("الوجه", "وجه", "مطابقة الوجه (سيلفي)", "سيلفي", "السيلفي"),
    "code": ("الرمز", "رمز", "الكود"),
    "sequential": ("تسلسلي", "الترقيم التسلسلي (بوث التصوير)", "بوث التصوير"),
    "both": ("الوجه والرمز", "وجه ورمز"),
}
ADDON_ALIASES: dict[str, tuple[str, ...]] = {
    "extra_photographer_seat": ("مقعد إضافي",),
    "sponsor_overlay": ("شعار الراعي",),
    "extended_retention": ("تمديد الحفظ", "تمديد مدة الحفظ 30 يوم"),
    "same_day_highlight_video": ("فيديو ملخص",),
}
# Spelling variants of the same city only — never a neighbouring one. الخبر is
# not الدمام: a booking whose city quietly became a different city would still
# pass the customer's summary check, because the summary shows the substitute.
# No article variant for جدة: "الجدة" is a different word, not a spelling.
CITY_ALIASES: dict[str, tuple[str, ...]] = {
    "jeddah": ("جده", "مدينة جدة", "jedda", "jiddah"),
    "riyadh": ("رياض", "مدينة الرياض", "riyad"),
    "dammam": ("دمام", "مدينة الدمام", "damam"),
}

_DIACRITICS = re.compile(r"[ً-ْٰـ]")  # harakat, dagger alef, tatweel


def _normalize(text: str) -> str:
    text = _DIACRITICS.sub("", text)
    text = re.sub(r"[أإآ]", "ا", text)
    return " ".join(text.split()).lower()


def _index(labels: dict[str, str], aliases: dict[str, tuple[str, ...]]) -> dict[str, str]:
    index: dict[str, str] = {}
    for key, label in labels.items():
        for name in (key, label, *aliases.get(key, ())):
            index[_normalize(name)] = key
    return index


_PACKAGE_INDEX = _index(PACKAGE_AR, PACKAGE_ALIASES)
_MATCH_MODE_INDEX = _index(MATCH_MODE_AR, MATCH_MODE_ALIASES)
_ADDON_INDEX = _index(ADDON_AR, ADDON_ALIASES)
_CITY_INDEX = _index(CITY_AR, CITY_ALIASES)


def _canonical(value: object, index: dict[str, str]) -> object:
    """The English key for a known name; anything else unchanged, so the
    caller's own validation reports it."""
    if not isinstance(value, str):
        return value
    return index.get(_normalize(value), value)


def ar_labels(keys: object, table: dict[str, str]) -> list[str]:
    """Arabic names for a list of keys, for a tool result the model reads.
    A key with no label (a remote booking's free-text city) is already the
    customer's own wording and comes back unchanged."""
    return [table.get(key, key) for key in keys]


def canonical_package(value: object) -> object:
    return _canonical(value, _PACKAGE_INDEX)


def canonical_match_mode(value: object) -> object:
    return _canonical(value, _MATCH_MODE_INDEX)


def canonical_addon(value: object) -> object:
    return _canonical(value, _ADDON_INDEX)


def canonical_city(value: object) -> object:
    """A known city's slug. Any other city comes back exactly as given: a
    remote booking may be anywhere in the Kingdom, and an onsite one outside
    the onsite list must be refused, not moved."""
    if isinstance(value, str):
        return _CITY_INDEX.get(_normalize(value), value.strip())
    return value


def days_ar(n: int) -> str:
    """"7 أيام", "14 يوم" — the counting the KB itself uses."""
    if n == 1:
        return "يوم واحد"
    if n == 2:
        return "يومين"
    if 3 <= n <= 10:
        return f"{n} أيام"
    return f"{n} يوم"


def duration_ar(hours: int) -> str:
    """How the KB states a cutoff: whole weeks and days in days ("7 أيام"),
    shorter spans in hours ("48 ساعة")."""
    if hours % 24 == 0 and hours >= 72:
        return days_ar(hours // 24)
    return f"{hours} ساعة"
