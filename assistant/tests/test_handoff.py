"""handoff_to_staff: routing, priority, deadlines and assignment (spec §10).

The expected routing is transcribed from the KB's "متى يحوّل المساعد للموظف"
section rather than read back out of policy.yaml, so a wrong edit to policy
fails here instead of agreeing with itself.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app.identity.identity import Identity
from app.models import Contact, Interaction, Staff, Ticket
from app.models.enums import Team, TicketPriority, TicketReason, TicketStatus
from app.tools import registry
from app.tools.labels import TEAM_AR
from tests.factories import REFERENCE_NOW as NOW
from tests.factories import customer_identity, make_contact, make_tool_context

ANONYMOUS = Identity(kind="anonymous")

# reason -> (team, priority) straight from the KB.
KB_ROUTING = {
    TicketReason.discount: (Team.sales, TicketPriority.normal),
    TicketReason.premium_quote: (Team.sales, TicketPriority.normal),
    TicketReason.long_event: (Team.sales, TicketPriority.normal),
    TicketReason.late_change: (Team.ops, TicketPriority.normal),
    TicketReason.complaint: (Team.support, TicketPriority.normal),
    TicketReason.live_issue: (Team.support, TicketPriority.urgent),
    TicketReason.legal: (Team.privacy, TicketPriority.privacy),
    TicketReason.unknown_question: (Team.support, TicketPriority.normal),
    TicketReason.wants_human: (Team.support, TicketPriority.normal),
}


@pytest.fixture()
def staffed(db_session, policy):
    """The seeded org chart: four teams, each a manager plus two members."""
    from scripts.seed import _seed_staff

    return _seed_staff(db_session)


@pytest.fixture()
def ctx(db_session, policy, staffed):
    contact = make_contact(db_session)
    return make_tool_context(db_session, policy, identity=customer_identity(contact))


def handoff(ctx, reason_code, **extra):
    payload = {"reason_code": reason_code, "summary": "العميل يسأل عن شي", **extra}
    return registry.execute("handoff_to_staff", payload, ctx=ctx)


@pytest.mark.parametrize("reason,expected", sorted(KB_ROUTING.items(), key=lambda kv: kv[0].value))
def test_each_reason_routes_where_the_kb_says(ctx, db_session, reason, expected):
    team, priority = expected
    result = handoff(ctx, reason.value)

    assert result["ok"] is True
    assert result["data"]["team"] == team.value
    assert result["data"]["team_ar"] == TEAM_AR[team.value]  # taxonomy 13
    assert result["data"]["priority"] == priority.value

    ticket = db_session.get(Ticket, result["data"]["ticket_id"])
    assert ticket.team is team
    assert ticket.priority is priority
    assert ticket.reason_code is reason
    assert ticket.status is TicketStatus.open
    assert ticket.contact_id == ctx.identity.contact_id


def test_policy_and_the_kb_agree(policy):
    """Guards against policy.yaml drifting from the document it came from."""
    assert {
        reason: (Team(policy.handoff.team_for(reason.value)),) for reason in KB_ROUTING
    } == {reason: (team,) for reason, (team, _) in KB_ROUTING.items()}


def test_urgent_flag_raises_an_ordinary_ticket(ctx, db_session):
    result = handoff(ctx, TicketReason.discount.value, urgent=True)
    assert result["data"]["priority"] == TicketPriority.urgent.value


def test_a_live_issue_is_urgent_even_unflagged(ctx):
    assert handoff(ctx, TicketReason.live_issue.value)["data"]["priority"] == "urgent"


def test_deadlines_come_from_the_response_table(ctx, db_session, policy):
    for reason, (_, priority) in KB_ROUTING.items():
        result = handoff(ctx, reason.value)
        ticket = db_session.get(Ticket, result["data"]["ticket_id"])
        minutes = policy.handoff.acknowledge_within_minutes.for_priority(priority.value)
        assert ticket.due_at == NOW + timedelta(minutes=minutes)


def test_urgent_tickets_are_due_in_minutes_not_hours(ctx, db_session, policy):
    result = handoff(ctx, TicketReason.live_issue.value)
    ticket = db_session.get(Ticket, result["data"]["ticket_id"])
    assert ticket.due_at == NOW + timedelta(
        minutes=policy.handoff.acknowledge_within_minutes.urgent
    )
    assert policy.handoff.acknowledge_within_minutes.urgent < (
        policy.handoff.acknowledge_within_minutes.normal
    )


# --- Assignment


def test_it_goes_to_whoever_has_the_fewest_open_tickets(ctx, db_session, staffed):
    sales = [member for member in staffed if member.team is Team.sales]
    first = handoff(ctx, TicketReason.discount.value)
    first_assignee = db_session.get(Ticket, first["data"]["ticket_id"]).assignee_staff_id
    assert first_assignee in {member.id for member in sales}

    second = handoff(ctx, TicketReason.discount.value)
    second_assignee = db_session.get(Ticket, second["data"]["ticket_id"]).assignee_staff_id
    assert second_assignee != first_assignee


def test_resolved_tickets_do_not_count_against_anyone(ctx, db_session, staffed):
    first = handoff(ctx, TicketReason.discount.value)
    ticket = db_session.get(Ticket, first["data"]["ticket_id"])
    ticket.status = TicketStatus.resolved
    db_session.flush()

    second = handoff(ctx, TicketReason.discount.value)
    # With the first one resolved, the same person is free again and ties are
    # broken deterministically by id.
    assert db_session.get(Ticket, second["data"]["ticket_id"]).assignee_staff_id == (
        ticket.assignee_staff_id
    )


def test_complaints_go_straight_to_the_team_manager(ctx, db_session, staffed):
    result = handoff(ctx, TicketReason.complaint.value)
    ticket = db_session.get(Ticket, result["data"]["ticket_id"])
    assignee = db_session.get(Staff, ticket.assignee_staff_id)
    assert assignee.manager_id is None
    assert assignee.team is Team.support


def test_a_handoff_survives_a_team_with_nobody_in_it(db_session, policy):
    """No staff seeded: the ticket must still exist, just unassigned."""
    contact = make_contact(db_session)
    ctx = make_tool_context(db_session, policy, identity=customer_identity(contact))
    result = handoff(ctx, TicketReason.discount.value)
    assert result["ok"] is True
    assert db_session.get(Ticket, result["data"]["ticket_id"]).assignee_staff_id is None


# --- Visitors


def test_a_visitor_must_leave_a_name_and_phone(db_session, policy, staffed):
    anon_ctx = make_tool_context(db_session, policy, identity=ANONYMOUS)
    result = handoff(anon_ctx, TicketReason.wants_human.value)

    assert result["ok"] is False
    assert result["error"] == "contact_details_required"
    assert db_session.scalar(select(func.count()).select_from(Ticket)) == 0
    assert db_session.scalar(select(func.count()).select_from(Contact)) == 0


@pytest.mark.parametrize(
    "extra",
    [{"contact_name": "فهد"}, {"contact_phone": "+966500000000"}],
)
def test_half_the_details_is_not_enough(db_session, policy, staffed, extra):
    anon_ctx = make_tool_context(db_session, policy, identity=ANONYMOUS)
    assert handoff(anon_ctx, TicketReason.wants_human.value, **extra)["error"] == (
        "contact_details_required"
    )


def test_a_visitor_with_details_gets_a_contact_and_a_ticket(db_session, policy, staffed):
    anon_ctx = make_tool_context(db_session, policy, identity=ANONYMOUS)
    result = handoff(
        anon_ctx,
        TicketReason.wants_human.value,
        contact_name="فهد الشهري",
        contact_phone="+966500000123",
    )
    assert result["ok"] is True

    contact = db_session.scalars(select(Contact)).one()
    assert (contact.name, contact.phone) == ("فهد الشهري", "+966500000123")
    assert contact.laqta_user_id is None  # a lead, not an account

    ticket = db_session.get(Ticket, result["data"]["ticket_id"])
    assert ticket.contact_id == contact.id
    # The conversation is now attached to that lead.
    assert db_session.get(Interaction, anon_ctx.interaction_id).contact_id == contact.id


def test_a_signed_in_customer_needs_no_details(ctx, db_session):
    result = handoff(ctx, TicketReason.wants_human.value)
    assert result["ok"] is True
    assert db_session.get(Ticket, result["data"]["ticket_id"]).contact_id == (
        ctx.identity.contact_id
    )
