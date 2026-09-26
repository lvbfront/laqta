"""The context block (spec §12).

The model has no other way to know what day it is, who it is talking to, or
what happened last time — so every line here is load-bearing.
"""

from __future__ import annotations

import re
from datetime import date, timedelta

import pytest

from app.agent.context import build_context_block
from app.domain.booking_state import Trigger, apply
from app.identity.identity import Identity
from app.models.enums import Team, TicketPriority, TicketReason, TicketStatus
from app.models.interaction import Interaction
from app.models.ticket import Ticket
from tests.factories import REFERENCE_NOW as NOW
from tests.factories import (
    customer_identity,
    make_contact,
    make_interaction,
    make_onsite_booking,
)

FUTURE_DAY = date(2026, 10, 15)


@pytest.fixture()
def contact(db_session):
    return make_contact(db_session, name="أحمد العتيبي", org_name="شركة الريّان للفعاليات")


def block_for(db_session, identity, policy) -> str:
    return build_context_block(db_session, identity, now=NOW, policy=policy)


def test_today_is_given_in_both_calendars(db_session, contact, policy):
    """NOW is the spec's reference moment: Friday 11 September 2026,
    29 Rabi' al-Awwal 1448, 14:05 Riyadh."""
    block = block_for(db_session, customer_identity(contact), policy)
    today = block.splitlines()[0]

    assert "الجمعة 11 سبتمبر 2026" in today
    assert "29" in today and "1448" in today  # Hijri day and year
    assert "14:05" in today
    assert "بتوقيت الرياض" in today


def test_a_signed_in_customer_is_named_with_their_organization(db_session, contact, policy):
    block = block_for(db_session, customer_identity(contact), policy)
    assert "عميل مسجل — أحمد العتيبي، شركة الريّان للفعاليات" in block


def test_a_visitor_is_told_to_be_unbookable(db_session, policy):
    block = block_for(db_session, Identity(kind="anonymous"), policy)
    assert "زائر غير مسجل" in block
    assert "ما يقدر يحجز" in block
    # No customer history to speak of, so no empty headings either.
    assert "حجوزاته" not in block
    assert "تذاكر مفتوحة" not in block


def test_live_bookings_are_listed_with_their_payment_deadline(db_session, contact, policy):
    make_onsite_booking(db_session, policy, FUTURE_DAY, contact_id=contact.id)
    block = block_for(db_session, customer_identity(contact), policy)

    assert "«ملتقى تجريبي»" in block
    assert "15 أكتوبر" in block
    assert "جدة" in block
    assert "مبدئي" in block
    assert "الدفع قبل" in block


def test_no_part_of_a_booking_id_is_in_the_block(db_session, contact, policy):
    """Taxonomy 2: the short id printed here was completed into a padded
    UUID. Every id comes from get_my_bookings, so neither the id nor any
    8+ character hex run belongs here. (The id's 4-character blocks are not
    checked one by one: «2026» or «1448» would match one by chance.)"""
    bookings = [
        make_onsite_booking(db_session, policy, FUTURE_DAY + timedelta(days=offset), contact_id=contact.id)
        for offset in range(3)
    ]
    block = block_for(db_session, customer_identity(contact), policy)

    for booking in bookings:
        assert str(booking.id) not in block
        assert str(booking.id).split("-")[0] not in block
    assert not re.search(r"[0-9a-f]{8,}", block, re.IGNORECASE), block
    bookings_line = next(line for line in block.splitlines() if line.startswith("حجوزاته:"))
    assert "#" not in bookings_line


def test_a_customer_with_no_bookings_is_told_so(db_session, contact, policy):
    assert "ما فيه حجوزات حالية" in block_for(db_session, customer_identity(contact), policy)


def test_finished_bookings_are_left_out(db_session, contact, policy):
    booking = make_onsite_booking(db_session, policy, FUTURE_DAY, contact_id=contact.id)
    apply(booking, Trigger.cancel, now=NOW, policy=policy, actor="customer:1")
    db_session.flush()

    assert "ما فيه حجوزات حالية" in block_for(db_session, customer_identity(contact), policy)


