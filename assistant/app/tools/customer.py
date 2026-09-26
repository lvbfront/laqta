"""Customer tools: their own bookings, the prepare_* family, and the single
tool that actually changes anything — confirm_action (spec §8, §10).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, Field, WithJsonSchema, field_validator
from sqlalchemy import select

from app.assistant_domain import confirmation as confirmations
from app.config import Policy, RefundTier
from app.domain.availability import AvailabilityRequest
from app.domain.booking_state import (
    CREATION_TRIGGER,
    GuardFailed,
    InvalidTransition,
    Trigger,
    apply,
    can_apply,
    record_creation,
)
from app.domain.capacity import check_under_lock, check_without_lock
from app.domain.payment import payment_deadline, refund_applies, refund_percent, refund_tier
from app.models import Booking, BookingEvent
from app.models.enums import BookingStatus, ConfirmationAction, MatchMode, TicketReason
from app.tools.common import availability_failure, unknown_when_id, when_or_none
from app.tools.labels import (
    ADDON_AR,
    CITY_AR,
    MATCH_MODE_AR,
    PACKAGE_AR,
    STATUS_AR,
    STRICT_MODE_AR,
    TEAM_AR,
    ar_labels,
    canonical_addon,
    canonical_city,
    canonical_match_mode,
    canonical_package,
    days_ar,
    duration_ar,
)
from app.tools.registry import ToolContext, fail, ok, registry

STRICT_PRIVACY_MODE = "strict"
STANDARD_PRIVACY_MODE = "standard"


def _load_own_booking(ctx: ToolContext, booking_id: uuid.UUID) -> Booking | None:
    """Scoped by contact. A booking that belongs to someone else comes back
    as None and is reported as not_found, never forbidden — the same
    anti-enumeration pattern Laqta uses for resources that are not yours
    (spec §4)."""
    return ctx.db.scalar(
        select(Booking).where(
            Booking.id == booking_id,
            Booking.contact_id == ctx.identity.contact_id,
        )
    )


def _not_found() -> dict:
    return fail("not_found", "ما لقيت حجز بهذا الرقم.")


def _tentative_at(ctx: ToolContext, booking: Booking) -> datetime:
    """When the booking became tentative — the anchor for its payment
    deadline. Taken from the creating transition, which carries the domain
    clock, not the database's."""
    created = ctx.db.scalar(
        select(BookingEvent.at)
        .where(
            BookingEvent.booking_id == booking.id,
            BookingEvent.trigger == CREATION_TRIGGER,
        )
        .order_by(BookingEvent.id)
        .limit(1)
    )
    return created or booking.created_at


def _handoff(reason_code: TicketReason, detail: str, ctx: ToolContext, error: str) -> dict:
    """A refusal a human has to resolve. No ticket is opened here — only
    handoff_to_staff may do that — so this tells the model which reason code
    to hand it."""
    team = ctx.policy.handoff.team_for(reason_code.value)
    return fail(
        error,
        detail,
        handoff={"reason_code": reason_code.value, "team": team, "team_ar": TEAM_AR[team]},
    )


def _local(moment: datetime, ctx: ToolContext) -> str:
    return moment.astimezone(ctx.policy.tz).strftime("%H:%M")


# --- get_my_bookings


class NoInput(BaseModel):
    pass


@registry.tool(
    name="get_my_bookings",
    roles={"customer"},
    description="""
    This customer's own bookings, newest event first. Use it when they refer
    to "my booking" without saying which, or ask about a payment deadline or
    status. There is no way to list anyone else's bookings.
    """,
)
def get_my_bookings(ctx: ToolContext, inp: NoInput) -> dict:
    bookings = ctx.db.scalars(
        select(Booking)
        .where(Booking.contact_id == ctx.identity.contact_id)
        .order_by(Booking.starts_at.desc())
    ).all()

    return ok(
        bookings=[
            {
                "booking_id": str(booking.id),
                "event_name": booking.event_name,
                "status": booking.status.value,
                "status_ar": STATUS_AR[booking.status.value],
                "city": booking.city,
                "city_ar": CITY_AR.get(booking.city, booking.city),
                "venue": booking.venue,
                "starts_at": booking.starts_at.astimezone(ctx.policy.tz).isoformat(),
                "ends_at": booking.ends_at.astimezone(ctx.policy.tz).isoformat(),
                "package": booking.package,
                "package_ar": PACKAGE_AR[booking.package],
                "onsite_support": booking.onsite_support,
                "strict_mode": booking.strict_mode,
                "payment_due_at": booking.payment_due_at.astimezone(ctx.policy.tz).isoformat(),
            }
            for booking in bookings
        ]
    )


