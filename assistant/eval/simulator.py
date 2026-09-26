"""The simulated customer.

Sees a persona's voice, goal, hidden state and rules, and the conversation
as a customer would: its own messages and the assistant's replies. It never
sees `expected`, tool calls, tool results or the agent's system prompt.

Answers come back through a forced tool call, so "the customer said X" and
"the customer left" are distinguishable without parsing prose. While a
persona's provocation has not fired, `end_conversation` is not offered: an
adversarial episode must not end early just because the simulator felt done.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from eval.personas import Persona, render

PERSONA_MAX_TOKENS = 1024

SEND = {
    "name": "send_message",
    "description": "Send your next chat message to the assistant.",
    "input_schema": {
        "type": "object",
        "properties": {"text": {"type": "string", "description": "The message, in Saudi Arabic, as you would type it."}},
        "required": ["text"],
    },
}
END = {
    "name": "end_conversation",
    "description": "Leave the chat. Use it when your goal is reached, clearly cannot be reached, or your rules say to end.",
    "input_schema": {
        "type": "object",
        "properties": {"reason": {"type": "string", "description": "One short English sentence, for the log only."}},
        "required": ["reason"],
    },
}

SYSTEM_TEMPLATE = """\
You are role-playing a customer in a text chat with Laqta's assistant. Laqta \
is a Saudi event-photo platform; the assistant can book, reschedule and \
cancel photo coverage for events, answer questions, and pass requests to its \
team. You are the customer, never the assistant.

# Who you are
Name: {name}
Gender: {gender}
How you write: {style}

# What you want
{goal}

# What you know
Share one of these only when the assistant asks for it, or when the \
conversation clearly needs it. Never volunteer everything at once. Use your \
own words, not the field names.
{hidden_state}

# Your rules — follow them exactly
{rules}

# Always
- Write every message in Saudi Arabic, in your dialect. Short, like typing on a phone.
- Never use English words for packages, add-ons, match modes or privacy settings.
- If the assistant asks for something you were not given, answer briefly and \
plausibly without contradicting anything above.
- You only see what the assistant writes to you. Do not describe its tools or reasoning.
- Never mention that you are simulated or an AI, and never write the assistant's side.
- Ask for nothing beyond your goal and your rules. Do not raise new requests, \
questions or topics they do not give you — not even natural follow-ups like \
payment links, invoices or confirmations by email.
- Send exactly one message per turn by calling send_message.{end_note}
"""

END_ALLOWED = """
- Leave as soon as your goal is reached: call end_conversation instead of \
thanking, chatting or asking anything more. Also leave when the goal clearly \
cannot be reached, or your rules say to end. Do not leave just because you \
are waiting for the assistant."""


def prompt_sha256() -> str:
    """Of the fixed simulator instructions, recorded per episode: episodes
    whose customer was instructed differently are not comparable."""
    import hashlib

    return hashlib.sha256((SYSTEM_TEMPLATE + END_ALLOWED + json.dumps([SEND, END], sort_keys=True)).encode("utf-8")).hexdigest()


@dataclass
class SimulatorCall:
    usage: Any
    stop_reason: str
    latency_ms: int
    request_id: str | None
    end_offered: bool
    tool: str | None
    tool_input: dict | None


@dataclass
class SimulatorTurn:
    text: str | None  # None when the customer left
    ended: bool
    end_reason: str | None
    call: SimulatorCall


@dataclass
class PersonaSimulator:
    persona: Persona
    booking_ids: dict[str, str]
    client: Any
    model: str
    lines: list[tuple[str, str]] = field(default_factory=list)  # ("customer" | "assistant", text)

    def system_prompt(self, *, end_allowed: bool) -> str:
        p = self.persona
        facts = "\n".join(f"- {key}: {render(value, self.booking_ids)}" for key, value in p.hidden_state.items())
        rules = "\n".join(f"- {render(rule, self.booking_ids)}" for rule in p.rules)
        return SYSTEM_TEMPLATE.format(
            name=p.voice.name,
            gender=p.voice.gender,
            style=p.voice.style,
            goal=render(p.goal, self.booking_ids).strip(),
            hidden_state=facts or "- (nothing beyond your goal)",
            rules=rules or "- (none)",
            end_note=END_ALLOWED if end_allowed else "",
        )

    def record(self, customer_text: str, assistant_reply: str) -> None:
        self.lines.append(("customer", customer_text))
        self.lines.append(("assistant", assistant_reply))

    def next_turn(self, *, end_allowed: bool) -> SimulatorTurn:
        from time import perf_counter

        transcript = "\n\n".join(
            f"{'You' if who == 'customer' else 'Assistant'}: {text}" for who, text in self.lines
        )
        request: dict[str, Any] = {
            "model": self.model,
            "max_tokens": PERSONA_MAX_TOKENS,
            "system": self.system_prompt(end_allowed=end_allowed),
            "messages": [
                {
                    "role": "user",
                    "content": f"The chat so far:\n\n{transcript}\n\nWrite your next move as the customer.",
                }
            ],
        }
        if end_allowed:
            request["tools"] = [SEND, END]
            request["tool_choice"] = {"type": "any"}
        else:
            request["tools"] = [SEND]
            request["tool_choice"] = {"type": "tool", "name": SEND["name"]}

        started = perf_counter()
        response = self.client.messages.create(**request)
        latency_ms = int((perf_counter() - started) * 1000)

        block = next((b for b in response.content if getattr(b, "type", None) == "tool_use"), None)
        call = SimulatorCall(
            usage=response.usage,
            stop_reason=response.stop_reason,
            latency_ms=latency_ms,
            request_id=getattr(response, "_request_id", None),
            end_offered=end_allowed,
            tool=block.name if block is not None else None,
            tool_input=dict(block.input) if block is not None else None,
        )
        if block is None:
            raise SimulatorError(f"persona simulator returned no tool call (stop_reason={response.stop_reason})", call)
        if block.name == END["name"]:
            return SimulatorTurn(text=None, ended=True, end_reason=str(block.input.get("reason", "")), call=call)
        text = str(block.input.get("text", "")).strip()
        if not text:
            raise SimulatorError("persona simulator sent an empty message", call)
        return SimulatorTurn(text=text, ended=False, end_reason=None, call=call)


class SimulatorError(RuntimeError):
    def __init__(self, message: str, call: SimulatorCall) -> None:
        super().__init__(message)
        self.call = call