def test_open_tickets_name_the_team_holding_them(db_session, contact, policy):
    interaction = make_interaction(db_session, identity=customer_identity(contact))
    db_session.add(
        Ticket(
            contact_id=contact.id,
            interaction_id=interaction.id,
            team=Team.sales,
            priority=TicketPriority.normal,
            reason_code=TicketReason.discount,
            summary="طلب خصم",
            status=TicketStatus.open,
            due_at=NOW + timedelta(hours=4),
        )
    )
    db_session.flush()

    block = block_for(db_session, customer_identity(contact), policy)
    assert "تذاكر مفتوحة" in block
    assert "طلب خصم" in block
    assert "المبيعات" in block


def test_resolved_tickets_are_left_out(db_session, contact, policy):
    interaction = make_interaction(db_session, identity=customer_identity(contact))
    db_session.add(
        Ticket(
            contact_id=contact.id,
            interaction_id=interaction.id,
            team=Team.sales,
            priority=TicketPriority.normal,
            reason_code=TicketReason.discount,
            summary="طلب خصم قديم",
            status=TicketStatus.resolved,
            due_at=NOW,
            resolved_at=NOW,
        )
    )
    db_session.flush()

    assert "تذاكر مفتوحة" not in block_for(db_session, customer_identity(contact), policy)


def test_the_last_conversation_is_recalled(db_session, contact, policy):
    """This is what the previous session's summary was written for."""
    previous = make_interaction(db_session, identity=customer_identity(contact))
    previous.summary = "حجز مبدئي لملتقى الريّان وطلب خصم فتحوّل للمبيعات."
    previous.ended_at = NOW - timedelta(days=2)
    db_session.flush()

    block = block_for(db_session, customer_identity(contact), policy)
    assert "آخر تواصل" in block
    assert "ملتقى الريّان" in block


def test_an_unfinished_session_is_not_recalled_as_history(db_session, contact, policy):
    make_interaction(db_session, identity=customer_identity(contact))
    assert "آخر تواصل" not in block_for(db_session, customer_identity(contact), policy)


def test_the_block_stays_small(db_session, contact, policy):
    """Spec §12 wants it under ~300 tokens. Arabic runs roughly 2–3 chars per
    token, so this bound is deliberately generous and still catches a block
    that has started dumping history."""
    for offset in range(6):
        make_onsite_booking(
            db_session, policy, FUTURE_DAY + timedelta(days=offset), contact_id=contact.id
        )

    block = block_for(db_session, customer_identity(contact), policy)
    assert len(block) < 900


def test_staff_are_named_with_their_team(db_session, policy):
    from app.models.staff import Staff

    staff = Staff(name="سارة الدوسري", email="sales.manager@laqta.test", team=Team.sales)
    db_session.add(staff)
    db_session.flush()

    block = build_context_block(
        db_session, Identity(kind="staff", staff_id=staff.id), now=NOW, policy=policy
    )
    assert "موظف — سارة الدوسري" in block
    assert "المبيعات" in block


# --- Gender (taxonomy 8): stated in the record or explicitly unknown, never guessed


def test_a_customer_with_no_stated_gender_is_marked_unstated(db_session, contact, policy):
    """أحمد is a name, not a stated gender. The line must say so, so the
    model has nothing to infer from."""
    block = block_for(db_session, customer_identity(contact), policy)
    assert "الجنس: غير مذكور في السجل." in block
    assert "ذكر" not in block


def test_a_stated_gender_is_passed_through(db_session, policy):
    from app.models.enums import Gender

    contact = make_contact(db_session, name="أحمد العتيبي", gender=Gender.female)
    block = block_for(db_session, customer_identity(contact), policy)
    assert "الجنس: أنثى (مذكور في السجل)." in block


def test_a_visitor_has_no_stated_gender(db_session, policy):
    assert "الجنس: غير مذكور في السجل." in block_for(db_session, Identity(kind="anonymous"), policy)
