"""The "what we know about this customer" block (spec §12).

Built once at the start of a session and sent as the *second* system block,
after the cached instructions — it differs per customer, so it has to sit
after the cache breakpoint or it would invalidate the prefix every time.

Deliberately small (a few hundred tokens at most): today's date in both
calendars, who is speaking, their live bookings, their open tickets, and
what happened last time. The date line matters most — the model has no way
to know what day it is except from here, and every date it reads back to a
customer depends on it.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.assistant_domain.dates.resolver import GREGORIAN_MONTHS_AR, WEEKDAYS_AR
from app.config import Policy
from app.identity.identity import Identity
from app.models.booking import Booking
from app.models.contact import Contact
from app.models.enums import BookingStatus, Gender, TicketReason, TicketStatus
from app.models.interaction import Interaction
from app.models.staff import Staff
from app.models.ticket import Ticket
from app.tools.labels import CITY_AR, STATUS_AR, TEAM_AR

# Keeps the block small when a customer has a long history. The most recent
# and the soonest are what a conversation actually refers to.
MAX_BOOKINGS = 5
MAX_TICKETS = 3

# A booking in one of these states is still live business worth mentioning.
ACTIVE_BOOKING_STATUSES = (
    BookingStatus.tentative,
    BookingStatus.confirmed,
    BookingStatus.live,
)
OPEN_TICKET_STATUSES = (TicketStatus.open, TicketStatus.acknowledged)

# Said explicitly either way, so the model never has to decide from a name
# (taxonomy 8). The system prompt turns "not stated" into neutral address.
GENDER_UNSTATED = "الجنس: غير مذكور في السجل."
GENDER_STATED = {
    Gender.male: "الجنس: ذكر (مذكور في السجل).",
    Gender.female: "الجنس: أنثى (مذكور في السجل).",
}

REASON_AR = {
    TicketReason.discount: "طلب خصم",
    TicketReason.premium_quote: "عرض سعر للباقة المميزة",
    TicketReason.long_event: "فعالية أطول من الحد",
    TicketReason.late_change: "تعديل قريب من الموعد",
    TicketReason.complaint: "شكوى",
    TicketReason.live_issue: "مشكلة تقنية في فعالية شغالة",
    TicketReason.legal: "طلب قانوني",
    TicketReason.unknown_question: "سؤال بدون جواب",
    TicketReason.wants_human: "يطلب التحدث مع موظف",
}


def build_context_block(
    db: Session, identity: Identity, *, now: datetime, policy: Policy
) -> str:
    lines = [_today_line(now, policy), _speaker_line(db, identity)]

    if identity.kind == "customer":
        lines.extend(
            line
            for line in (
                _bookings_line(db, identity, policy),
                _tickets_line(db, identity, policy),
                _last_contact_line(db, identity, policy),
            )
            if line is not None
        )

    return "\n".join(lines)


def _today_line(now: datetime, policy: Policy) -> str:
    """Both calendars, because the assistant confirms every date in both."""
    from hijridate import Gregorian  # local: keeps this module import-cheap

    local = now.astimezone(policy.tz)
    hijri = Gregorian.fromdate(local.date()).to_hijri()
    gregorian = (
        f"{WEEKDAYS_AR[local.weekday()]} {local.day} "
        f"{GREGORIAN_MONTHS_AR[local.month]} {local.year}"
    )
    return (
        f"اليوم: {gregorian} = {hijri.day} {hijri.month_name('ar')} {hijri.year}، "
        f"الساعة {local:%H:%M} بتوقيت الرياض"
    )


def _speaker_line(db: Session, identity: Identity) -> str:
    if identity.kind == "anonymous":
        return (
            "المتكلم: زائر غير مسجل — ما يقدر يحجز. "
            "تقدر تجاوب أسئلته، أو تعطيه رابط التسجيل، أو تاخذ اسمه وجواله وتحوّله للفريق. "
            + GENDER_UNSTATED
        )

    if identity.kind == "staff":
        staff = db.get(Staff, identity.staff_id)
        if staff is None:
            return "المتكلم: موظف"
        return f"المتكلم: موظف — {staff.name}، فريق {TEAM_AR[staff.team.value]}"

    contact = db.get(Contact, identity.contact_id)
    if contact is None:
        return f"المتكلم: عميل مسجل. {GENDER_UNSTATED}"
    org = f"، {contact.org_name}" if contact.org_name else ""
    gender = GENDER_STATED[contact.gender] if contact.gender is not None else GENDER_UNSTATED
    return f"المتكلم: عميل مسجل — {contact.name}{org}. {gender}"


def _bookings_line(db: Session, identity: Identity, policy: Policy) -> str | None:
    """Name, date, city and status — no booking id, not even a short one.

    A short id here was completed into a padded UUID when the customer named
    the event (`456276dd-0000-…`, taxonomy 2), and a full one would sooner or
    later be read to the customer, which no voice channel can say. The booking
    tools take their id from get_my_bookings only. A customer quoting a
    dashboard number still works: the full id it returns starts with it."""
    bookings = db.scalars(
        select(Booking)
        .where(
            Booking.contact_id == identity.contact_id,
            Booking.status.in_(ACTIVE_BOOKING_STATUSES),
        )
        .order_by(Booking.starts_at)
        .limit(MAX_BOOKINGS)
    ).all()
    if not bookings:
        return "حجوزاته: ما فيه حجوزات حالية."

    entries = []
    for booking in bookings:
        starts = booking.starts_at.astimezone(policy.tz)
        parts = [
            f"«{booking.event_name}»",
            f"{starts.day} {GREGORIAN_MONTHS_AR[starts.month]}",
            # Arabic, not the slug: the model repeats what it reads here (taxonomy 13).
            CITY_AR.get(booking.city, booking.city),
            STATUS_AR[booking.status.value],
        ]
        if booking.status is BookingStatus.tentative:
            due = booking.payment_due_at.astimezone(policy.tz)
            parts.append(f"الدفع قبل {due.day} {GREGORIAN_MONTHS_AR[due.month]}")
        entries.append("، ".join(parts))

    return "حجوزاته: " + " | ".join(entries)


def _tickets_line(db: Session, identity: Identity, policy: Policy) -> str | None:
    tickets = db.scalars(
        select(Ticket)
        .where(
            Ticket.contact_id == identity.contact_id,
            Ticket.status.in_(OPEN_TICKET_STATUSES),
        )
        .order_by(Ticket.created_at.desc())
        .limit(MAX_TICKETS)
    ).all()
    if not tickets:
        return None

    entries = []
    for ticket in tickets:
        created = ticket.created_at.astimezone(policy.tz)
        entries.append(
            f"#{ticket.id} {REASON_AR.get(ticket.reason_code, ticket.reason_code.value)} "
            f"— مع {TEAM_AR[ticket.team.value]} "
            f"منذ {created.day} {GREGORIAN_MONTHS_AR[created.month]}"
        )
    return "تذاكر مفتوحة: " + " | ".join(entries)


def _last_contact_line(db: Session, identity: Identity, policy: Policy) -> str | None:
    """The summary written when the previous session ended (spec §12)."""
    previous = db.scalars(
        select(Interaction)
        .where(
            Interaction.contact_id == identity.contact_id,
            Interaction.summary.is_not(None),
            Interaction.ended_at.is_not(None),
        )
        .order_by(Interaction.ended_at.desc())
        .limit(1)
    ).first()
    if previous is None:
        return None

    ended = previous.ended_at.astimezone(policy.tz)
    return (
        f"آخر تواصل: {ended.day} {GREGORIAN_MONTHS_AR[ended.month]} — {previous.summary}"
    )
