"""The agent loop (spec §12).

Written by hand rather than with the SDK's tool runner because three things
here are ours, not the SDK's: the second role check on every tool call, the
tool_calls log, and the customer-message counter the mandatory confirmation
depends on.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from typing import Any

from app.agent.session import AgentSession, TokenUsage
from app.assistant_domain import confirmation as confirmations
from app.config import AGENT_MAX_STEPS, AGENT_MAX_TOKENS, SYSTEM_PROMPT_PATH, settings
from app.models.enums import TicketReason
from app.tools import registry

FALLBACK_MESSAGE = "عذراً، خلني أحوّلك لأحد من الفريق يكمل معك."
REFUSAL_MESSAGE = "ما أقدر أساعد في هذا الطلب. تحب أحوّلك لأحد من الفريق؟"
TRUNCATED_NOTE = "…"
API_ERROR_MESSAGE = "صار عندي خلل تقني بسيط. تقدر تعيد آخر رسالة؟"

usage_log = logging.getLogger("app.agent.usage")
log = logging.getLogger("app.agent.loop")

# Notes for whoever edits the prompt, not for the model.
_AUTHOR_COMMENT = re.compile(r"<!--.*?-->\n?", re.DOTALL)


@lru_cache(maxsize=1)
def system_prompt() -> str:
    """Read once. It is the cached half of the system prompt, so it has to be
    byte-identical on every request or the cache never hits. HTML comments
    are stripped: they explain the prompt to its editors and cost tokens
    without telling the model anything."""
    return _AUTHOR_COMMENT.sub("", SYSTEM_PROMPT_PATH.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def default_client() -> Any:
    import anthropic  # local import: the CLI should start without the SDK loaded

    return anthropic.Anthropic()


@dataclass(frozen=True)
class _Turn:
    """How a turn ended.

    `delivered` is true only for a complete model reply. Everything else —
    the canned messages, a reply cut off at max_tokens, an exception — means
    the customer was handed something other than what the model was in the
    middle of saying, so anything prepare_* produced this turn did not reach
    them.
    """

    reply: str
    delivered: bool


def run_turn(
    session: AgentSession,
    user_text: str,
    *,
    now: datetime,
    client: Any | None = None,
    on_event: Callable[[str], None] | None = None,
) -> str:
    """One customer message in, one reply out. Tool calls happen in between."""
    api = client if client is not None else default_client()
    session.add_user_message(user_text)

    delivered = False
    already_failing = False
    try:
        try:
            turn = _steps(session, now=now, api=api, on_event=on_event)
        except Exception as exc:  # noqa: BLE001 — narrowed immediately below
            if not isinstance(exc, transient_error_types()):
                raise
            _note(on_event, f"transient api error: {type(exc).__name__}: {exc}")
            turn = _Turn(API_ERROR_MESSAGE, delivered=False)
        delivered = turn.delivered
    except BaseException:
        already_failing = True
        raise
    finally:
        # Also on failure: the calls that did complete were billed.
        _note_turn_usage(session, on_event)
        if not delivered:
            _void_this_turns_confirmations(
                session, now=now, on_event=on_event, already_failing=already_failing
            )

    session.save_transcript()
    return turn.reply


def _steps(
    session: AgentSession,
    *,
    now: datetime,
    api: Any,
    on_event: Callable[[str], None] | None,
) -> _Turn:
    for _ in range(AGENT_MAX_STEPS):
        response = api.messages.create(
            model=settings.agent_model,
            max_tokens=AGENT_MAX_TOKENS,
            # Adaptive is the only on-mode on Sonnet 5; budget_tokens and
            # temperature are rejected outright.
            thinking={"type": "adaptive"},
            system=[
                # Stable half, cached. Everything volatile goes after it.
                {
                    "type": "text",
                    "text": system_prompt(),
                    "cache_control": {"type": "ephemeral"},
                },
                {"type": "text", "text": session.context_block},
            ],
            tools=registry.schemas_for(session.identity),
            messages=session.messages,
        )

        session.add_assistant_content(response.content)
        usage = session.record_usage(response.usage)
        usage_log.info("turn %d call %d: %s", usage.user_turn, usage.call, usage.describe())
        _note(on_event, f"stop_reason: {response.stop_reason}")
        _note(on_event, f"tokens: {usage.describe()}")

        if response.stop_reason == "refusal":
            return _Turn(REFUSAL_MESSAGE, delivered=False)

        if response.stop_reason != "tool_use":
            text = _text_of(response.content)
            if response.stop_reason == "max_tokens":
                # Truncated mid-sentence: better to say so than to present
                # half a booking summary as if it were complete.
                if text:
                    return _Turn(text + TRUNCATED_NOTE, delivered=False)
                return _Turn(FALLBACK_MESSAGE, delivered=False)
            if text:
                return _Turn(text, delivered=True)
            return _Turn(FALLBACK_MESSAGE, delivered=False)

        # Every tool_use block has to be answered before the next request,
        # and the answers have to be attached even if something in here
        # throws: a tool_use left without its tool_result is a malformed
        # conversation, and the session would then fail on every later turn
        # rather than just this one. registry.execute does not raise (a
        # crashing tool comes back as data), but its own bookkeeping commit
        # can, and that is outside the savepoint.
        calls = [block for block in response.content if block.type == "tool_use"]
        results: list[dict[str, Any]] = []
        try:
            for block in calls:
                out = registry.execute(block.name, block.input, ctx=session.tool_ctx(now=now))
                _note(on_event, f"{block.name}({json.dumps(block.input, ensure_ascii=False)}) -> {json.dumps(out, ensure_ascii=False, default=str)}")
                results.append(_tool_result(block.id, out))
        except BaseException as exc:
            cause = f"{type(exc).__name__}: {exc}"
            _note(on_event, f"tool step failed: {cause}")
            # The call that was running when this hit is not in the same
            # position as the ones queued behind it, and the difference is
            # the only thing the model can act on. results holds one entry
            # per completed call, so calls[len(results)] is the interrupted
            # one and everything after it never started.
            if len(results) < len(calls):
                block = calls[len(results)]
                results.append(_tool_result(block.id, _interrupted(block.name, cause)))
            for block in calls[len(results) :]:
                results.append(_tool_result(block.id, _never_ran(cause)))
            raise
        finally:
            session.add_tool_results(results)

    # Out of steps. Hand to a human through the tool, so the ticket is routed
    # and logged like any other handoff rather than written behind its back.
    _note(on_event, f"hit AGENT_MAX_STEPS={AGENT_MAX_STEPS}, handing off")
    registry.execute(
        "handoff_to_staff",
        {
            "reason_code": TicketReason.wants_human.value,
            "summary": "المساعد دار في حلقة أدوات بدون ما يوصل لجواب، والمحادثة تحتاج موظف.",
        },
        ctx=session.tool_ctx(now=now),
    )
    return _Turn(FALLBACK_MESSAGE, delivered=False)


# Written to the model, not to the customer, and in the same English as the
# registry's own crashed() detail. These say what to do next, and the system
# prompt — the only other place that could — cannot know which call it was.
#
# What to do next depends on the tool, not on who is speaking. A tool with no
# side effects can simply be called again. A side-effecting one cannot, and
# then the question is whether anything can check what happened, which is
# only true for confirm_action.
INTERRUPTED_HARMLESS = (
    "This call was interrupted before it returned. It changes nothing a customer "
    "can see, and any draft it wrote has been discarded. Call it again."
)
INTERRUPTED_CHECK_FIRST = (
    "This call started and was then interrupted, so whether it took effect is "
    "unknown — the booking may exist. Do not call confirm_action again, and do not "
    "tell the customer it failed. Call get_my_bookings first and say what you "
    "actually find."
)
INTERRUPTED_UNCHECKABLE = (
    "This call started and was then interrupted, so whether it took effect is "
    "unknown, and no tool can check. Do not tell the customer it failed. If they "
    "still need a person, call it once more: a duplicate ticket can be closed, a "
    "request that was never recorded leaves them waiting for nobody."
)
NEVER_RAN_DETAIL = (
    "Not run. Another call in the same step was interrupted before this one started, "
    "so nothing it would have done has happened. It is safe to call again."
)


def _interrupted_detail(name: str) -> str:
    tool = registry.get(name)
    if tool is None or not tool.side_effects:
        return INTERRUPTED_HARMLESS
    if name == "confirm_action":
        return INTERRUPTED_CHECK_FIRST
    # handoff_to_staff today, and the cautious default for anything added
    # later: naming a tool the speaker may not have would be worse than
    # naming none, and only a customer has get_my_bookings.
    return INTERRUPTED_UNCHECKABLE


def _interrupted(name: str, cause: str) -> dict[str, Any]:
    """A call that was in flight. Its side effects do not all roll back with
    the database — MockLaqta is in memory and keeps what it was given, and the
    real Laqta will be an HTTP call that cannot be taken back at all — so "it
    failed" would be a claim we cannot make."""
    return {
        "ok": False,
        "error": "interrupted",
        "detail": _interrupted_detail(name),
        "cause": cause,
        "_exception": True,
    }


