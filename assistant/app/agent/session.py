"""One conversation's state (spec §12).

Holds the message history, the customer-message counter the mandatory
confirmation depends on, and the resolved-date store that lets booking tools
take a `when_id` instead of a date.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.agent.context import build_context_block
from app.assistant_domain.dates.intents import ResolvedWhen
from app.config import Policy
from app.identity.identity import Identity
from app.laqta.adapter import LaqtaAdapter
from app.models.enums import Channel, IdentityKind
from app.models.interaction import Interaction
from app.tools.registry import ToolContext


@dataclass(frozen=True)
class TokenUsage:
    """One API response's `usage`, or a sum of several.

    `input_tokens` is only the uncached part of the prompt. A cache that is
    configured but never read shows up as cache_read_input_tokens staying 0
    while cache_creation_input_tokens is paid again on every call.
    """

    user_turn: int
    call: int  # 1-based within the turn; 0 on a total
    input_tokens: int
    output_tokens: int
    cache_creation_input_tokens: int
    cache_read_input_tokens: int

    @classmethod
    def total(cls, calls: list[TokenUsage]) -> TokenUsage:
        return cls(
            user_turn=calls[0].user_turn if calls else 0,
            call=0,
            input_tokens=sum(c.input_tokens for c in calls),
            output_tokens=sum(c.output_tokens for c in calls),
            cache_creation_input_tokens=sum(c.cache_creation_input_tokens for c in calls),
            cache_read_input_tokens=sum(c.cache_read_input_tokens for c in calls),
        )

    def describe(self) -> str:
        return (
            f"in={self.input_tokens} out={self.output_tokens} "
            f"cache_write={self.cache_creation_input_tokens} "
            f"cache_read={self.cache_read_input_tokens}"
        )


@dataclass
class AgentSession:
    db: Session
    identity: Identity
    policy: Policy
    laqta: LaqtaAdapter
    interaction: Interaction
    context_block: str

    messages: list[dict[str, Any]] = field(default_factory=list)

    # How many messages the *customer* has sent. confirm_action compares this
    # against the turn a confirmation was prepared on, which is what stops the
    # model confirming its own summary (spec §8).
    user_turn: int = 0

    # when_id -> resolved window. One dict for the whole session: a when_id
    # handed out on turn 2 is still valid on turn 5.
    resolved: dict[str, ResolvedWhen] = field(default_factory=dict)

    # Every API call's token usage, in order. In memory only: it is for
    # /debug and for the eval's per-episode cost, not for the CRM.
    usage: list[TokenUsage] = field(default_factory=list)

    @classmethod
    def start(
        cls,
        db: Session,
        *,
        identity: Identity,
        policy: Policy,
        laqta: LaqtaAdapter,
        now: datetime,
        channel: Channel = Channel.chat,
    ) -> AgentSession:
        interaction = Interaction(
            contact_id=identity.contact_id,
            staff_id=identity.staff_id,
            channel=channel,
            identity_kind=IdentityKind(identity.kind),
            started_at=now,
        )
        db.add(interaction)
        db.commit()

        return cls(
            db=db,
            identity=identity,
            policy=policy,
            laqta=laqta,
            interaction=interaction,
            # Built once: it is the volatile half of the system prompt, and
            # rebuilding it mid-conversation would throw away the cached
            # prefix on every turn.
            context_block=build_context_block(db, identity, now=now, policy=policy),
        )

    def tool_ctx(self, *, now: datetime) -> ToolContext:
        return ToolContext(
            db=self.db,
            identity=self.identity,
            interaction_id=self.interaction.id,
            policy=self.policy,
            laqta=self.laqta,
            now=now,
            user_turn=self.user_turn,
            resolved=self.resolved,
        )

    def add_user_message(self, text: str) -> None:
        self.user_turn += 1
        self.messages.append({"role": "user", "content": text})

    def add_assistant_content(self, content: list[Any]) -> None:
        """Stored as wire-shaped dicts rather than SDK objects, so the history
        is one representation that round-trips through JSONB and back into a
        request. exclude_none drops the nulls the SDK fills in; thinking
        blocks keep their signature, which they need to be echoed back."""
        self.messages.append(
            {
                "role": "assistant",
                "content": [
                    block.model_dump(mode="json", exclude_none=True)
                    if hasattr(block, "model_dump")
                    else block
                    for block in content
                ],
            }
        )

    def record_usage(self, usage: Any) -> TokenUsage:
        """From a response's `usage`. The SDK types the two cache fields as
        optional, so None counts as 0."""
        record = TokenUsage(
            user_turn=self.user_turn,
            call=len(self.usage_for_turn(self.user_turn)) + 1,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_creation_input_tokens=usage.cache_creation_input_tokens or 0,
            cache_read_input_tokens=usage.cache_read_input_tokens or 0,
        )
        self.usage.append(record)
        return record

    def usage_for_turn(self, user_turn: int) -> list[TokenUsage]:
        return [u for u in self.usage if u.user_turn == user_turn]

    def add_tool_results(self, results: list[dict[str, Any]]) -> None:
        # One user message carrying every result: splitting them teaches the
        # model to stop calling tools in parallel.
        self.messages.append({"role": "user", "content": results})

    def save_transcript(self) -> None:
        """After every turn, so an interrupted conversation is still on record."""
        self.interaction.transcript = json.loads(
            json.dumps(self.messages, ensure_ascii=False, default=str)
        )
        self.db.commit()

    def end(self, *, now: datetime, outcome: str | None = None, summary: str | None = None) -> None:
        self.interaction.ended_at = now
        if outcome is not None:
            self.interaction.outcome = outcome
        if summary is not None:
            self.interaction.summary = summary
        self.save_transcript()
