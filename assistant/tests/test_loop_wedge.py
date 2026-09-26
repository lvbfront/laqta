"""A tool call that never gets its result attached wedges the whole session.

The Anthropic API requires every `tool_use` block to be answered by a
`tool_result` in the next message. `registry.execute` is careful never to
raise — a crashing tool comes back as data — but its own bookkeeping sits
outside that guarantee: the `tool_calls` row is written and committed after
the savepoint closes, and a database that has gone away raises there.

If that happens between the `tool_use` and its `tool_result`, the session's
message list is malformed from then on. The turn that failed is not the
cost; every later turn on that session is, because each one resends the
whole history. So the loop attaches results for the unanswered calls on its
way out.
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import select

from app.agent.loop import run_turn
from app.agent.session import AgentSession
from app.laqta.mock import MockLaqta
from app.models import ToolCall
from tests.factories import REFERENCE_NOW as NOW
from tests.factories import customer_identity, make_contact
from tests.fakes import FakeClient, FakeResponse, FakeToolUse, calls_tool, says

SEARCH = {"query": "وش الباقات المتوفرة؟"}


def three_calls_at_once() -> FakeResponse:
    """One response asking for three tools in parallel."""
    return FakeResponse(
        [FakeToolUse(name="search_kb", input=SEARCH, id=f"toolu_{i}") for i in range(3)],
        "tool_use",
    )


@pytest.fixture(autouse=True)
def stub_embeddings(monkeypatch):
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
        laqta=MockLaqta.seeded(),
        now=NOW,
    )


@pytest.fixture()
def tool_log_commit_fails(db_session, monkeypatch):
    """Make exactly the commit that would persist a `tool_calls` row raise.

    Narrower than patching `commit` outright: the tool has already run and
    its own writes have already been committed by then, which is what makes
    this the gap between a tool_use and its tool_result rather than a
    failure before the tool ever ran.
    """
    real_commit = db_session.commit

    def commit(*args, **kwargs):
        if any(isinstance(pending, ToolCall) for pending in db_session.new):
            raise RuntimeError("server closed the connection unexpectedly")
        return real_commit(*args, **kwargs)

    monkeypatch.setattr(db_session, "commit", commit)


def tool_use_ids(messages) -> list[str]:
    return [
        block["id"]
        for message in messages
        if message["role"] == "assistant"
        for block in message["content"]
        if block.get("type") == "tool_use"
    ]


def tool_result_ids(messages) -> list[str]:
    return [
        block["tool_use_id"]
        for message in messages
        if message["role"] == "user" and isinstance(message["content"], list)
        for block in message["content"]
        if block.get("type") == "tool_result"
    ]


def test_a_failed_turn_leaves_a_sendable_conversation(
    session, db_session, tool_log_commit_fails, monkeypatch
):
    """Turn 1 dies inside the tool step. Turn 2 has to be a request the API
    would accept."""
    with pytest.raises(RuntimeError, match="server closed the connection"):
        run_turn(
            session,
            "وش الباقات؟",
            now=NOW,
            client=FakeClient(calls_tool("search_kb", SEARCH, block_id="toolu_wedged")),
        )

    assert tool_use_ids(session.messages) == ["toolu_wedged"]
    assert tool_result_ids(session.messages) == ["toolu_wedged"]

    # The database is working again; the customer tries once more.
    monkeypatch.undo()
    next_client = FakeClient(says("الباقات ثلاث."))
    assert run_turn(session, "؟", now=NOW, client=next_client) == "الباقات ثلاث."

    sent = next_client.calls[-1]["messages"]
    assert tool_use_ids(sent) == tool_result_ids(sent), "unanswered tool_use in the request"


def test_the_model_is_told_the_call_failed(session, db_session, tool_log_commit_fails):
    """The stand-in result is an error, not a silent empty success: a model
    resuming this conversation must not read it as the tool having worked."""
    with pytest.raises(RuntimeError):
        run_turn(
            session,
            "وش الباقات؟",
            now=NOW,
            client=FakeClient(calls_tool("search_kb", SEARCH, block_id="toolu_wedged")),
        )

    results = [
        block
        for message in session.messages
        if message["role"] == "user" and isinstance(message["content"], list)
        for block in message["content"]
        if block.get("type") == "tool_result"
    ]
    assert len(results) == 1
    assert results[0]["is_error"] is True
    assert "server closed the connection" in results[0]["content"]
    assert json.loads(results[0]["content"])["_exception"] is True


def results_by_id(messages) -> dict[str, dict]:
    return {
        block["tool_use_id"]: json.loads(block["content"])
        for message in messages
        if message["role"] == "user" and isinstance(message["content"], list)
        for block in message["content"]
        if block.get("type") == "tool_result"
    }


def test_every_call_in_a_parallel_step_is_answered(
    session, db_session, tool_log_commit_fails
):
    """Several tool_use blocks in one response, failing on the first: the
    ones that never ran still need results, or the request stays malformed."""
    with pytest.raises(RuntimeError):
        run_turn(session, "وش الباقات؟", now=NOW, client=FakeClient(three_calls_at_once()))

    assert tool_use_ids(session.messages) == ["toolu_0", "toolu_1", "toolu_2"]
    assert tool_result_ids(session.messages) == ["toolu_0", "toolu_1", "toolu_2"]


def test_an_interrupted_call_is_not_reported_as_a_failure(
    session, db_session, tool_log_commit_fails
):
    """The call that was running when the exception hit had already reached
    the tool. Its own writes roll back with the savepoint, but MockLaqta is
    an in-memory object that keeps whatever it was handed, and the real Laqta
    will be an HTTP call that cannot be taken back at all. So the honest
    answer is that the outcome is unknown — telling the model it failed would
    invite it to redo a side effect that may already have happened, or to
    tell the customer nothing happened when something did.

    The calls queued behind it are a different case: those genuinely never
    started, and saying so lets the model just call them again.
    """
    with pytest.raises(RuntimeError):
        run_turn(session, "وش الباقات؟", now=NOW, client=FakeClient(three_calls_at_once()))

    results = results_by_id(session.messages)
    interrupted, never_ran = results["toolu_0"], [results["toolu_1"], results["toolu_2"]]

    assert interrupted != never_ran[0], "the interrupted call reads the same as one that never ran"

    assert interrupted["error"] == "interrupted"
    assert "Call it again" in interrupted["detail"], "search_kb changes nothing"

    for result in never_ran:
        assert result["error"] == "not_run"
        assert "safe to call again" in result["detail"]

    # Both are still faults, so both still reach the model as errors, and
    # both still name what actually went wrong.
    for result in (interrupted, *never_ran):
        assert result["ok"] is False
        assert result["_exception"] is True
        assert "server closed the connection" in result["cause"]


def test_a_lone_interrupted_call_is_reported_as_unknown(
    session, db_session, tool_log_commit_fails
):
    """One call in the step, so there is nothing queued behind it — it is the
    interrupted one, not a never-ran one."""
    with pytest.raises(RuntimeError):
        run_turn(
            session,
            "وش الباقات؟",
            now=NOW,
            client=FakeClient(calls_tool("search_kb", SEARCH, block_id="toolu_wedged")),
        )

    assert results_by_id(session.messages)["toolu_wedged"]["error"] == "interrupted"


def test_a_working_turn_is_unchanged(session, db_session):
    """The control: normal tool calls still pair up one for one, and the
    rows are still logged."""
    run_turn(
        session,
        "وش الباقات؟",
        now=NOW,
        client=FakeClient(calls_tool("search_kb", SEARCH, block_id="toolu_ok"), says("تمام")),
    )

    assert tool_use_ids(session.messages) == ["toolu_ok"]
    assert tool_result_ids(session.messages) == ["toolu_ok"]
    assert [row.name for row in db_session.scalars(select(ToolCall)).all()] == ["search_kb"]


# --- What the interrupted message tells the model to do next


def test_the_advice_never_names_a_tool_the_speaker_does_not_have(policy):
    """The message points at a tool to check state with. Which tools exist
    depends on who is speaking — handoff_to_staff is reachable by an
    anonymous visitor, who has no get_my_bookings — so a message naming one
    they were never given would send the model after a tool that is not in
    its list."""
    import re

    from app.agent.loop import _interrupted
    from app.identity.identity import Identity
    from app.tools import registry
    from tests.factories import customer_identity, make_contact

    every_tool = {tool.name for tool in registry.all_tools()}
    identities = {
        "anonymous": Identity(kind="anonymous"),
        "staff": Identity(kind="staff", staff_id=1),
    }

    for label, identity in identities.items():
        available = {schema["name"] for schema in registry.schemas_for(identity)}
        for name in available:
            detail = _interrupted(name, "x")["detail"]
            named = {word for word in re.findall(r"[a-z_]{4,}", detail)} & every_tool
            assert named <= available, (
                f"the message for {name} as {label} names {sorted(named - available)}, "
                f"which {label} cannot call"
            )


def test_a_customer_is_told_to_check_before_retrying_a_confirm(db_session, policy):
    """The one case where a tool can answer the question. confirm_action is
    customer-only, and a customer has get_my_bookings."""
    from app.agent.loop import _interrupted
    from app.tools import registry
    from tests.factories import customer_identity, make_contact

    identity = customer_identity(make_contact(db_session))
    available = {schema["name"] for schema in registry.schemas_for(identity)}
    assert {"confirm_action", "get_my_bookings"} <= available

    detail = _interrupted("confirm_action", "x")["detail"]
    assert "get_my_bookings" in detail
    assert "do not tell the customer it failed" in detail.lower()


def test_an_interrupted_handoff_names_no_tool_at_all():
    """Nothing can see a ticket — not get_my_bookings, which returns
    bookings, and there is no get_my_tickets. So the message says so instead
    of sending the model somewhere useless."""
    from app.agent.loop import _interrupted
    from app.tools import registry

    assert registry.get("handoff_to_staff").side_effects is True
    detail = _interrupted("handoff_to_staff", "x")["detail"]

    assert "no tool can check" in detail
    assert "get_my_bookings" not in detail
