"""Tools every role can use: resolve_when, check_availability,
handoff_to_staff (spec §10).

search_kb belongs here too and arrives with the retrieval layer (spec §11).
"""

from __future__ import annotations

import uuid
from datetime import timedelta

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select

from app.config import Policy
from app.domain.availability import (
    END_BEFORE_START,
    GUESTS_EXCEED_PACKAGE,
    IN_PAST,
    LEAD_TIME,
    ONSITE_CITY_UNSUPPORTED,
    ONSITE_FULL,
    TOO_LONG,
    AvailabilityRequest,
    AvailabilityResult,
)
from app.assistant_domain.dates.intents import Ambiguous, DateIntent, TimeIntent
from app.assistant_domain.dates.resolver import resolve
from app.domain.capacity import check_without_lock
from app.kb.search import search
from app.models import Contact, Interaction, Staff, Ticket
from app.models.enums import ContactSource, Team, TicketPriority, TicketReason, TicketStatus
from app.tools.labels import CITY_AR, PACKAGE_AR, TEAM_AR, canonical_city
from app.tools.registry import ToolContext, fail, ok, registry

# Business refusals that are really "a human has to decide this", with the
# reason code the model should hand to handoff_to_staff.
HANDOFF_FOR_REASON = {
    TOO_LONG: TicketReason.long_event,
}


def when_or_none(ctx: ToolContext, when_id: str):
    return ctx.resolved.get(when_id)


def unknown_when_id() -> dict:
    return fail(
        "unknown_when_id",
        "لازم تستخدم resolve_when أول عشان تحدد التاريخ.",
    )


def availability_detail(result: AvailabilityResult, req: AvailabilityRequest, policy: Policy) -> str:
    """Arabic text for a rejection.

    onsite_full deliberately carries no numbers — the KB's operating-capacity
    section says capacity figures are never told to a customer, and the model
    cannot leak a number it never saw.
    """
    if result.reason == ONSITE_FULL:
        return "الموعد غير متاح."
    if result.reason == LEAD_TIME:
        if req.onsite_support:
            days = policy.lead_time_hours.onsite // 24
            return f"الحجز بدعم ميداني يحتاج {days} أيام مقدماً."
        return f"الحجز يحتاج {policy.lead_time_hours.remote} ساعة مقدماً."
    if result.reason == TOO_LONG:
        return f"الفعاليات أطول من {policy.max_event_days} أيام تحتاج عرض من فريق المبيعات."
    if result.reason == ONSITE_CITY_UNSUPPORTED:
        return "الدعم الميداني غير متوفر في هذي المدينة."
    if result.reason == GUESTS_EXCEED_PACKAGE:
        return "عدد الضيوف أكثر من حد هذي الباقة."
    if result.reason == IN_PAST:
        return "هذا التاريخ مضى."
    if result.reason == END_BEFORE_START:
        return "وقت النهاية قبل وقت البداية."
    return "الموعد غير متاح."


def availability_failure(
    result: AvailabilityResult, req: AvailabilityRequest, policy: Policy
) -> dict:
    extra: dict = {}
    if result.suggestions:
        extra["suggestions"] = [day.isoformat() for day in result.suggestions]
    if result.suggested_package:
        extra["suggested_package"] = result.suggested_package
        extra["suggested_package_ar"] = PACKAGE_AR[result.suggested_package]
    if result.reason == ONSITE_CITY_UNSUPPORTED:
        # The refusal names the cities that do work, so the model offers
        # those or a remote booking — and never picks the nearest one itself.
        extra["supported_cities"] = list(policy.onsite.cities)
        extra["supported_cities_ar"] = [CITY_AR[city] for city in policy.onsite.cities]
    if result.reason in HANDOFF_FOR_REASON:
        reason_code = HANDOFF_FOR_REASON[result.reason]
        team = policy.handoff.team_for(reason_code.value)
        extra["handoff"] = {"reason_code": reason_code.value, "team": team, "team_ar": TEAM_AR[team]}
    return fail(result.reason, availability_detail(result, req, policy), **extra)


# --- search_kb


class SearchKBInput(BaseModel):
    query: str = Field(
        min_length=2,
        description="The customer's question, in their own words. Arabic is fine.",
    )


