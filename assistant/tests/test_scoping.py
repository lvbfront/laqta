"""One customer must not see or touch another's booking (spec §4, §14)."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import select

from app.identity.identity import Identity
from app.models import Booking
from app.models.enums import BookingStatus
from app.tools import registry
from tests.factories import REFERENCE_NOW as NOW
from tests.factories import (
    customer_identity,
    make_contact,
    make_onsite_booking,
    make_tool_context,
    make_when,
    register_when,
)

THEIR_DAY = date(2026, 10, 20)
ANONYMOUS = Identity(kind="anonymous")

CUSTOMER_ONLY_TOOLS = {
    "get_my_bookings": {},
    "prepare_booking": {"when_id": "x", "details": {}},
    "prepare_reschedule": {"booking_id": "00000000-0000-4000-8000-000000000000", "when_id": "x"},
    "prepare_cancel": {"booking_id": "00000000-0000-4000-8000-000000000000"},
    "confirm_action": {"confirmation_id": "00000000-0000-4000-8000-000000000000"},
}


@pytest.fixture()
def other_booking(db_session, policy):
    """A booking owned by somebody else entirely."""
    them = make_contact(db_session, name="عميل ثاني")
    return make_onsite_booking(db_session, policy, THEIR_DAY, contact_id=them.id)


@pytest.fixture()
def ctx(db_session, policy):
    me = make_contact(db_session, name="أنا")
    return make_tool_context(db_session, policy, identity=customer_identity(me))


def test_another_customers_booking_reads_as_not_found(ctx, other_booking):
    """not_found, never forbidden: a booking id must not be probeable."""
    result = registry.execute("prepare_cancel", {"booking_id": str(other_booking.id)}, ctx=ctx)
    assert result["ok"] is False
    assert result["error"] == "not_found"


def test_another_customers_booking_cannot_be_rescheduled(ctx, policy, other_booking):
    when_id = register_when(ctx, make_when(policy, (NOW + timedelta(days=40)).date()))
    result = registry.execute(
        "prepare_reschedule",
        {"booking_id": str(other_booking.id), "when_id": when_id},
        ctx=ctx,
    )
    assert result["error"] == "not_found"


def test_my_bookings_lists_only_mine(ctx, db_session, policy, other_booking):
    mine = make_onsite_booking(
        db_session, policy, date(2026, 11, 5), contact_id=ctx.identity.contact_id
    )
    result = registry.execute("get_my_bookings", {}, ctx=ctx)

    listed = {entry["booking_id"] for entry in result["data"]["bookings"]}
    assert listed == {str(mine.id)}
    # The other booking still exists; it is simply not visible here.
    assert db_session.scalar(select(Booking.id).where(Booking.id == other_booking.id))


def test_an_untouched_booking_stays_untouched(ctx, db_session, other_booking):
    before = (other_booking.status, other_booking.starts_at, other_booking.version)
    registry.execute("prepare_cancel", {"booking_id": str(other_booking.id)}, ctx=ctx)
    db_session.refresh(other_booking)
    assert (other_booking.status, other_booking.starts_at, other_booking.version) == before
    assert other_booking.status is BookingStatus.tentative


@pytest.mark.parametrize("tool_name", sorted(CUSTOMER_ONLY_TOOLS))
def test_visitors_are_refused_the_customer_tools(db_session, policy, tool_name):
    """Even calling past the schema filter, which is the point of the second
    check in execute()."""
    anon_ctx = make_tool_context(db_session, policy, identity=ANONYMOUS)
    result = registry.execute(tool_name, CUSTOMER_ONLY_TOOLS[tool_name], ctx=anon_ctx)
    assert result["ok"] is False
    assert result["error"] == "forbidden"


@pytest.mark.parametrize("tool_name", sorted(CUSTOMER_ONLY_TOOLS))
def test_visitors_are_not_even_offered_the_customer_tools(tool_name):
    assert tool_name not in {schema["name"] for schema in registry.schemas_for(ANONYMOUS)}