# --- prepare_booking


class BookingDetails(BaseModel):
    # The schema is written for the model, and the model repeats what it reads
    # there to the customer (taxonomy 13). So it names every choice the way
    # the KB does. The validators below still accept the English keys, and
    # rows, params and Laqta calls still carry only the keys.
    event_name: str = Field(min_length=2, max_length=255)
    city: str = Field(
        description=f"{' أو '.join(CITY_AR.values())}; any other city exactly as the customer said it."
    )
    venue: str = Field(min_length=2, max_length=255)
    expected_guests: int = Field(gt=0)
    photographers: int = Field(gt=0)
    match_mode: Annotated[
        MatchMode,
        WithJsonSchema({"type": "string", "enum": list(MATCH_MODE_AR.values())}),
    ]
    strict_mode: bool = Field(
        title=STRICT_MODE_AR,
        description=f"True for a women's event or any event that needs {STRICT_MODE_AR}.",
    )
    package: Annotated[
        str, WithJsonSchema({"type": "string", "enum": list(PACKAGE_AR.values())})
    ]
    addons: list[str] = Field(default_factory=list)
    onsite_support: bool = False

    # The KB names packages, match modes and add-ons in Arabic, so that is
    # what the model reads and passes back. Accept it rather than spend a
    # round trip on unknown_package every booking (taxonomy 3). Stored and
    # confirmed as the English key either way.
    @field_validator("city", mode="before")
    @classmethod
    def _city_alias(cls, value: object) -> object:
        return canonical_city(value)

    @field_validator("package", mode="before")
    @classmethod
    def _package_alias(cls, value: object) -> object:
        return canonical_package(value)

    @field_validator("match_mode", mode="before")
    @classmethod
    def _match_mode_alias(cls, value: object) -> object:
        return canonical_match_mode(value)

    @field_validator("addons", mode="before")
    @classmethod
    def _addon_aliases(cls, value: object) -> object:
        return [canonical_addon(item) for item in value] if isinstance(value, list) else value


class PrepareBookingInput(BaseModel):
    when_id: str = Field(description="From resolve_when.")
    details: BookingDetails


