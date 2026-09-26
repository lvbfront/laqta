"""The agent loop (spec §12), driven by a scripted client — no API calls."""

from __future__ import annotations

import json

import pytest
from sqlalchemy import func, select

from app.agent.loop import (
    API_ERROR_MESSAGE,
    FALLBACK_MESSAGE,
    REFUSAL_MESSAGE,
    TRUNCATED_NOTE,
    run_turn,
    system_prompt,
)
from app.agent.session import AgentSession
from app.config import AGENT_MAX_STEPS, AGENT_MAX_TOKENS, settings
from app.identity.identity import Identity
from app.models import Interaction, Ticket, ToolCall
from app.models.enums import TicketReason
from tests.factories import REFERENCE_NOW as NOW
from tests.factories import customer_identity, make_contact
from tests.fakes import (
    FakeClient,
    FakeResponse,
    FakeText,
    auth_api_error,
    calls_tool,
    says,
    transient_api_error,
)

SEARCH = {"query": "وش الباقات المتوفرة؟"}


@pytest.fixture(autouse=True)
def stub_embeddings(monkeypatch):
    """search_kb is the harmless tool these tests drive the loop with; keep
    the 2GB model out of it."""
    from app.config import EMBEDDING_DIM

    monkeypatch.setattr(
        "app.kb.search.embed_query", lambda text: [1.0] + [0.0] * (EMBEDDING_DIM - 1)
    )


@pytest.fixture()
def session(db_session, policy):
    contact = make_contact(db_session)
    return AgentSession.start(
        db_session,
        identity=customer_identity(contact),
        policy=policy,
        laqta=__import__("app.laqta.mock", fromlist=["MockLaqta"]).MockLaqta.seeded(),
        now=NOW,
    )


@pytest.fixture()
def anon_session(db_session, policy):
    from app.laqta.mock import MockLaqta

    return AgentSession.start(
        db_session,
        identity=Identity(kind="anonymous"),
        policy=policy,
        laqta=MockLaqta.seeded(),
        now=NOW,
    )


# --- A plain turn


def test_a_reply_with_no_tools_comes_straight_back(session):
    client = FakeClient(says("أهلاً فيك! كيف أقدر أساعدك؟"))
    reply = run_turn(session, "السلام عليكم", now=NOW, client=client)

    assert reply == "أهلاً فيك! كيف أقدر أساعدك؟"
    assert len(client.calls) == 1
    assert [message["role"] for message in session.messages] == ["user", "assistant"]


def test_the_transcript_is_saved_after_every_turn(session, db_session):
    run_turn(session, "مرحبا", now=NOW, client=FakeClient(says("هلا")))

    stored = db_session.get(Interaction, session.interaction.id).transcript
    assert [entry["role"] for entry in stored] == ["user", "assistant"]
    assert stored[0]["content"] == "مرحبا"


# --- The counter the mandatory confirmation depends on


def test_user_turn_counts_customer_messages_not_tool_calls(session):
    """confirm_action refuses unless user_turn moved since the prepare, so a
    turn that makes three tool calls must still count as one message —
    otherwise the model could prepare and confirm without the customer
    saying anything (spec §8)."""
    client = FakeClient(
        calls_tool("search_kb", SEARCH),
        calls_tool("search_kb", SEARCH),
        calls_tool("search_kb", SEARCH),
        says("تم"),
    )
    run_turn(session, "سؤال", now=NOW, client=client)

    assert session.user_turn == 1

    run_turn(session, "سؤال ثاني", now=NOW, client=FakeClient(says("تم")))
    assert session.user_turn == 2


def test_tools_see_the_current_turn_number(session, db_session):
    run_turn(session, "سؤال", now=NOW, client=FakeClient(calls_tool("search_kb", SEARCH), says("تم")))
    run_turn(session, "ثاني", now=NOW, client=FakeClient(calls_tool("search_kb", SEARCH), says("تم")))

    logged = db_session.scalars(select(ToolCall).order_by(ToolCall.id)).all()
    assert [row.user_turn for row in logged] == [1, 2]


# --- Tool calls


