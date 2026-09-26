"""Tool registration, role enforcement, execution and logging (spec §10).

Two layers of permission, as §4 requires:
  1. schemas_for() only sends a role the tools it may use, so the model
     never sees the rest;
  2. execute() checks the role again, because a model can name a tool it was
     never given.

Every call is logged to tool_calls with its latency, arguments and result —
the raw material for layer 2's evals.
"""

from __future__ import annotations

import inspect
import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from time import perf_counter
from typing import Any, Callable, get_type_hints

from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from app.config import Policy
from app.assistant_domain.dates.intents import ResolvedWhen
from app.identity.identity import Identity
from app.laqta.adapter import LaqtaAdapter
from app.models import ToolCall

ROLES = frozenset({"anonymous", "customer", "staff"})


@dataclass
class ToolContext:
    """Everything a tool may touch. `now` is supplied by the caller so the
    whole tool layer stays testable against a fake clock."""

    db: Session
    identity: Identity
    interaction_id: int
    policy: Policy
    laqta: LaqtaAdapter
    now: datetime
    user_turn: int = 0
    # when_id -> resolved window (spec §7). Booking tools take a when_id and
    # never a date, so every date they act on has been through the resolver.
    resolved: dict[str, ResolvedWhen] = field(default_factory=dict)


def ok(**data: Any) -> dict:
    return {"ok": True, "data": data}


def fail(error: str, detail: str | None = None, **extra: Any) -> dict:
    """A business refusal: ordinary data the model is expected to handle,
    never an error (spec §10)."""
    payload: dict[str, Any] = {"ok": False, "error": error}
    if detail is not None:
        payload["detail"] = detail
    payload.update(extra)
    return payload


def crashed(detail: str) -> dict:
    """A real fault — the only thing that becomes is_error: true."""
    return {"ok": False, "error": "internal_error", "detail": detail, "_exception": True}


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    roles: frozenset[str]
    input_model: type[BaseModel]
    fn: Callable[[ToolContext, BaseModel], dict]
    side_effects: bool


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def tool(
        self,
        *,
        name: str,
        roles: Iterable[str],
        description: str,
        side_effects: bool = False,
    ):
        """Register a `(ctx, inp) -> dict` function. The input schema is read
        off the second parameter's annotation."""

        def decorator(fn: Callable[..., dict]) -> Callable[..., dict]:
            params = list(inspect.signature(fn).parameters)
            if len(params) != 2:
                raise TypeError(f"tool {name!r} must take exactly (ctx, inp)")
            hints = get_type_hints(fn)
            if params[1] not in hints:
                raise TypeError(
                    f"tool {name!r} must annotate its input parameter with a pydantic model — "
                    "the schema sent to the model is read from that annotation"
                )
            input_model = hints[params[1]]
            if not (isinstance(input_model, type) and issubclass(input_model, BaseModel)):
                raise TypeError(f"tool {name!r}'s input must be a pydantic model")

            unknown = set(roles) - ROLES
            if unknown:
                raise ValueError(f"tool {name!r} names unknown roles: {sorted(unknown)}")
            if name in self._tools:
                raise ValueError(f"tool {name!r} is already registered")

            self._tools[name] = Tool(
                name=name,
                description=inspect.cleandoc(description),
                roles=frozenset(roles),
                input_model=input_model,
                fn=fn,
                side_effects=side_effects,
            )
            return fn

        return decorator

    def all_tools(self) -> tuple[Tool, ...]:
        return tuple(self._tools[name] for name in sorted(self._tools))

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def schemas_for(self, identity: Identity) -> list[dict]:
        """The Anthropic tool list for this role, and nothing more."""
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.input_model.model_json_schema(),
            }
            for tool in self.all_tools()
            if identity.kind in tool.roles
        ]

    def execute(self, name: str, raw_input: dict, *, ctx: ToolContext) -> dict:
        """Run one tool call. Owns the transaction: a successful call commits
        (so confirm_action's booking and its Laqta event land together), a
        crash rolls back, and either way the call is logged."""
        started = perf_counter()

        tool = self._tools.get(name)
        if tool is None:
            return self._log(ctx, name, raw_input, started, fail("unknown_tool", f"لا توجد أداة باسم {name}"))

        if ctx.identity.kind not in tool.roles:
            return self._log(
                ctx, name, raw_input, started,
                fail("forbidden", "هذي الأداة غير متاحة لك."),
            )

        try:
            inp = tool.input_model.model_validate(raw_input)
        except ValidationError as exc:
            # Handed back as data so the model can correct itself (spec §10).
            return self._log(
                ctx, name, raw_input, started,
                fail("invalid_input", "المدخلات ناقصة أو غير صحيحة.", fields=_field_errors(exc)),
            )

        try:
            # A savepoint, not the whole transaction: a crashing tool must
            # undo its own writes and nothing else. A plain rollback() here
            # would also discard the caller's work — including the
            # interaction row this crash is about to be logged against.
            with ctx.db.begin_nested():
                result = tool.fn(ctx, inp)
            ctx.db.commit()
        except Exception as exc:  # noqa: BLE001 — becomes is_error: true
            result = crashed(f"{type(exc).__name__}: {exc}")

        return self._log(ctx, name, raw_input, started, result)

    def _log(self, ctx: ToolContext, name: str, raw_input: dict, started: float, result: dict) -> dict:
        ctx.db.add(
            ToolCall(
                interaction_id=ctx.interaction_id,
                user_turn=ctx.user_turn,
                name=name,
                args=_jsonable(raw_input),
                result=_jsonable(result),
                ok=bool(result.get("ok")),
                latency_ms=int((perf_counter() - started) * 1000),
            )
        )
        ctx.db.commit()
        return result


def _field_errors(exc: ValidationError) -> list[dict]:
    return [
        {"field": ".".join(str(part) for part in error["loc"]), "problem": error["msg"]}
        for error in exc.errors()
    ]


def _jsonable(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


registry = ToolRegistry()