def _never_ran(cause: str) -> dict[str, Any]:
    """A call still queued behind the interrupted one. This one we can be
    definite about."""
    return {"ok": False, "error": "not_run", "detail": NEVER_RAN_DETAIL, "cause": cause, "_exception": True}


def _tool_result(tool_use_id: str, out: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "tool_result",
        "tool_use_id": tool_use_id,
        "content": json.dumps(out, ensure_ascii=False, default=str),
        # Only a real fault is an error; a business refusal is data.
        "is_error": bool(out.get("_exception", False)),
    }


def _void_this_turns_confirmations(
    session: AgentSession,
    *,
    now: datetime,
    on_event: Callable[[str], None] | None,
    already_failing: bool,
) -> None:
    """The turn ended without a reply, so any token it prepared is dead.

    See confirmations.void_prepared_at_turn for why. This runs in a finally,
    so it has two callers in one: when an exception is already on its way out
    of run_turn, raising here would replace it with a less informative one and
    the caller is being told the turn failed regardless — so log and stand
    aside. On every other path the caller is about to be handed a reply and
    told the turn merely went badly, and a void that did not land is a live
    token the caller has no way to learn about. There the failure has to
    propagate: whatever the customer says next must not reach a summary they
    never saw, and refusing the whole session is the only answer left once
    the token cannot be killed.
    """
    try:
        voided = confirmations.void_prepared_at_turn(
            session.db,
            interaction_id=session.interaction.id,
            user_turn=session.user_turn,
            now=now,
        )
        if voided:
            session.db.commit()
            _note(on_event, f"voided {voided} confirmation(s) prepared on turn {session.user_turn}")
    except Exception as exc:  # noqa: BLE001 — see the docstring
        log.warning(
            "could not void confirmations prepared on turn %d of interaction %s: %s",
            session.user_turn,
            session.interaction.id,
            exc,
        )
        _note(on_event, f"could not void this turn's confirmations: {type(exc).__name__}: {exc}")
        if not already_failing:
            raise


def _note_turn_usage(session: AgentSession, on_event: Callable[[str], None] | None) -> None:
    calls = session.usage_for_turn(session.user_turn)
    if not calls:
        return
    total = TokenUsage.total(calls)
    _note(on_event, f"turn {session.user_turn} tokens ({len(calls)} calls): {total.describe()}")


def _text_of(content: list[Any]) -> str:
    return "".join(block.text for block in content if block.type == "text").strip()


def _note(on_event: Callable[[str], None] | None, message: str) -> None:
    if on_event is not None:
        on_event(message)


@lru_cache(maxsize=1)
def transient_error_types() -> tuple[type[BaseException], ...]:
    """The failures worth apologising for and letting the customer retry.

    Deliberately a short list rather than "anything from the SDK": a missing
    API key, a bad request or a wrong model id is a misconfiguration, and
    answering it with a polite Arabic apology would hide it from whoever can
    fix it. Those propagate.
    """
    import anthropic

    return (
        anthropic.APIConnectionError,  # APITimeoutError subclasses this
        anthropic.RateLimitError,
        anthropic.InternalServerError,
    )