@registry.tool(
    name="prepare_booking",
    roles={"customer"},
    description="""
    Check a complete booking and produce a summary to read back to the
    customer. It changes nothing and books nothing.

    Do not call this until you have every required field: event name, the
    when_id from resolve_when, city, venue, expected guests, number of
    photographers, match mode, whether it is a women's event / الوضع المشدد,
    and the package plus any add-ons. If something is missing, ask for it
    first.

    On success you get a confirmation_id and summary_ar. Read the summary out
    in full, then wait. Only after the customer clearly agrees in a NEW
    message may you call confirm_action.
    """,
)
def prepare_booking(ctx: ToolContext, inp: PrepareBookingInput) -> dict:
    when = when_or_none(ctx, inp.when_id)
    if when is None:
        return unknown_when_id()

    details = inp.details
    policy = ctx.policy

    if details.package not in policy.packages:
        return fail(
            "unknown_package",
            "هذي الباقة غير موجودة.",
            packages=sorted(policy.packages),
            packages_ar=ar_labels(sorted(policy.packages), PACKAGE_AR),
        )

    unknown_addons = sorted(set(details.addons) - set(policy.addons))
    if unknown_addons:
        return fail(
            "unknown_addon",
            "فيه إضافة غير موجودة في قائمة الإضافات.",
            addons=unknown_addons,
            available=list(policy.addons),
            available_ar=ar_labels(policy.addons, ADDON_AR),
        )

    forbidden = set(details.addons) & set(policy.strict_mode.forbidden_addons)
    if details.strict_mode and forbidden:
        return fail(
            "addon_not_allowed_in_strict_mode",
            "هذي الإضافة ما تتوافق مع الوضع المشدد.",
            addons=sorted(forbidden),
            addons_ar=ar_labels(sorted(forbidden), ADDON_AR),
        )

    if details.onsite_support:
        allowed = set(policy.onsite.included_in) | set(policy.onsite.addon_for)
        if details.package not in allowed:
            return fail(
                "onsite_not_available_for_package",
                "الدعم الميداني غير متاح مع هذي الباقة.",
                packages=sorted(allowed),
                packages_ar=ar_labels(sorted(allowed), PACKAGE_AR),
            )

    req = AvailabilityRequest(
        starts_at=when.start,
        ends_at=when.end,
        city=details.city,
        onsite_support=details.onsite_support,
        expected_guests=details.expected_guests,
        package=details.package,
    )
    result = check_without_lock(ctx.db, req, now=ctx.now, policy=policy)
    if not result.ok:
        return availability_failure(result, req, policy)

    params = {
        "when": {
            "starts_at": when.start.isoformat(),
            "ends_at": when.end.isoformat(),
            "gregorian_text": when.gregorian_text,
            "hijri_text": when.hijri_text,
        },
        "details": details.model_dump(mode="json"),
    }
    confirmation = confirmations.prepare(
        ctx.db,
        interaction_id=ctx.interaction_id,
        action=ConfirmationAction.booking,
        params=params,
        user_turn=ctx.user_turn,
        now=ctx.now,
        policy=policy,
    )

    deadline = payment_deadline(tentative_at=ctx.now, starts_at=when.start, policy=policy)
    # Every key goes through its Arabic label: this text is read to the
    # customer verbatim, and `both` or `starter` in it is a leak (taxonomy 5).
    summary = (
        f"حجز مبدئي لـ«{details.event_name}» يوم {when.gregorian_text} "
        f"({when.hijri_text}) من {_local(when.start, ctx)} إلى {_local(when.end, ctx)}، "
        f"في {details.venue} بـ{CITY_AR.get(details.city, details.city)}، "
        f"{details.expected_guests} ضيف و{details.photographers} مصور، "
        f"طريقة التعرّف: {MATCH_MODE_AR[details.match_mode.value]}، "
        f"الباقة: {PACKAGE_AR[details.package]}"
        + (
            f"، إضافات: {'، '.join(ADDON_AR[addon] for addon in details.addons)}"
            if details.addons
            else ""
        )
        + ("، بدعم ميداني" if details.onsite_support else "")
        + ("، بالوضع المشدد" if details.strict_mode else "")
        + "."
        + (_strict_retention_note(details.package, policy) if details.strict_mode else "")
        + f" مهلة الدفع إلى {deadline.astimezone(policy.tz):%Y-%m-%d %H:%M}."
    )
    return ok(
        confirmation_id=str(confirmation.id),
        summary_ar=summary,
        expires_in_minutes=policy.confirmation_ttl_minutes,
    )


def _strict_retention_note(package: str, policy: Policy) -> str:
    """Strict mode's retention replaces the package's, and a customer who
    read the package table expects the package's (taxonomy 6). Said in the
    summary so it is on record before they agree."""
    strict_days = policy.strict_mode.retention_days
    package_days = policy.packages[package].retention_days
    note = f" مدة حفظ الصور {days_ar(strict_days)} بسبب الوضع المشدد"
    if package_days != strict_days:
        note += f"، وتلغي مدة الباقة {PACKAGE_AR[package]} ({days_ar(package_days)})"
    return note + "."


# --- prepare_reschedule


# The context block names bookings but carries no id (taxonomy 2), so this
# is where the model is told where one comes from.
BOOKING_ID_DESCRIPTION = "The full booking_id exactly as get_my_bookings returned it."


class PrepareRescheduleInput(BaseModel):
    booking_id: uuid.UUID = Field(description=BOOKING_ID_DESCRIPTION)
    when_id: str = Field(description="The new window, from resolve_when.")


