"""A thin wrapper round the model client, so the dev panel can show what the
loop does not return.

`run_turn` hands back a string. Per-step stop reasons, latencies and request
ids exist only inside it, and `on_event` reports them as already-formatted
prose. The eval has the same problem and solves it the same way, by passing
its own client in — `run_turn(client=...)` is a public parameter, so this
needs no change to app/.

Always on, because reply_source has to be exact even in production: a canned
loop message must never be shown as the model's words, and telling
FALLBACK_MESSAGE from a model that happened to say the same sentence needs
the stop reason. Only the detail is dev-gated, in events.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from time import perf_counter
from typing import Any


@dataclass
class Step:
    ok: bool
    stop_reason: str | None = None
    model: str | None = None
    request_id: str | None = None
    latency_ms: int = 0
    error: str | None = None


class RecordingClient:
    """Stands in for anthropic.Anthropic. The loop only uses messages.create."""

    def __init__(self, inner: Any) -> None:
        # Kept because the summariser calls messages.parse, which the loop
        # never does and this therefore does not wrap.
        self.inner = inner
        self.steps: list[Step] = []
        self.messages = _Messages(inner.messages, self.steps)

    def since(self, mark: int) -> list[Step]:
        return self.steps[mark:]

    @property
    def mark(self) -> int:
        return len(self.steps)


@dataclass
class _Messages:
    _inner: Any
    _steps: list[Step] = field(default_factory=list)

    def create(self, **kwargs: Any) -> Any:
        started = perf_counter()
        try:
            response = self._inner.create(**kwargs)
        except Exception as exc:
            self._steps.append(
                Step(ok=False, error=f"{type(exc).__name__}: {exc}", latency_ms=_ms(started))
            )
            raise
        self._steps.append(
            Step(
                ok=True,
                stop_reason=getattr(response, "stop_reason", None),
                model=getattr(response, "model", None),
                request_id=getattr(response, "_request_id", None),
                latency_ms=_ms(started),
            )
        )
        return response


def _ms(started: float) -> int:
    return int((perf_counter() - started) * 1000)