def test_a_tool_call_is_executed_and_its_result_fed_back(session, db_session):
    client = FakeClient(
        calls_tool("search_kb", SEARCH, block_id="toolu_7"),
        says("ما لقيت شي في المستند، خلني أحوّلك."),
    )
    reply = run_turn(session, "وش الباقات؟", now=NOW, client=client)

    assert reply.startswith("ما لقيت")
    assert db_session.scalar(select(func.count()).select_from(ToolCall)) == 1

    results = session.messages[2]["content"]
    assert results[0]["type"] == "tool_result"
    assert results[0]["tool_use_id"] == "toolu_7"
    assert json.loads(results[0]["content"])["ok"] is True

    # The second request carried the result back.
    assert client.calls[1]["messages"][-1]["content"][0]["tool_use_id"] == "toolu_7"


def test_a_business_refusal_is_not_an_error(session):
    """ok: false is ordinary data — flagging it as is_error would teach the
    model to treat a full date or a missing field as a system fault."""
    client = FakeClient(
        calls_tool("prepare_cancel", {"booking_id": "00000000-0000-4000-8000-000000000000"}),
        says("ما لقيت الحجز."),
    )
    run_turn(session, "ألغِ حجزي", now=NOW, client=client)

    result = session.messages[2]["content"][0]
    assert json.loads(result["content"])["error"] == "not_found"
    assert result["is_error"] is False


def test_a_crashing_tool_is_flagged_as_an_error(session, monkeypatch):
    def boom(text):
        raise RuntimeError("embedding backend down")

    monkeypatch.setattr("app.kb.search.embed_query", boom)
    client = FakeClient(calls_tool("search_kb", SEARCH), says("صار خلل."))
    run_turn(session, "وش الباقات؟", now=NOW, client=client)

    result = session.messages[2]["content"][0]
    assert result["is_error"] is True
    assert json.loads(result["content"])["error"] == "internal_error"


# --- Request shape


def test_the_static_prompt_is_cached_and_the_context_block_is_not(session):
    client = FakeClient(says("هلا"))
    run_turn(session, "مرحبا", now=NOW, client=client)

    blocks = client.calls[0]["system"]
    assert len(blocks) == 2
    assert blocks[0]["text"] == system_prompt()
    assert blocks[0]["cache_control"] == {"type": "ephemeral"}
    # Volatile half, after the breakpoint, uncached.
    assert blocks[1]["text"] == session.context_block
    assert "cache_control" not in blocks[1]


def test_model_and_sampling_parameters(session):
    client = FakeClient(says("هلا"))
    run_turn(session, "مرحبا", now=NOW, client=client)

    call = client.calls[0]
    assert call["model"] == settings.agent_model
    assert call["max_tokens"] == AGENT_MAX_TOKENS
    assert call["thinking"] == {"type": "adaptive"}
    # Sonnet 5 rejects both outright.
    assert "temperature" not in call
    assert "budget_tokens" not in json.dumps(call["thinking"])


def test_a_customer_and_a_visitor_are_offered_different_tools(session, anon_session):
    customer_client = FakeClient(says("هلا"))
    run_turn(session, "مرحبا", now=NOW, client=customer_client)

    visitor_client = FakeClient(says("هلا"))
    run_turn(anon_session, "مرحبا", now=NOW, client=visitor_client)

    assert "prepare_booking" in customer_client.tool_names_offered()
    assert "prepare_booking" not in visitor_client.tool_names_offered()
    assert "search_kb" in visitor_client.tool_names_offered()


# --- Safety nets


def test_the_step_cap_hands_off_through_the_tool(session, db_session):
    """A model stuck in a tool loop ends with a ticket a human will see, and
    the ticket goes through handoff_to_staff so it is routed and logged like
    any other — not written behind the tool layer's back."""
    client = FakeClient(*[calls_tool("search_kb", SEARCH) for _ in range(AGENT_MAX_STEPS)])
    reply = run_turn(session, "سؤال", now=NOW, client=client)

    assert reply == FALLBACK_MESSAGE
    assert len(client.calls) == AGENT_MAX_STEPS

    ticket = db_session.scalars(select(Ticket)).one()
    assert ticket.reason_code is TicketReason.wants_human
    assert ticket.contact_id == session.identity.contact_id


def test_a_truncated_reply_is_marked_as_unfinished(session):
    client = FakeClient(FakeResponse([FakeText("الحجز المبدئي لـ«ملتقى")], "max_tokens"))
    reply = run_turn(session, "احجز لي", now=NOW, client=client)
    assert reply.endswith(TRUNCATED_NOTE)


