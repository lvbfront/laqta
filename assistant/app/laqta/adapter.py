"""The only way the assistant talks to Laqta (spec §9).

Names and values mirror Laqta exactly — name_ar, match_mode, privacy_mode,
UUID ids — so the real v2 implementation is a thin HTTP layer.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class LaqtaUser:
    # Same fields as Laqta's GET /api/auth/me (UserPublic).
    id: uuid.UUID
    org_id: uuid.UUID
    email: str
    role: str


@dataclass(frozen=True)
class LaqtaEvent:
    id: uuid.UUID
    org_id: uuid.UUID
    name_ar: str
    starts_at: datetime
    ends_at: datetime
    match_mode: str  # face | code | sequential | both
    privacy_mode: str  # standard | strict
    status: str  # draft | active | closed


class LaqtaNotFound(Exception):
    pass


class LaqtaAdapter(Protocol):
    def get_user(self, user_id: uuid.UUID) -> LaqtaUser: ...

    def create_event(
        self,
        *,
        idempotency_key: str,
        org_id: uuid.UUID,
        name_ar: str,
        starts_at: datetime,
        ends_at: datetime,
        match_mode: str,
        privacy_mode: str,
    ) -> LaqtaEvent: ...

    def update_event_window(
        self, event_id: uuid.UUID, starts_at: datetime, ends_at: datetime
    ) -> LaqtaEvent: ...

    def cancel_event(self, event_id: uuid.UUID) -> None: ...

    def get_event(self, event_id: uuid.UUID) -> LaqtaEvent: ...