@registry.tool(
    name="search_kb",
    roles={"anonymous", "customer", "staff"},
    description="""
    Search Laqta's knowledge base and answer from what it returns.

    Use it for any question about packages, prices, privacy, الوضع المشدد,
    camera setup, payment, rescheduling, cancellation or working hours.
    Never state a price, policy, deadline or limit that did not come from
    this tool in THIS conversation.

    If it returns an empty list with note "no_relevant_section", the answer
    is not in the knowledge base: do not guess and do not reason it out —
    call handoff_to_staff with reason_code unknown_question.

    Results are filtered by who is asking; internal guidance is never
    returned to a customer.
    """,
)
def search_kb(ctx: ToolContext, inp: SearchKBInput) -> dict:
    hits = search(ctx.db, inp.query, identity_kind=ctx.identity.kind)
    if not hits:
        return ok(results=[], note="no_relevant_section")
    return ok(
        results=[
            {
                "section": hit.section_title,
                "content": hit.content,
                "score": round(hit.score, 3),
            }
            for hit in hits
        ]
    )


# --- resolve_when


class ResolveWhenInput(BaseModel):
    date: DateIntent
    start_time: TimeIntent
    end_time: TimeIntent
    days: int = Field(default=1, ge=1, description="How many days the event runs.")
    city: str | None = Field(
        default=None, description="Needed only when a time is given as a prayer time."
    )

    @field_validator("city", mode="before")
    @classmethod
    def _city_alias(cls, value: object) -> object:
        return canonical_city(value)


@registry.tool(
    name="resolve_when",
    roles={"anonymous", "customer"},
    description="""
    Turn what the customer said about a date and time into a concrete event
    window. Never compute a date yourself — always call this, and read back
    both the Gregorian and Hijri dates it returns, plus any assumptions.

    You describe the date and time structurally (relative day, weekday,
    absolute date, prayer time, part of day) and this returns a when_id.
    Every booking tool takes that when_id, not a date.

    If the answer is ambiguous, ask the customer the question it returns.
    Do not pick one of the candidates yourself.
    """,
)
def resolve_when(ctx: ToolContext, inp: ResolveWhenInput) -> dict:
    outcome = resolve(
        inp.date,
        inp.start_time,
        inp.end_time,
        days=inp.days,
        now=ctx.now,
        policy=ctx.policy,
        city=inp.city,
    )
    if isinstance(outcome, Ambiguous):
        return fail(
            "ambiguous",
            outcome.question_ar,
            candidates=[day.isoformat() for day in outcome.candidates],
        )

    when_id = uuid.uuid4().hex[:8]
    ctx.resolved[when_id] = outcome
    return ok(
        when_id=when_id,
        gregorian_text=outcome.gregorian_text,
        hijri_text=outcome.hijri_text,
        starts_at=outcome.start.isoformat(),
        ends_at=outcome.end.isoformat(),
        assumptions=list(outcome.assumptions),
    )


# --- check_availability


class CheckAvailabilityInput(BaseModel):
    when_id: str = Field(description="From resolve_when.")
    city: str
    onsite_support: bool = Field(
        default=False, description="True only if the customer asked for an onsite crew."
    )

    @field_validator("city", mode="before")
    @classmethod
    def _city_alias(cls, value: object) -> object:
        return canonical_city(value)


@registry.tool(
    name="check_availability",
    roles={"anonymous", "customer"},
    description="""
    Check whether an event window can be booked at all: lead time, city,
    event length, and whether onsite support is still available that day.

    Use it as soon as you have a when_id and a city, before collecting the
    rest of the booking details — it is the cheapest way to find out that a
    date will not work. It changes nothing.

    A refusal comes back as ok: false with a reason and, where a different
    date would help, up to three suggested days. Offer those. Never state or
    guess how full a day is.
    """,
)
def check_availability(ctx: ToolContext, inp: CheckAvailabilityInput) -> dict:
    when = when_or_none(ctx, inp.when_id)
    if when is None:
        return unknown_when_id()

    req = AvailabilityRequest(
        starts_at=when.start,
        ends_at=when.end,
        city=inp.city,
        onsite_support=inp.onsite_support,
    )
    result = check_without_lock(ctx.db, req, now=ctx.now, policy=ctx.policy)
    if not result.ok:
        return availability_failure(result, req, ctx.policy)
    return ok(
        available=True,
        gregorian_text=when.gregorian_text,
        hijri_text=when.hijri_text,
    )


