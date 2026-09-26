"""What happened during one turn, assembled after it.

The loop returns a string. Everything else here is read back from places that
are already public: `tool_calls` and `confirmations` rows, the session's own
usage records and its resolved-date store, and the recording client's per-step
data. Nothing reaches into app/ internals and nothing changed there to make
this possible.

What is still missing, and is listed as missing rather than guessed at:

- the model's thinking blocks — they are in session.messages, but showing a
  customer-facing panel the model's reasoning is a different decision from
  showing it tool calls, so it is not shown here;
- which step a tool call belongs to when one turn makes several — the
  tool_calls rows carry user_turn, not step, so calls are listed per turn;
- why the model chose a tool. Nothing records that.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select

from app.agent.loop import API_ERROR_MESSAGE, FALLBACK_MESSAGE, REFUSAL_MESSAGE
from app.agent.session import AgentSession
from app.models import Confirmation, ToolCall
from server.recording import Step

# Exactly the eval runner's distinction, and for the same reason: three of
# these are sentences the loop wrote, not the model, and presenting them as
# the assistant's own words would misreport what happened.
CANNED = {
    API_ERROR_MESSAGE: "loop_api_error",
    REFUSAL_MESSAGE: "loop_refusal",
    FALLBACK_MESSAGE: "loop_fallback",
}


def reply_source(reply: str, steps: list[Step]) -> str:
    if reply in CANNED:
        return CANNED[reply]
    last = next((step for step in reversed(steps) if step.ok), None)
    if last is not None and last.stop_reason == "max_tokens":
        return "model_truncated"
    return "model"


def for_turn(
    session: AgentSession,
    *,
    user_turn: int,
    steps: list[Step],
    latency_ms: int,
    now: datetime,
    dev: bool,
) -> dict[str, Any]:
    """The dev panel's payload. Empty outside dev — a customer's browser has
    no business holding tool arguments."""
    if not dev:
        return {}

    calls = session.db.scalars(
        select(ToolCall)
        .where(ToolCall.interaction_id == session.interaction.id, ToolCall.user_turn == user_turn)
        .order_by(ToolCall.id)
    ).all()

    return {
        "user_turn": user_turn,
        "latency_ms": latency_ms,
        "tool_calls": [
            {
                "name": row.name,
                "args": row.args,
                "result": row.result,
                "ok": row.ok,
                "latency_ms": row.latency_ms,
            }
            for row in calls
        ],
        "steps": [
            {
                "ok": step.ok,
                "stop_reason": step.stop_reason,
                "model": step.model,
                "request_id": step.request_id,
                "latency_ms": step.latency_ms,
                "error": step.error,
            }
            for step in steps
        ],
        "confirmations": _confirmations(session, now=now),
        "resolved": _resolved(session),
        "tokens": _tokens(session, user_turn),
        "missing": [
            "thinking blocks (in session.messages; not surfaced by choice)",
            "which step a tool call belongs to (tool_calls records user_turn, not step)",
        ],
    }


def _confirmations(session: AgentSession, *, now: datetime) -> list[dict[str, Any]]:
    """Every token this conversation has produced, live or spent.

    `state` is computed, not stored, and follows redeem's own order: used
    beats expired, and expiry is inclusive of the instant. A token voided by
    a turn that never delivered its summary reads here as `expired`, because
    voiding *is* moving the expiry — the row keeps no separate mark, which is
    the limitation recorded in STATUS.md taxonomy 15.
    """
    rows = session.db.scalars(
        select(Confirmation)
        .where(Confirmation.interaction_id == session.interaction.id)
        .order_by(Confirmation.prepared_at_user_turn)
    ).all()
    return [
        {
            "id": str(row.id),
            "action": row.action.value,
            "prepared_at_user_turn": row.prepared_at_user_turn,
            "expires_at": row.expires_at.isoformat(),
            "used_at": row.used_at.isoformat() if row.used_at else None,
            "params_hash": row.params_hash,
            "state": (
                "used"
                if row.used_at is not None
                else "expired"
                if now >= row.expires_at
                else "live"
            ),
        }
        for row in rows
    ]


def _resolved(session: AgentSession) -> list[dict[str, Any]]:
    return [
        {
            "when_id": when_id,
            "starts_at": when.start.isoformat(),
            "ends_at": when.end.isoformat(),
            "gregorian_text": when.gregorian_text,
            "hijri_text": when.hijri_text,
        }
        for when_id, when in session.resolved.items()
    ]


def _tokens(session: AgentSession, user_turn: int) -> dict[str, int]:
    calls = session.usage_for_turn(user_turn)
    return {
        "calls": len(calls),
        "input": sum(call.input_tokens for call in calls),
        "output": sum(call.output_tokens for call in calls),
        "cache_write": sum(call.cache_creation_input_tokens for call in calls),
        "cache_read": sum(call.cache_read_input_tokens for call in calls),
    }
