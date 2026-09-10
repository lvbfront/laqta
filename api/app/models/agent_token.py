from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.base import TimestampMixin, UUIDPKMixin

if TYPE_CHECKING:
    from app.models.event import Event


class AgentToken(Base, UUIDPKMixin, TimestampMixin):
    """A long-lived credential for the desktop watch-folder agent
    (agent/), scoped to exactly one event -- issued once by redeeming an
    AgentPairingCode (app/api/routes/agent.py's pair_agent), then stored
    in the OS keychain on the photographer's machine and never shown to a
    human again. No expiry by design (an event can run for days and the
    agent must keep working without the photographer re-pairing); only
    ends via revoked_at, same revocation-by-timestamp pattern as
    EventFtpCredential.

    device_label is whatever the agent reported at pairing time (e.g. its
    hostname) purely so the dashboard's agent list is legible when more
    than one laptop is paired to the same event.

    token_hash is SHA-256, not bcrypt, on purpose: bcrypt is salted and
    non-deterministic specifically to defend a low-entropy human-chosen
    password against precomputation/dictionary attacks -- but this token
    is 256 bits of secrets.token_urlsafe output, already unguessable, and
    every request needs an indexed equality lookup to even find which
    row to check (unlike a password, there's no separate username to
    look up by first). A fast deterministic hash is the correct tool
    here, same reasoning as any bearer-API-key scheme.
    """

    __tablename__ = "agent_tokens"

    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("events.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    device_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    event: Mapped["Event"] = relationship()

    def __repr__(self) -> str:  # pragma: no cover
        return f"<AgentToken {self.id} event_id={self.event_id} device={self.device_label!r}>"
