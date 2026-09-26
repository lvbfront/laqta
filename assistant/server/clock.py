"""The one real-clock read in the service.

Everything under app/ takes `now` as a parameter — the domain is checked for
this by an AST test — precisely so the edge can decide what time it is. This
is that edge.

A dev override sets where the session *starts*, not a frozen instant. Freezing
would stop confirmation tokens ever expiring, so a demo of Hijri and relative
dates would quietly also be a demo with the ten-minute TTL switched off, and
the one guard most worth watching in a demo would be the one not running.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


def wall_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class Clock:
    """`started_at` is the session's notion of its first moment; `wall_start`
    is the real one. Time passes at the usual rate from there."""

    started_at: datetime
    wall_start: datetime

    @classmethod
    def real(cls) -> Clock:
        now = wall_now()
        return cls(started_at=now, wall_start=now)

    @classmethod
    def starting_at(cls, started_at: datetime) -> Clock:
        return cls(started_at=started_at, wall_start=wall_now())

    def now(self) -> datetime:
        return self.started_at + (wall_now() - self.wall_start)

    @property
    def overridden(self) -> bool:
        return self.started_at != self.wall_start