def test_a_refusal_is_turned_into_an_offer_to_hand_off(session):
    client = FakeClient(FakeResponse([], "refusal"))
    assert run_turn(session, "...", now=NOW, client=client) == REFUSAL_MESSAGE


def test_a_transient_api_failure_does_not_end_the_conversation(session, db_session):
    client = FakeClient(raises=transient_api_error())
    reply = run_turn(session, "مرحبا", now=NOW, client=client)

    assert reply == API_ERROR_MESSAGE
    # The customer's message is still on record, so they can just repeat it.
    assert db_session.get(Interaction, session.interaction.id).transcript[0]["content"] == "مرحبا"


def test_a_missing_api_key_is_not_hidden_behind_an_apology(session):
    """Authentication is a misconfiguration, not a blip. Absorbing it would
    show the customer "a small technical problem" while hiding from the
    operator the one thing they could actually fix."""
    client = FakeClient(raises=auth_api_error())
    with pytest.raises(Exception, match="x-api-key"):
        run_turn(session, "مرحبا", now=NOW, client=client)


def test_an_unexpected_error_is_not_swallowed(session):
    """A bug in our own code must surface, not hide behind a polite Arabic
    apology."""
    client = FakeClient(raises=ValueError("a bug in our own code"))
    with pytest.raises(ValueError, match="a bug in our own code"):
        run_turn(session, "مرحبا", now=NOW, client=client)


def test_debug_events_are_reported(session):
    seen: list[str] = []
    client = FakeClient(calls_tool("search_kb", SEARCH), says("تم"))
    run_turn(session, "سؤال", now=NOW, client=client, on_event=seen.append)

    assert any("search_kb" in line for line in seen)
    assert any("stop_reason" in line for line in seen)


# --- The prompt itself


def test_author_comments_never_reach_the_model():
    from app.config import SYSTEM_PROMPT_PATH

    raw = SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
    assert "<!--" in raw and "Voice" in raw  # the note for editors exists...
    assert "<!--" not in system_prompt()  # ...and is stripped before sending
    assert "Voice" not in system_prompt()


def test_the_prompt_forbids_emoji_and_requires_neutral_address():
    prompt = system_prompt()
    assert "Never use emoji" in prompt
    assert "gender-neutral Arabic" in prompt
    assert "Never infer gender from a name" in prompt


# --- Token usage


def test_usage_is_recorded_per_call_and_summed_per_turn(session):
    from tests.fakes import fake_usage

    first = calls_tool("search_kb", SEARCH)
    first.usage = fake_usage(120, 40, cache_creation_input_tokens=2600, cache_read_input_tokens=0)
    second = says("تم")
    second.usage = fake_usage(310, 25, cache_creation_input_tokens=0, cache_read_input_tokens=2600)

    seen: list[str] = []
    run_turn(session, "سؤال", now=NOW, client=FakeClient(first, second), on_event=seen.append)

    assert [(u.call, u.cache_read_input_tokens) for u in session.usage] == [(1, 0), (2, 2600)]
    assert "tokens: in=310 out=25 cache_write=0 cache_read=2600" in seen
    assert "turn 1 tokens (2 calls): in=430 out=65 cache_write=2600 cache_read=2600" in seen


def test_missing_cache_fields_count_as_zero(session):
    """The SDK types both cache fields as optional."""
    run_turn(session, "مرحبا", now=NOW, client=FakeClient(says("هلا")))
    usage = session.usage[0]
    assert (usage.cache_creation_input_tokens, usage.cache_read_input_tokens) == (0, 0)


def test_usage_is_reported_even_when_the_turn_fails(session):
    """The calls before a failure were billed."""
    client = FakeClient(calls_tool("search_kb", SEARCH))
    scripted = client.messages.create

    def fail_once_the_script_runs_out(**kwargs):
        if not client.messages.responses:
            raise transient_api_error()
        return scripted(**kwargs)

    client.messages.create = fail_once_the_script_runs_out  # type: ignore[method-assign]
    seen: list[str] = []
    assert run_turn(session, "سؤال", now=NOW, client=client, on_event=seen.append) == API_ERROR_MESSAGE
    assert any(line.startswith("turn 1 tokens (1 calls)") for line in seen)
