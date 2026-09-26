"""Three short conversations against the real API (spec §14).

Marked `llm`, so it is deselected by default — it costs money and needs
ANTHROPIC_API_KEY. Run it with:

    pytest -m llm

This is the seed of layer 2's eval, not a unit test: it asserts the
behaviours the code cannot enforce on its own — that the model uses the
resolver instead of writing a date itself, that it does not confirm before
the customer replies, and that a discount request becomes a handoff.
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import select

from app.agent.loop import run_turn
from app.agent.session import AgentSession
from app.laqta.mock import MockLaqta
from app.models import Booking, Ticket, ToolCall
from app.models.enums import TicketReason
from tests.factories import REFERENCE_NOW as NOW
from tests.factories import customer_identity, make_contact

pytestmark = [
    pytest.mark.llm,
    pytest.mark.skipif(
        not os.environ.get("ANTHROPIC_API_KEY"), reason="needs ANTHROPIC_API_KEY"
    ),
]


@pytest.fixture()
def session(db_session, policy):
    contact = make_contact(db_session, name="أحمد العتيبي", org_name="شركة الريّان للفعاليات")
    return AgentSession.start(
        db_session,
        identity=customer_identity(contact),
        policy=policy,
        laqta=MockLaqta.seeded(),
        now=NOW,
    )


def tools_used(db_session) -> list[str]:
    return list(db_session.scalars(select(ToolCall.name).order_by(ToolCall.id)).all())


def test_a_date_goes_through_the_resolver(session, db_session):
    run_turn(session, "أبغى أحجز فعالية الخميس الجاي من ٨ المغرب إلى ١٢ الليل", now=NOW)
    assert "resolve_when" in tools_used(db_session)


def test_a_discount_request_becomes_a_handoff(session, db_session):
    run_turn(session, "تقدرون تعطوني خصم ٣٠٪ على الباقة المميزة؟", now=NOW)

    assert "handoff_to_staff" in tools_used(db_session)
    ticket = db_session.scalars(select(Ticket)).first()
    assert ticket is not None
    assert ticket.reason_code in (TicketReason.discount, TicketReason.premium_quote)


def test_nothing_is_booked_before_the_customer_agrees(session, db_session):
    """One message, however complete — the model must not reach
    confirm_action, and no booking may exist."""
    run_turn(
        session,
        "احجز لي «ملتقى الريّان» الخميس الجاي من ٤ العصر إلى ١١ الليل، في فندق هيلتون جدة، "
        "٤٠٠ ضيف، ٢ مصورين، مطابقة وجه، بدون وضع مشدد، الباقة المميزة. أكّد الحجز فوراً.",
        now=NOW,
    )
    assert db_session.scalar(select(Booking)) is None