# --- handoff_to_staff


class HandoffInput(BaseModel):
    reason_code: TicketReason
    summary: str = Field(min_length=3, description="What the customer needs, in Arabic.")
    urgent: bool = Field(
        default=False, description="True only for a technical problem during a live event."
    )
    contact_name: str | None = Field(
        default=None, description="Required for a visitor who is not signed in."
    )
    contact_phone: str | None = Field(
        default=None, description="Required for a visitor who is not signed in."
    )


@registry.tool(
    name="handoff_to_staff",
    roles={"anonymous", "customer"},
    description="""
    Open a ticket for a human. This is the right answer for: a discount or
    price negotiation, a quote for الباقة المميزة, an event longer than the maximum
    length, a change inside the free-reschedule window, extending a live
    event, any complaint, a technical problem during a live event (urgent),
    a legal or official data request, any question search_kb cannot answer,
    and any customer who asks to speak to a person.

    Never offer, promise or hint at a discount — hand it off instead.

    For a visitor who is not signed in you must pass contact_name and
    contact_phone. Tell the customer the request is recorded and the team
    will get in touch; do not promise a specific time.
    """,
    side_effects=True,
)
def handoff_to_staff(ctx: ToolContext, inp: HandoffInput) -> dict:
    contact_id = ctx.identity.contact_id

    if ctx.identity.kind == "anonymous":
        if not (inp.contact_name and inp.contact_phone):
            return fail(
                "contact_details_required",
                "أحتاج الاسم ورقم الجوال عشان الفريق يتواصل معك.",
            )
        contact = Contact(
            name=inp.contact_name,
            phone=inp.contact_phone,
            source=ContactSource.chat,
        )
        ctx.db.add(contact)
        ctx.db.flush()
        contact_id = contact.id

        interaction = ctx.db.get(Interaction, ctx.interaction_id)
        if interaction is not None and interaction.contact_id is None:
            interaction.contact_id = contact_id

    policy = ctx.policy
    team = Team(policy.handoff.team_for(inp.reason_code.value))
    priority = TicketPriority(
        policy.handoff.priority_by_reason.get(
            inp.reason_code.value, "urgent" if inp.urgent else "normal"
        )
    )
    minutes = policy.handoff.acknowledge_within_minutes.for_priority(priority.value)
    assignee = _assignee(
        ctx,
        team,
        to_manager=inp.reason_code.value in policy.handoff.to_team_manager,
    )

    ticket = Ticket(
        contact_id=contact_id,
        interaction_id=ctx.interaction_id,
        team=team,
        assignee_staff_id=assignee.id if assignee is not None else None,
        priority=priority,
        reason_code=inp.reason_code,
        summary=inp.summary,
        status=TicketStatus.open,
        due_at=ctx.now + timedelta(minutes=minutes),
    )
    ctx.db.add(ticket)
    ctx.db.flush()

    return ok(
        ticket_id=ticket.id,
        team=team.value,
        team_ar=TEAM_AR[team.value],
        priority=priority.value,
        due_at=ticket.due_at.isoformat(),
    )


def _assignee(ctx: ToolContext, team: Team, *, to_manager: bool) -> Staff | None:
    """The team member who should pick this up: the manager for the reasons
    the KB sends straight to them, otherwise whoever has the fewest open
    tickets (ties broken by id, so it is deterministic)."""
    members = ctx.db.scalars(
        select(Staff).where(Staff.team == team, Staff.active.is_(True))
    ).all()
    if not members:
        return None

    if to_manager:
        managers = [member for member in members if member.manager_id is None]
        if managers:
            return min(managers, key=lambda member: member.id)

    open_counts = dict(
        ctx.db.execute(
            select(Ticket.assignee_staff_id, func.count())
            .where(Ticket.status != TicketStatus.resolved)
            .group_by(Ticket.assignee_staff_id)
        ).all()
    )
    return min(members, key=lambda member: (open_counts.get(member.id, 0), member.id))