@registry.tool(
    name="prepare_reschedule",
    roles={"customer"},
    description="""
    Check moving one of this customer's bookings to a new window, and produce
    a summary to read back. It changes nothing.

    Needs the booking_id from get_my_bookings and a when_id for the new
    window. If the change falls inside the free-reschedule window, or
    the event is already running, this comes back asking for a handoff —
    call handoff_to_staff with the reason code it gives you.

    On success, read summary_ar out in full and wait for the customer to
    agree in a NEW message before calling confirm_action.
    """,
)
def prepare_reschedule(ctx: ToolContext, inp: PrepareRescheduleInput) -> dict:
    booking = _load_own_booking(ctx, inp.booking_id)
    if booking is None:
        return _not_found()

    when = when_or_none(ctx, inp.when_id)
    if when is None:
        return unknown_when_id()

    policy = ctx.policy
    try:
        can_apply(booking, Trigger.reschedule, now=ctx.now, policy=policy)
    except GuardFailed:
        # Inside the free window. The KB says the team has to approve it.
        return _handoff(
            TicketReason.late_change,
            f"التعديل خلال آخر {policy.free_reschedule_before_hours} ساعة يحتاج موافقة الفريق.",
            ctx,
            "needs_staff_approval",
        )
    except InvalidTransition:
        return _handoff(
            TicketReason.late_change,
            "ما نقدر نعدّل موعد هذا الحجز بحالته الحالية.",
            ctx,
            "not_reschedulable",
        )

    req = AvailabilityRequest(
        starts_at=when.start,
        ends_at=when.end,
        city=booking.city,
        onsite_support=booking.onsite_support,
        expected_guests=booking.expected_guests,
        package=booking.package,
    )
    result = check_without_lock(
        ctx.db, req, now=ctx.now, policy=policy, exclude_booking_id=booking.id
    )
    if not result.ok:
        return availability_failure(result, req, policy)

    params = {
        "booking_id": str(booking.id),
        "when": {
            "starts_at": when.start.isoformat(),
            "ends_at": when.end.isoformat(),
            "gregorian_text": when.gregorian_text,
            "hijri_text": when.hijri_text,
        },
    }
    confirmation = confirmations.prepare(
        ctx.db,
        interaction_id=ctx.interaction_id,
        action=ConfirmationAction.reschedule,
        params=params,
        user_turn=ctx.user_turn,
        now=ctx.now,
        policy=policy,
    )

    summary = (
        f"تعديل موعد «{booking.event_name}» إلى {when.gregorian_text} "
        f"({when.hijri_text}) من {_local(when.start, ctx)} إلى {_local(when.end, ctx)}"
    )
    if booking.status is BookingStatus.tentative:
        # The deadline follows the new date; keeping the old one could put it
        # after the event itself.
        deadline = payment_deadline(
            tentative_at=_tentative_at(ctx, booking), starts_at=when.start, policy=policy
        )
        summary += f". مهلة الدفع تصير إلى {deadline.astimezone(policy.tz):%Y-%m-%d %H:%M}"
    summary += "."

    return ok(
        confirmation_id=str(confirmation.id),
        summary_ar=summary,
        expires_in_minutes=policy.confirmation_ttl_minutes,
    )


# --- prepare_cancel


class PrepareCancelInput(BaseModel):
    booking_id: uuid.UUID = Field(description=BOOKING_ID_DESCRIPTION)


@registry.tool(
    name="prepare_cancel",
    roles={"customer"},
    description="""
    Check cancelling one of this customer's bookings and produce a summary to
    read back. It cancels nothing. Needs the booking_id from get_my_bookings.

    For a paid booking the summary and refund_percent give the refund and why
    that tier applies. An unpaid booking (مبدئي) cancels without fees: its
    summary says so and there is no refund_percent — do not state one.

    Read the summary out in full, then wait for the customer to agree in a
    NEW message before calling confirm_action.
    """,
)
def prepare_cancel(ctx: ToolContext, inp: PrepareCancelInput) -> dict:
    booking = _load_own_booking(ctx, inp.booking_id)
    if booking is None:
        return _not_found()

    try:
        can_apply(booking, Trigger.cancel, now=ctx.now, policy=ctx.policy)
    except InvalidTransition:
        return _handoff(
            TicketReason.late_change,
            "ما نقدر نلغي هذا الحجز بحالته الحالية.",
            ctx,
            "not_cancellable",
        )

    cancelling = (
        f"إلغاء «{booking.event_name}» بتاريخ "
        f"{booking.starts_at.astimezone(ctx.policy.tz):%Y-%m-%d}"
    )
    params: dict = {"booking_id": str(booking.id)}
    refund: dict = {}
    if refund_applies(booking.status.value, ctx.policy):
        tier = refund_tier(starts_at=booking.starts_at, now=ctx.now, policy=ctx.policy)
        params["refund_percent"] = refund["refund_percent"] = tier.percent
        summary = f"{cancelling}، ونسبة الاسترداد {tier.percent}% {_refund_reason(tier, ctx.policy)}."
    else:
        # Unpaid: no percentage anywhere, not even 0% (taxonomy 11). The
        # data matters as much as the text — staff read params and results,
        # not the chat.
        summary = f"{cancelling}. الحجز مبدئي وما انْدفع، فيتلغى بدون رسوم."

    confirmation = confirmations.prepare(
        ctx.db,
        interaction_id=ctx.interaction_id,
        action=ConfirmationAction.cancel,
        params=params,
        user_turn=ctx.user_turn,
        now=ctx.now,
        policy=ctx.policy,
    )

    return ok(
        confirmation_id=str(confirmation.id),
        summary_ar=summary,
        **refund,
        expires_in_minutes=ctx.policy.confirmation_ttl_minutes,
    )


