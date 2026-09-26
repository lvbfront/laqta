"""The eval runner, driven by scripted clients — no API calls, no cost.

Runs inside the usual rolled-back `assistant_test` transaction: the runner's
database functions take a session and never pick a database themselves.
The `assistant_eval` guard is tested on its own. `eval.run` is deliberately
not imported here — it redirects `settings.database_url` at import time.
"""

from __future__ import annotations

import json
import warnings

import pytest
from sqlalchemy import select
from sqlalchemy.exc import SAWarning

from app.models import Booking
from eval import database, report, usage
from eval.guard import NotTheEvalDatabase, require_eval_database
from eval.personas import ScriptedTurn, When, load_personas
from eval.runner import run_episode
from eval.simulator import END, SEND
from tests.fakes import FakeClient, FakeResponse, FakeToolUse, calls_tool, fake_usage, says

PERSONAS = {p.id: p for p in load_personas()}
AGENT_MODEL = "claude-sonnet-5"
PERSONA_MODEL = "claude-haiku-4-5"


def customer_says(text: str) -> FakeResponse:
    return FakeResponse([FakeToolUse(name=SEND["name"], input={"text": text})], "tool_use", fake_usage(300, 20))


def customer_leaves(reason: str = "done") -> FakeResponse:
    return FakeResponse([FakeToolUse(name=END["name"], input={"reason": reason})], "tool_use", fake_usage(300, 10))


def run(db_session, policy, persona, agent: FakeClient, customer: FakeClient) -> dict:
    return run_episode(
        db_session,
        persona,
        episode=1,
        policy=policy,
        agent_client=agent,
        persona_client=customer,
        agent_model=AGENT_MODEL,
        persona_model=PERSONA_MODEL,
    )


# --- the database guard


@pytest.mark.parametrize("name", ["assistant", "assistant_test", "assistant_eval_old", "laqta", "postgres"])
def test_the_guard_refuses_every_database_but_assistant_eval(name):
    with pytest.raises(NotTheEvalDatabase):
        require_eval_database(f"postgresql+psycopg://u:p@localhost:5433/{name}")


def test_the_guard_accepts_assistant_eval():
    require_eval_database("postgresql+psycopg://u:p@localhost:5433/assistant_eval")


def test_the_test_session_itself_is_refused(db_session):
    """So a runner entry point handed this session would stop."""
    with pytest.raises(NotTheEvalDatabase):
        require_eval_database(db_session)


# --- seeding


@pytest.mark.parametrize(
    ("persona_id", "key", "status", "triggers"),
    [
        ("p25_cancel_unpaid_tentative", "fahad_workshop_tentative", "tentative", ["confirm_booking"]),
        ("p07_cancel_half_refund_why", "fahad_expo", "confirmed", ["confirm_booking", "mark_paid"]),
        ("p14_live_issue_urgent", "fahad_live", "live", ["confirm_booking", "mark_paid", "window_open"]),
        ("p13_complaint", "ahmed_ended", "ended", ["confirm_booking", "mark_paid", "window_open", "window_close"]),
    ],
)
def test_fixtures_reach_their_status_through_the_state_machine(db_session, policy, persona_id, key, status, triggers):
    ids = database.reset_and_seed(db_session, PERSONAS[persona_id], policy=policy)

    booking = db_session.get(Booking, ids[key])
    assert booking.status.value == status
    assert [e.trigger for e in booking.events] == triggers
    assert booking.laqta_event_id is not None
    assert "seed_jeddah" in ids


def test_reseeding_in_one_session_does_not_confuse_the_identity_map(db_session, policy):
    """RESTART IDENTITY reuses ids; the previous episode's objects must not
    be mistaken for the new rows."""
    persona = PERSONAS["p19_anon_packages_answered"]
    with warnings.catch_warnings():
        warnings.simplefilter("error", SAWarning)
        for _ in range(2):
            run(db_session, policy, persona, FakeClient(says("أهلاً")), FakeClient(customer_leaves()))


# --- scripted turns and provocations


def test_scripted_turns_fire_in_order_when_their_conditions_hold(db_session, policy):
    persona = PERSONAS["a5_internal_only_question"]  # push_number at turn 1, push_sla at turn 2
    agent = FakeClient(says("رد ١"), says("رد ٢"), says("رد ٣"))
    customer = FakeClient(customer_leaves())

    record = run(db_session, policy, persona, agent, customer)

    messages = [e for e in record["events"] if e["type"] == "customer_message"]
    assert [m["source"] for m in messages] == ["opening", "script:push_number", "script:push_sla"]
    assert messages[1]["text"] == next(t.say for t in persona.script if t.id == "push_number")
    assert record["provocation"] == {"id": "opening", "status": "fired", "customer_turn": 1}
    assert record["status"] == "completed"
    assert record["end_reason"] == "persona_ended"
    # The simulator was consulted once, after both scripted turns were spent.
    assert len(customer.calls) == 1
    assert {t["name"] for t in customer.calls[0]["tools"]} == {"send_message", "end_conversation"}


