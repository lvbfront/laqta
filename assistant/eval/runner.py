"""One episode: one persona, one conversation, one JSON record.

The agent is driven through the real `app.agent.loop.run_turn` — same system
prompt, same tools, same database writes as the CLI. Nothing here changes
what the agent sees; the runner only watches:

- a recording wrapper around the agent's client keeps every API response in
  call order, for per-step usage;
- `tool_calls` rows give each call's arguments, result, ok flag and latency;
- the session's message list gives every content block the model produced.

Scripted customer turns are checked after every agent reply and sent
verbatim the first time their condition holds, instead of the simulator's
message. An adversarial episode whose provocation never fired is recorded as
`not_provoked` — the scorer must exclude it, never count it as a pass.

No scoring happens here.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from datetime import datetime, timezone
from time import perf_counter
from typing import Any

from sqlalchemy.orm import Session

from app.agent import loop as agent_loop
from app.agent.session import AgentSession
from app.config import Policy
from app.identity.dev_auth import DevAuth
from app.laqta.mock import MockLaqta
from app.models import ToolCall
from app.tools import registry
from eval import database, usage
from eval.personas import Persona, ScriptedTurn, persona_sha256, render
from eval.simulator import PersonaSimulator, SimulatorError
from eval.simulator import prompt_sha256 as simulator_prompt_sha256

RECORD_VERSION = 1


# --- recording the agent's API calls


class RecordingClient:
    """Stands in for `anthropic.Anthropic` in `run_turn`. Only
    `messages.create` is used by the loop, so only that is wrapped."""

    def __init__(self, inner: Any) -> None:
        self.calls: list[dict[str, Any]] = []
        self.messages = _RecordingMessages(inner.messages, self.calls)


class _RecordingMessages:
    def __init__(self, inner: Any, calls: list[dict[str, Any]]) -> None:
        self._inner = inner
        self._calls = calls

    def create(self, **kwargs: Any) -> Any:
        started = perf_counter()
        try:
            response = self._inner.create(**kwargs)
        except Exception as exc:
            self._calls.append(
                {"ok": False, "error": f"{type(exc).__name__}: {exc}", "latency_ms": _ms(started)}
            )
            raise
        self._calls.append(
            {
                "ok": True,
                "response": response,
                "latency_ms": _ms(started),
                "request_id": getattr(response, "_request_id", None),
            }
        )
        return response


def _ms(started: float) -> int:
    return int((perf_counter() - started) * 1000)


# --- scripted turns


def condition_holds(turn: ScriptedTurn, *, db: Session, interaction_id: int, now: datetime, customer_turn: int) -> bool:
    when = turn.when
    if when.after_tool is not None:
        return database.successful_tool_calls(db, interaction_id, when.after_tool) >= when.nth
    if when.live_tokens_at_least is not None:
        return database.live_tokens(db, interaction_id, now=now) >= when.live_tokens_at_least
    return customer_turn >= when.customer_turn


def due_scripted_turn(persona: Persona, fired: dict[str, int], **state: Any) -> ScriptedTurn | None:
    """The first unfired scripted turn whose condition holds, in script order."""
    for turn in persona.script:
        if turn.id not in fired and condition_holds(turn, **state):
            return turn
    return None


def provocation_pending(persona: Persona, fired: dict[str, int]) -> bool:
    return persona.provocation not in (None, "opening") and persona.provocation not in fired


def provocation_status(persona: Persona, fired: dict[str, int]) -> str | None:
    if persona.adversarial is None:
        return None
    if persona.provocation == "opening" or persona.provocation in fired:
        return "fired"
    return "not_provoked"


def english_leaks(text: str, policy: Policy) -> list[str]:
    """English enum words in a simulator-written line. Taxonomy 3 and 5 are
    only meaningful if the customer never said them first."""
    words = (*policy.packages, *policy.addons, "face", "code", "sequential", "both", "strict")
    return sorted({w for w in words if re.search(rf"(?<![A-Za-z_]){re.escape(w)}(?![A-Za-z_])", text, re.IGNORECASE)})


# --- one episode


def run_episode(
    db: Session,
    persona: Persona,
    *,
    episode: int,
    policy: Policy,
    agent_client: Any,
    persona_client: Any,
    agent_model: str,
    persona_model: str,
    on_progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    started_at = datetime.now(timezone.utc)
    wall = perf_counter()
    note = on_progress or (lambda _message: None)

    booking_ids = database.reset_and_seed(db, persona, policy=policy)
    identity = DevAuth(db).parse(persona.identity)
    recorder = RecordingClient(agent_client)
    session = AgentSession.start(db, identity=identity, policy=policy, laqta=MockLaqta.seeded(db), now=persona.now)
    interaction_id = session.interaction.id
    simulator = PersonaSimulator(persona=persona, booking_ids=booking_ids, client=persona_client, model=persona_model)

    events: list[dict[str, Any]] = []
    warnings: list[str] = []
    fired: dict[str, int] = {}
    end_reason: str | None = None
    end_detail: str | None = None

    customer_turn = 0
    text, source, sim_call = render(persona.opening, booking_ids), "opening", None

    while True:
        customer_turn += 1
        events.append(_customer_event(customer_turn, source, text, sim_call))
        if source == "simulator" and (leaked := english_leaks(text, policy)):
            warnings.append(f"customer turn {customer_turn}: simulator used English enum words {leaked}")
        note(f"  customer {customer_turn} [{source}]: {text}")

        tool_mark = database.last_tool_call_id(db, interaction_id)
        message_mark = len(session.messages)
        call_mark = len(recorder.calls)

        reply = agent_loop.run_turn(session, text, now=persona.now, client=recorder)

        agent_event = _agent_event(
            customer_turn=customer_turn,
            reply=reply,
            new_messages=session.messages[message_mark + 1 :],
            calls=recorder.calls[call_mark:],
            usages=session.usage_for_turn(session.user_turn),
            rows=database.tool_call_rows_after(db, interaction_id, tool_mark),
            warnings=warnings,
        )
        events.append(agent_event)
        for step in agent_event["steps"]:
            for call in step["tool_calls"]:
                note(f"    {call['name']} -> {'ok' if call['ok'] else (call['result'] or {}).get('error')}")
        note(f"  agent: {reply}")

        if agent_event["api_errors"]:
            end_reason, end_detail = "infra_error", "; ".join(agent_event["api_errors"])
            break

        simulator.record(text, reply)

        if customer_turn >= persona.max_customer_turns:
            end_reason = "max_customer_turns"
            break

        due = due_scripted_turn(persona, fired, db=db, interaction_id=interaction_id, now=persona.now, customer_turn=customer_turn)
        if due is not None:
            fired[due.id] = customer_turn + 1
            text, source, sim_call = render(due.say, booking_ids), f"script:{due.id}", None
            continue

        try:
            turn = simulator.next_turn(end_allowed=not provocation_pending(persona, fired))
        except SimulatorError as exc:
            events.append({"type": "simulator_error", "after_customer_turn": customer_turn, "error": str(exc), "call": _sim_call(exc.call)})
            end_reason, end_detail = "infra_error", str(exc)
            break
        except Exception as exc:
            if not isinstance(exc, agent_loop.transient_error_types()):
                raise
            events.append({"type": "simulator_error", "after_customer_turn": customer_turn, "error": f"{type(exc).__name__}: {exc}"})
            end_reason, end_detail = "infra_error", f"persona simulator: {type(exc).__name__}"
            break

        if turn.ended:
            events.append({"type": "customer_left", "after_customer_turn": customer_turn, "reason": turn.end_reason, "call": _sim_call(turn.call)})
            end_reason, end_detail = "persona_ended", turn.end_reason
            break
        text, source, sim_call = turn.text, "simulator", turn.call

    session.end(now=persona.now)
    final_state = database.snapshot(db, interaction_id)
    final_state["laqta_calls"] = json.loads(json.dumps(session.laqta.calls, ensure_ascii=False, default=str))

    agent_usage, persona_usage = _usage_totals(events)
    agent_cost = usage.cost_usd(agent_model, agent_usage)
    persona_cost = usage.cost_usd(persona_model, persona_usage)
    status = provocation_status(persona, fired)

    return {
        "record_version": RECORD_VERSION,
        "persona_id": persona.id,
        "persona_title": persona.title,
        # The scorer reads `expected` from the persona file as it is at scoring
        # time; this says whether that is still the file the episode ran with.
        "persona_sha256": persona_sha256(persona.id),
        "simulator_prompt_sha256": simulator_prompt_sha256(),
        "episode": episode,
        "taxonomy": list(persona.taxonomy),
        "adversarial": persona.adversarial,
        "started_at": started_at.isoformat(),
        "duration_s": round(perf_counter() - wall, 1),
        "models": {"agent": agent_model, "persona": persona_model},
        "fingerprint": fingerprint(identity),
        "identity": persona.identity,
        "now": persona.now.isoformat(),
        "interaction_id": interaction_id,
        "booking_ids": booking_ids,
        "context_block": session.context_block,
        "status": "infra_error" if end_reason == "infra_error" else ("not_provoked" if status == "not_provoked" else "completed"),
        "end_reason": end_reason,
        "end_detail": end_detail,
        "customer_turns": customer_turn,
        "provocation": None if status is None else {"id": persona.provocation, "status": status, "customer_turn": 1 if persona.provocation == "opening" else fired.get(persona.provocation)},
        "scripted_turns": [{"id": t.id, "fired_at_customer_turn": fired.get(t.id)} for t in persona.script],
        "events": events,
        "agent_messages": session.messages,
        "final_state": final_state,
        "usage": {"agent": agent_usage, "persona": persona_usage},
        "cost_usd": {
            "agent": agent_cost,
            "persona": persona_cost,
            "total": None if agent_cost is None or persona_cost is None else agent_cost + persona_cost,
        },
        "warnings": warnings,
    }


def fingerprint(identity: Any) -> dict[str, str]:
    """Which system prompt and tool schemas this episode ran against. The
    repo changes between runs; results from different fingerprints are not
    comparable."""
    tools = json.dumps(registry.schemas_for(identity), sort_keys=True, ensure_ascii=False)
    return {
        "system_prompt_sha256": hashlib.sha256(agent_loop.system_prompt().encode("utf-8")).hexdigest(),
        "tools_sha256": hashlib.sha256(tools.encode("utf-8")).hexdigest(),
    }


def _customer_event(turn: int, source: str, text: str, sim_call: Any) -> dict[str, Any]:
    return {
        "type": "customer_message",
        "customer_turn": turn,
        "source": source,  # opening | script:<id> | simulator
        "text": text,
        "simulator_call": _sim_call(sim_call) if sim_call is not None else None,
    }


def _sim_call(call: Any) -> dict[str, Any]:
    return {
        "usage": usage.usage_dict(call.usage),
        "stop_reason": call.stop_reason,
        "latency_ms": call.latency_ms,
        "request_id": call.request_id,
        "end_offered": call.end_offered,
        "tool": call.tool,
        "tool_input": call.tool_input,
    }


def _agent_event(
    *,
    customer_turn: int,
    reply: str,
    new_messages: list[dict[str, Any]],
    calls: list[dict[str, Any]],
    usages: list[Any],
    rows: list[ToolCall],
    warnings: list[str],
) -> dict[str, Any]:
    """Pairs, per API step: the response's usage, the content it produced,
    and for each tool_use block the tool_result the model was sent back and
    the tool_calls row the registry wrote.

    Usage is the session's own record (`AgentSession.usage`, one entry per
    response, appended alongside the assistant message), so the eval counts
    exactly what /debug shows. The recording client supplies what the
    session does not keep — stop reason, latency, request id, errors — and
    its usage is kept only as a cross-check."""
    responses = [c for c in calls if c["ok"]]
    assistant_messages = [m for m in new_messages if m["role"] == "assistant"]
    if not len(responses) == len(assistant_messages) == len(usages):
        warnings.append(
            f"customer turn {customer_turn}: {len(responses)} API responses, {len(assistant_messages)} assistant "
            f"messages, {len(usages)} session usage records — step pairing is unreliable for this turn"
        )

    results: dict[str, dict[str, Any]] = {}
    for message in new_messages:
        if message["role"] == "user" and isinstance(message["content"], list):
            for block in message["content"]:
                if block.get("type") == "tool_result":
                    results[block["tool_use_id"]] = block

    remaining = list(rows)
    steps = []
    for index, message in enumerate(assistant_messages):
        response = responses[index]["response"] if index < len(responses) else None
        tool_calls = []
        for block in message["content"]:
            if block.get("type") != "tool_use":
                continue
            row = _take_row(remaining, block["name"])
            sent_back = results.get(block["id"])
            tool_calls.append(
                {
                    "tool_use_id": block["id"],
                    "name": block["name"],
                    "input": block["input"],
                    "result": json.loads(sent_back["content"]) if sent_back else None,
                    "is_error": sent_back.get("is_error") if sent_back else None,
                    "ok": row.ok if row is not None else None,
                    "latency_ms": row.latency_ms if row is not None else None,
                    "tool_call_row_id": row.id if row is not None else None,
                    "user_turn": row.user_turn if row is not None else None,
                }
            )
        step_usage = usage.usage_dict(vars(usages[index]) if index < len(usages) else None)
        if response is not None and usage.usage_dict(response.usage) != step_usage:
            warnings.append(f"customer turn {customer_turn} step {index + 1}: session usage differs from the API response's")
        steps.append(
            {
                "step": index + 1,
                "model": getattr(response, "model", None),
                "stop_reason": getattr(response, "stop_reason", None),
                "usage": step_usage,
                "latency_ms": responses[index]["latency_ms"] if index < len(responses) else None,
                "request_id": responses[index]["request_id"] if index < len(responses) else None,
                "content": message["content"],
                "tool_calls": tool_calls,
            }
        )

    turn_usage = usage.zero()
    for step in steps:
        turn_usage = usage.add(turn_usage, step["usage"])

    return {
        "type": "agent_turn",
        "customer_turn": customer_turn,
        "reply": reply,
        "reply_source": _reply_source(reply, steps),
        "steps": steps,
        # Calls the loop made itself, not the model: the AGENT_MAX_STEPS handoff.
        "loop_tool_calls": [
            {"name": r.name, "input": r.args, "result": r.result, "ok": r.ok, "tool_call_row_id": r.id, "user_turn": r.user_turn}
            for r in remaining
        ],
        "usage": turn_usage,
        "api_errors": [c["error"] for c in calls if not c["ok"]],
    }


def _take_row(rows: list[ToolCall], name: str) -> ToolCall | None:
    for i, row in enumerate(rows):
        if row.name == name:
            return rows.pop(i)
    return None


def _reply_source(reply: str, steps: list[dict[str, Any]]) -> str:
    """Whether the customer saw the model's words or a canned loop message.
    A canned message is not the model's phrasing and should not be scored as
    such."""
    if reply == agent_loop.API_ERROR_MESSAGE:
        return "loop_api_error"
    if reply == agent_loop.REFUSAL_MESSAGE:
        return "loop_refusal"
    last = steps[-1] if steps else None
    if last is not None and last["stop_reason"] == "max_tokens":
        return "model_truncated"
    if reply == agent_loop.FALLBACK_MESSAGE:
        return "loop_fallback"
    return "model"


def _usage_totals(events: list[dict[str, Any]]) -> tuple[dict[str, int], dict[str, int]]:
    agent, persona = usage.zero(), usage.zero()
    for event in events:
        if event["type"] == "agent_turn":
            agent = usage.add(agent, event["usage"])
        call = event.get("simulator_call") or event.get("call")
        if call is not None and "usage" in call:
            persona = usage.add(persona, call["usage"])
    return agent, persona
