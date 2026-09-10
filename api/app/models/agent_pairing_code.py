from __future__ import annotations

import secrets
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
    from app.models.user import User

# Excludes 0/O/1/I/L -- a photographer reads this off a screen and types
# it into a desktop app once; ambiguous characters are exactly what turns
# a 6-character code into a support request.
_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 6


def _generate_code() -> str:
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(CODE_LENGTH))


class AgentPairingCode(Base, UUIDPKMixin, TimestampMixin):
    """A short-lived, single-use code an organizer generates on the
    dashboard and reads aloud (or shows on screen) to a photographer at
    the desktop-agent's pairing screen -- the whole point is that the
    photographer never types a URL, port, username, or password, just
    this. Redeemed exactly once (app/api/routes/agent.py's pair_agent)
    for a long-lived AgentToken; the code itself is single-use and
    expires in AGENT_PAIRING_CODE_TTL_MINUTES regardless.
    """

    __tablename__ = "agent_pairing_codes"

    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("events.id", ondelete="CASCADE"), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(String(CODE_LENGTH), unique=True, nullable=False, index=True, default=_generate_code)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    redeemed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    event: Mapped["Event"] = relationship()
    creator: Mapped["User | None"] = relationship()

    def __repr__(self) -> str:  # pragma: no cover
        return f"<AgentPairingCode {self.id} code={self.code!r} event_id={self.event_id}>"