def _refund_reason(tier: RefundTier, policy: Policy) -> str:
    """Which cutoff the cancellation falls on, in the KB's own terms, so a
    figure that changes from one day to the next comes with its reason
    (taxonomy 9). Built from policy.refunds, so a new tier needs no edit."""
    tiers = policy.refunds
    index = tiers.index(tier)
    lower = tier.min_hours_before
    if index == 0:
        return f"لأن الإلغاء قبل الفعالية بـ{duration_ar(lower)} أو أكثر"
    upper = tiers[index - 1].min_hours_before
    if lower == 0:
        return f"لأن الإلغاء خلال آخر {duration_ar(upper)} قبل الفعالية"
    return (
        f"لأن الإلغاء قبل الفعالية بأقل من {duration_ar(upper)} "
        f"وبـ{duration_ar(lower)} أو أكثر"
    )


# --- confirm_action


class ConfirmActionInput(BaseModel):
    confirmation_id: uuid.UUID


@registry.tool(
    name="confirm_action",
    roles={"customer"},
    description="""
    Execute a prepared booking, reschedule or cancellation. This is the only
    tool that changes anything.

    Call it only after you read the prepared summary back to the customer and
    they clearly agreed in a NEW message. If they changed any detail, call the
    matching prepare_* again instead — a confirmation is valid for one action
    only, and its parameters are the ones that were prepared, not anything
    you pass now.

    Availability is rechecked at this moment, so this can still come back
    ok: false if the date filled up while you were talking.
    """,
    side_effects=True,
)
def confirm_action(ctx: ToolContext, inp: ConfirmActionInput) -> dict:
    try:
        confirmation = confirmations.redeem(
            ctx.db,
            inp.confirmation_id,
            interaction_id=ctx.interaction_id,
            user_turn=ctx.user_turn,
            now=ctx.now,
        )
    except confirmations.ConfirmationError as exc:
        return fail(exc.code, exc.detail_ar)

    if confirmation.action is ConfirmationAction.booking:
        return _create_booking(ctx, confirmation.params)
    if confirmation.action is ConfirmationAction.reschedule:
        return _reschedule(ctx, confirmation.params)
    return _cancel(ctx, confirmation.params)


def _window(params: dict) -> tuple[datetime, datetime]:
    return (
        datetime.fromisoformat(params["when"]["starts_at"]),
        datetime.fromisoformat(params["when"]["ends_at"]),
    )


def _create_booking(ctx: ToolContext, params: dict) -> dict:
    details = params["details"]
    starts_at, ends_at = _window(params)
    policy = ctx.policy

    req = AvailabilityRequest(
        starts_at=starts_at,
        ends_at=ends_at,
        city=details["city"],
        onsite_support=details["onsite_support"],
        expected_guests=details["expected_guests"],
        package=details["package"],
    )
    # Under the lock this time: the world may have moved since the prepare.
    result = check_under_lock(ctx.db, req, now=ctx.now, policy=policy)
    if not result.ok:
        return availability_failure(result, req, policy)

    booking = Booking(
        contact_id=ctx.identity.contact_id,
        laqta_org_id=ctx.identity.laqta_org_id,
        event_name=details["event_name"],
        city=details["city"],
        venue=details["venue"],
        starts_at=starts_at,
        ends_at=ends_at,
        expected_guests=details["expected_guests"],
        photographers=details["photographers"],
        match_mode=MatchMode(details["match_mode"]),
        strict_mode=details["strict_mode"],
        package=details["package"],
        addons=details["addons"],
        onsite_support=details["onsite_support"],
        payment_due_at=payment_deadline(
            tentative_at=ctx.now, starts_at=starts_at, policy=policy
        ),
    )
    record_creation(booking, now=ctx.now, actor=f"customer:{ctx.identity.contact_id}")
    ctx.db.add(booking)
    ctx.db.flush()

    event = ctx.laqta.create_event(
        idempotency_key=str(booking.id),
        org_id=booking.laqta_org_id,
        name_ar=booking.event_name,
        starts_at=booking.starts_at,
        ends_at=booking.ends_at,
        match_mode=booking.match_mode.value,
        privacy_mode=STRICT_PRIVACY_MODE if booking.strict_mode else STANDARD_PRIVACY_MODE,
    )
    booking.laqta_event_id = event.id
    ctx.db.flush()

    return ok(
        booking_id=str(booking.id),
        status=booking.status.value,
        status_ar=STATUS_AR[booking.status.value],
        payment_due_at=booking.payment_due_at.astimezone(policy.tz).isoformat(),
        starts_at=booking.starts_at.astimezone(policy.tz).isoformat(),
        ends_at=booking.ends_at.astimezone(policy.tz).isoformat(),
    )


