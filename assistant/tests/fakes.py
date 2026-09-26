"""A scripted stand-in for the Anthropic client.

The agent tests drive the loop with canned responses: no network, no key, no
cost. Only the parts of the SDK's shapes the loop actually touches are
modelled — content blocks with a `type`, `stop_reason`, and `model_dump`,
which is how the session stores assistant turns.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any


@dataclass
class FakeText:
    text: str
    type: str = "text"

    def model_dump(self, **_kwargs) -> dict:
        return {"type": "text", "text": self.text}


@dataclass
class FakeToolUse:
    name: str
    input: dict
    id: str = "toolu_fake"
    type: str = "tool_use"

    def model_dump(self, **_kwargs) -> dict:
        return {"type": "tool_use", "id": self.id, "name": self.name, "input": self.input}


@dataclass
class FakeThinking:
    thinking: str = ""
    signature: str = "sig"
    type: str = "thinking"

    def model_dump(self, **_kwargs) -> dict:
        return {"type": "thinking", "thinking": self.thinking, "signature": self.signature}


def fake_usage(
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_creation_input_tokens: int | None = None,
    cache_read_input_tokens: int | None = None,
) -> SimpleNamespace:
    """The SDK's Usage shape. The cache fields default to None because the
    SDK types them as optional."""
    return SimpleNamespace(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_creation_input_tokens=cache_creation_input_tokens,
        cache_read_input_tokens=cache_read_input_tokens,
    )


@dataclass
class FakeResponse:
    content: list[Any]
    stop_reason: str = "end_turn"
    usage: Any = field(default_factory=fake_usage)


def says(text: str) -> FakeResponse:
    return FakeResponse([FakeText(text)])


def calls_tool(name: str, tool_input: dict, *, block_id: str = "toolu_fake") -> FakeResponse:
    return FakeResponse([FakeToolUse(name=name, input=tool_input, id=block_id)], "tool_use")


def transient_api_error() -> BaseException:
    """A real SDK error, so the loop's classification is tested against the
    actual hierarchy rather than a look-alike that would pass either way."""
    import anthropic
    import httpx2

    return anthropic.APIConnectionError(
        request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    )


def auth_api_error() -> BaseException:
    """A missing or wrong key. Must NOT be absorbed by the loop."""
    import anthropic
    import httpx2

    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    return anthropic.AuthenticationError(
        "invalid x-api-key",
        response=httpx2.Response(401, request=request),
        body=None,
    )


@dataclass
class FakeMessages:
    responses: list[FakeResponse] = field(default_factory=list)
    calls: list[dict] = field(default_factory=list)
    raises: BaseException | None = None
    parsed: Any = None
    parse_calls: list[dict] = field(default_factory=list)

    def create(self, **kwargs) -> FakeResponse:
        # Deep-copied, not stored by reference: `messages` is the session's
        # own live list, so recording it as-is would mean every "what did we
        # send on turn N" assertion actually inspected the final state of the
        # conversation and passed or failed for the wrong reason.
        self.calls.append(deepcopy(kwargs))
        if self.raises is not None:
            raise self.raises
        if not self.responses:
            raise AssertionError("the loop asked for more turns than were scripted")
        return self.responses.pop(0)

    def parse(self, **kwargs):
        self.parse_calls.append(deepcopy(kwargs))
        if self.raises is not None:
            raise self.raises
        return SimpleNamespace(parsed_output=self.parsed)


class FakeClient:
    def __init__(
        self,
        *responses: FakeResponse,
        raises: BaseException | None = None,
        parsed: Any = None,
    ) -> None:
        self.messages = FakeMessages(list(responses), raises=raises, parsed=parsed)

    @property
    def calls(self) -> list[dict]:
        return self.messages.calls

    def tool_names_offered(self, call_index: int = 0) -> set[str]:
        return {tool["name"] for tool in self.calls[call_index]["tools"]}
