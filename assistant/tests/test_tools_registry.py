"""The registry itself (spec §10): schemas per role, the second role check,
input validation as data, crashes as is_error, and logging.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel
from sqlalchemy import func, select

from app.identity.identity import Identity
from app.models import Contact, ToolCall
from app.models.enums import ContactSource
from app.tools import registry
from app.tools.registry import ToolContext, ToolRegistry
from tests.factories import customer_identity, make_contact, make_tool_context

ANONYMOUS = Identity(kind="anonymous")


@pytest.fixture()
def ctx(db_session, policy):
    contact = make_contact(db_session)
    return make_tool_context(db_session, policy, identity=customer_identity(contact))


@pytest.fixture()
def anon_ctx(db_session, policy):
    return make_tool_context(db_session, policy, identity=ANONYMOUS)


# --- Schemas


def test_anonymous_visitors_see_only_the_open_tools(anon_ctx):
    names = {schema["name"] for schema in registry.schemas_for(ANONYMOUS)}
    assert names == {"search_kb", "resolve_when", "check_availability", "handoff_to_staff"}


def test_customers_additionally_see_the_booking_tools(ctx):
    names = {schema["name"] for schema in registry.schemas_for(ctx.identity)}
    assert names == {
        "search_kb",
        "resolve_when",
        "check_availability",
        "handoff_to_staff",
        "get_my_bookings",
        "prepare_booking",
        "prepare_reschedule",
        "prepare_cancel",
        "confirm_action",
    }


def test_schemas_are_anthropic_shaped(ctx):
    for schema in registry.schemas_for(ctx.identity):
        assert set(schema) == {"name", "description", "input_schema"}
        assert schema["input_schema"]["type"] == "object"
        # Descriptions are part of the contract with the model, not optional.
        assert len(schema["description"]) > 80


def test_only_confirm_and_handoff_declare_side_effects():
    assert {tool.name for tool in registry.all_tools() if tool.side_effects} == {
        "confirm_action",
        "handoff_to_staff",
    }


# --- execute()


def test_unknown_tool_is_data_not_a_crash(ctx):
    result = registry.execute("book_everything", {}, ctx=ctx)
    assert result == {
        "ok": False,
        "error": "unknown_tool",
        "detail": "لا توجد أداة باسم book_everything",
    }
    assert "_exception" not in result


def test_the_role_is_checked_again_at_execution(anon_ctx):
    """The schema filter is not the security boundary — a model can name a
    tool it was never given (spec §4)."""
    result = registry.execute("prepare_booking", {"when_id": "x", "details": {}}, ctx=anon_ctx)
    assert result["ok"] is False
    assert result["error"] == "forbidden"


def test_invalid_input_comes_back_as_correctable_data(ctx):
    result = registry.execute("check_availability", {"when_id": "x"}, ctx=ctx)
    assert result["ok"] is False
    assert result["error"] == "invalid_input"
    assert [field["field"] for field in result["fields"]] == ["city"]
    assert "_exception" not in result


def test_a_crash_is_flagged_as_an_error(ctx, db_session):
    """A tool that raises must come back as is_error: true — the one thing
    the agent loop treats differently from a business refusal — with its
    partial writes undone and the crash still on record.

    A purpose-built exploding tool, registered on its own registry: execute()
    is the same code either way, and this no longer depends on some real tool
    happening to be broken (it used to ride on resolve_when raising
    NotImplementedError, which the resolver no longer does).
    """
    fresh = ToolRegistry()

    @fresh.tool(name="explode", roles={"customer"}, description="Raises, on purpose." * 4)
    def explode(tool_ctx: ToolContext, inp: Input) -> dict:
        tool_ctx.db.add(Contact(name="نصف عملية", source=ContactSource.chat))
        tool_ctx.db.flush()
        raise RuntimeError("قاعدة البيانات اختفت")

    contacts_before = db_session.scalar(select(func.count()).select_from(Contact))
    result = fresh.execute("explode", {}, ctx=ctx)

    assert result["_exception"] is True
    assert result["error"] == "internal_error"
    assert "RuntimeError" in result["detail"]

    # The savepoint undid the half-finished work.
    assert db_session.scalar(select(func.count()).select_from(Contact)) == contacts_before

    # And the crash is logged, which is exactly when the log matters most.
    row = db_session.scalars(select(ToolCall).where(ToolCall.name == "explode")).one()
    assert row.ok is False
    assert row.result["_exception"] is True


# --- Logging


def test_every_call_is_logged(ctx, db_session):
    registry.execute("get_my_bookings", {}, ctx=ctx)
    registry.execute("nope", {"a": 1}, ctx=ctx)

    logged = db_session.scalars(
        select(ToolCall).where(ToolCall.interaction_id == ctx.interaction_id).order_by(ToolCall.id)
    ).all()
    assert [row.name for row in logged] == ["get_my_bookings", "nope"]
    assert [row.ok for row in logged] == [True, False]
    assert all(row.user_turn == ctx.user_turn for row in logged)
    assert all(row.latency_ms >= 0 for row in logged)
    assert logged[1].args == {"a": 1}
    assert logged[1].result["error"] == "unknown_tool"


def test_a_rejected_call_is_still_logged(ctx, db_session):
    """Invalid input is data, not a crash — but it is logged the same way."""
    registry.execute("resolve_when", {"bad": "input"}, ctx=ctx)
    row = db_session.scalars(
        select(ToolCall).where(ToolCall.interaction_id == ctx.interaction_id)
    ).one()
    assert row.name == "resolve_when"
    assert row.ok is False
    assert "_exception" not in row.result


# --- Registration guards


class Input(BaseModel):
    value: int = 0


def test_duplicate_names_are_rejected():
    fresh = ToolRegistry()

    @fresh.tool(name="thing", roles={"customer"}, description="x" * 90)
    def thing(ctx: ToolContext, inp: Input) -> dict:
        return {}

    with pytest.raises(ValueError, match="already registered"):

        @fresh.tool(name="thing", roles={"customer"}, description="y" * 90)
        def thing_again(ctx: ToolContext, inp: Input) -> dict:
            return {}


def test_an_unannotated_input_is_rejected_clearly():
    """Without the annotation there is no schema to send the model, so this
    must say so rather than raise a bare KeyError."""
    fresh = ToolRegistry()
    with pytest.raises(TypeError, match="annotate"):
        fresh.tool(name="thing", roles={"customer"}, description="x" * 90)(lambda ctx, inp: {})


def test_unknown_roles_are_rejected():
    fresh = ToolRegistry()
    with pytest.raises(ValueError, match="unknown roles"):

        @fresh.tool(name="thing", roles={"admin"}, description="x" * 90)
        def thing(ctx: ToolContext, inp: Input) -> dict:
            return {}


def test_a_tool_must_take_ctx_and_input():
    fresh = ToolRegistry()
    with pytest.raises(TypeError, match="exactly"):

        @fresh.tool(name="thing", roles={"customer"}, description="x" * 90)
        def thing(ctx: ToolContext) -> dict:
            return {}


def test_the_input_must_be_a_pydantic_model():
    fresh = ToolRegistry()
    with pytest.raises(TypeError, match="pydantic"):

        @fresh.tool(name="thing", roles={"customer"}, description="x" * 90)
        def thing(ctx: ToolContext, inp: dict) -> dict:
            return {}