def _reschedule(ctx: ToolContext, params: dict) -> dict:
    booking = _load_own_booking(ctx, uuid.UUID(params["booking_id"]))
    if booking is None:
        return _not_found()

    starts_at, ends_at = _window(params)
    policy = ctx.policy
    req = AvailabilityRequest(
        starts_at=starts_at,
        ends_at=ends_at,
        city=booking.city,
        onsite_support=booking.onsite_support,
        expected_guests=booking.expected_guests,
        package=booking.package,
    )
    result = check_under_lock(
        ctx.db, req, now=ctx.now, policy=policy, exclude_booking_id=booking.id
    )
    if not result.ok:
        return availability_failure(result, req, policy)

    was_tentative = booking.status is BookingStatus.tentative
    tentative_at = _tentative_at(ctx, booking) if was_tentative else None

    try:
        apply(
            booking,
            Trigger.reschedule,
            now=ctx.now,
            policy=policy,
            actor=f"customer:{ctx.identity.contact_id}",
            new_window=(starts_at, ends_at),
        )
    except (GuardFailed, InvalidTransition):
        return _handoff(
            TicketReason.late_change,
            "الحجز ما صار يقبل التعديل. خلني أحوّلك للفريق.",
            ctx,
            "needs_staff_approval",
        )

    if was_tentative:
        booking.payment_due_at = payment_deadline(
            tentative_at=tentative_at, starts_at=starts_at, policy=policy
        )
    ctx.db.flush()

    if booking.laqta_event_id is not None:
        ctx.laqta.update_event_window(booking.laqta_event_id, starts_at, ends_at)

    return ok(
        booking_id=str(booking.id),
        status=booking.status.value,
        status_ar=STATUS_AR[booking.status.value],
        starts_at=booking.starts_at.astimezone(policy.tz).isoformat(),
        ends_at=booking.ends_at.astimezone(policy.tz).isoformat(),
        payment_due_at=booking.payment_due_at.astimezone(policy.tz).isoformat(),
    )


def _cancel(ctx: ToolContext, params: dict) -> dict:
    booking = _load_own_booking(ctx, uuid.UUID(params["booking_id"]))
    if booking is None:
        return _not_found()

    # Decided on the status before the transition, which makes it cancelled.
    paid = refund_applies(booking.status.value, ctx.policy)
    if paid != ("refund_percent" in params):
        # Paid since the summary was read: the customer agreed to "without
        # fees", and a refund tier now applies. Nothing is cancelled on terms
        # they were not read.
        return fail(
            "booking_changed",
            "حالة الدفع تغيّرت بعد ما جهّزنا الإلغاء. لازم نجهّزه من جديد ونقرأ الملخص.",
        )
    refund = (
        {"refund_percent": refund_percent(starts_at=booking.starts_at, now=ctx.now, policy=ctx.policy)}
        if paid
        else {}
    )
    try:
        apply(
            booking,
            Trigger.cancel,
            now=ctx.now,
            policy=ctx.policy,
            actor=f"customer:{ctx.identity.contact_id}",
        )
    except InvalidTransition:
        return _handoff(
            TicketReason.late_change,
            "ما نقدر نلغي هذا الحجز بحالته الحالية.",
            ctx,
            "not_cancellable",
        )
    ctx.db.flush()

    if booking.laqta_event_id is not None:
        ctx.laqta.cancel_event(booking.laqta_event_id)

    return ok(
        booking_id=str(booking.id),
        status=booking.status.value,
        status_ar=STATUS_AR[booking.status.value],
        **refund,
    )