def test_a_provocation_that_never_fires_is_not_provoked_and_the_customer_cannot_leave_early(db_session, policy, tmp_path):
    persona = PERSONAS["a2_bare_yes_two_tokens"].model_copy(update={"max_customer_turns": 3})
    agent = FakeClient(says("وش تبي بالضبط؟"), says("طيب"), says("تمام"))
    customer = FakeClient(customer_says("ألغ المعرض"), customer_says("وانقل المنتدى"))

    record = run(db_session, policy, persona, agent, customer)

    assert record["provocation"] == {"id": "bare_yes", "status": "not_provoked", "customer_turn": None}
    assert record["status"] == "not_provoked"
    assert record["end_reason"] == "max_customer_turns"
    for call in customer.calls:
        assert [t["name"] for t in call["tools"]] == ["send_message"]
        assert call["tool_choice"] == {"type": "tool", "name": "send_message"}

    (tmp_path / "episodes").mkdir()
    (tmp_path / "episodes" / "a2__e01.json").write_text(json.dumps(record, ensure_ascii=False, default=str))
    summary = report.write_report(tmp_path, {"run_id": "t"})
    assert summary["status_counts"] == {"not_provoked": 1}
    assert summary["personas"][0]["completed"] == 0
    assert "**not_provoked**" in (tmp_path / "report.md").read_text()


def test_an_after_tool_script_fires_and_tool_calls_are_logged_with_results_and_usage(db_session, policy):
    persona = PERSONAS["p08_reschedule_free"].model_copy(
        update={
            "adversarial": "partial_booking_id",
            "provocation": "probe",
            "script": [ScriptedTurn(id="probe", when=When(after_tool="get_my_bookings"), say="هذا رقمه")],
        }
    )
    agent = FakeClient(
        FakeResponse(calls_tool("get_my_bookings", {}).content, "tool_use", fake_usage(100, 20, 1500, 0)),
        FakeResponse(says("لقيت حجزك").content, "end_turn", fake_usage(40, 15, 0, 1500)),
        FakeResponse(says("تمام").content, "end_turn", fake_usage(30, 5, 0, 1500)),
    )
    customer = FakeClient(customer_leaves())

    record = run(db_session, policy, persona, agent, customer)

    assert record["provocation"] == {"id": "probe", "status": "fired", "customer_turn": 2}
    first = record["events"][1]
    assert first["type"] == "agent_turn" and len(first["steps"]) == 2
    call = first["steps"][0]["tool_calls"][0]
    assert call["name"] == "get_my_bookings" and call["input"] == {} and call["ok"] is True
    assert record["booking_ids"]["fahad_forum"] in {b["booking_id"] for b in call["result"]["data"]["bookings"]}
    assert first["steps"][0]["usage"] == {
        "input_tokens": 100, "output_tokens": 20, "cache_creation_input_tokens": 1500, "cache_read_input_tokens": 0,
    }
    assert first["usage"]["cache_read_input_tokens"] == 1500

    assert record["usage"]["agent"] == {
        "input_tokens": 170, "output_tokens": 40, "cache_creation_input_tokens": 1500, "cache_read_input_tokens": 3000,
    }
    assert record["usage"]["persona"]["input_tokens"] == 300
    assert record["cost_usd"]["agent"] == pytest.approx(usage.cost_usd(AGENT_MODEL, record["usage"]["agent"]))
    assert record["warnings"] == []

    # What the scorer needs survives the next episode's truncate.
    assert {b["id"] for b in record["final_state"]["bookings"]} >= {record["booking_ids"]["fahad_forum"]}
    json.dumps(record, ensure_ascii=False, default=str)


def test_the_simulator_sees_the_persona_but_not_the_expectations(db_session, policy):
    persona = PERSONAS["a5_internal_only_question"]
    customer = FakeClient(customer_leaves())
    run(db_session, policy, persona, FakeClient(says("١"), says("٢"), says("٣")), customer)

    system = customer.calls[0]["system"]
    assert persona.hidden_state["phone"] in system
    assert persona.voice.style in system
    for hidden in ("handoff_to_staff", "unknown_question", "سعة التشغيل", "no_capacity_implication"):
        assert hidden not in system
    # It sees the conversation as the customer did: its lines, scripted ones
    # included, and the assistant's replies — and nothing else.
    transcript = customer.calls[0]["messages"][0]["content"]
    assert f"You: {persona.opening}" in transcript
    assert f"You: {persona.script[0].say}" in transcript
    assert "Assistant: ٣" in transcript
    assert "tool" not in transcript


def test_an_api_error_ends_the_episode_as_infrastructure_not_as_agent_behaviour(db_session, policy):
    from tests.fakes import transient_api_error

    record = run(
        db_session, policy, PERSONAS["p19_anon_packages_answered"], FakeClient(raises=transient_api_error()), FakeClient()
    )
    assert record["status"] == "infra_error"
    assert record["events"][1]["reply_source"] == "loop_api_error"


# --- cost


def test_cost_counts_cache_writes_and_reads_at_their_own_rates():
    million = {"input_tokens": 1_000_000, "output_tokens": 1_000_000, "cache_creation_input_tokens": 1_000_000, "cache_read_input_tokens": 1_000_000}
    assert usage.cost_usd("claude-sonnet-5", million) == pytest.approx(2.00 + 10.00 + 2.50 + 0.20)
    assert usage.cost_usd("claude-haiku-4-5", million) == pytest.approx(1.00 + 5.00 + 1.25 + 0.10)


def test_an_unpriced_model_has_no_cost_rather_than_zero():
    assert usage.cost_usd("claude-unknown", usage.zero()) is None


def test_the_simulator_asks_nothing_beyond_its_goal_and_leaves_when_it_is_reached(db_session, policy):
    """a3's customer invented a payment-link request after the booking, and
    the correct handoff it drew scored as a forbidden one."""
    persona = PERSONAS["p19_anon_packages_answered"]
    customer = FakeClient(customer_leaves())
    record = run(db_session, policy, persona, FakeClient(says("أهلاً")), customer)

    system = customer.calls[0]["system"]
    assert "Ask for nothing beyond your goal" in system
    assert "Leave as soon as your goal is reached" in system
    assert record["simulator_prompt_sha256"]
