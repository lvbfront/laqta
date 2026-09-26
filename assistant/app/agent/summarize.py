"""The end-of-session summary (spec §12).

Two or three lines and an outcome label, written by a cheaper model and
stored on the interaction. This is what appears as "آخر تواصل" in the
context block the next time the same customer calls.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.agent.session import AgentSession
from app.config import SUMMARY_MAX_TOKENS, settings

OUTCOMES = ("booked", "rescheduled", "cancelled", "answered", "handed_off", "abandoned")

SUMMARY_SYSTEM = """
You summarise a finished conversation between a Saudi event-photo platform's
assistant and an event organizer.

Write two or three short lines in Saudi Arabic, in the third person, saying
what the customer wanted and what actually happened — including anything left
unfinished. Name the event if it was named. Do not add advice, do not add
facts that are not in the transcript, and do not invent a next step.

Then pick the single outcome label that fits best:
booked, rescheduled, cancelled, answered, handed_off, abandoned.
""".strip()


class SessionSummary(BaseModel):
    summary_ar: str = Field(description="Two or three lines of Saudi Arabic.")
    outcome: Literal["booked", "rescheduled", "cancelled", "answered", "handed_off", "abandoned"]


def summarize_session(
    session: AgentSession, *, now: datetime, client: Any | None = None
) -> SessionSummary | None:
    """Summarise, store, and close the interaction. Returns None when there
    was nothing to summarise (a session where nobody said anything)."""
    transcript = readable_transcript(session)
    if not transcript:
        session.end(now=now, outcome="abandoned")
        return None

    api = client if client is not None else _default_client()
    response = api.messages.parse(
        model=settings.summary_model,
        max_tokens=SUMMARY_MAX_TOKENS,
        system=SUMMARY_SYSTEM,
        messages=[{"role": "user", "content": transcript}],
        output_format=SessionSummary,
    )
    summary = response.parsed_output

    session.end(now=now, outcome=summary.outcome, summary=summary.summary_ar)
    return summary


def readable_transcript(session: AgentSession) -> str:
    """Just what was said. Tool calls are already in tool_calls, and feeding
    them to the summariser invites it to describe plumbing instead of the
    conversation."""
    lines = []
    for message in session.messages:
        content = message["content"]
        if isinstance(content, str):
            lines.append(f"العميل: {content}")
            continue
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text" and block.get("text"):
                speaker = "المساعد" if message["role"] == "assistant" else "العميل"
                lines.append(f"{speaker}: {block['text']}")
    return "\n".join(lines).strip()


def _default_client() -> Any:
    from app.agent.loop import default_client

    return default_client()
