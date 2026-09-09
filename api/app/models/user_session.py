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
    from app.models.user import User


def _generate_session_token() -> str:
    return secrets.token_urlsafe(32)


class UserSession(Base, UUIDPKMixin, TimestampMixin):
    """A staff/organizer login session -- the same bearer-token pattern
    already used for guests (Guest.session_token), kept as its own table
    rather than a column on User because a staff user can legitimately
    have more than one active session (multiple devices), unlike a guest.

    Named UserSession, not Session, to avoid colliding with
    sqlalchemy.orm.Session in any file that imports both.
    """

    __tablename__ = "user_sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, index=True, default=_generate_session_token
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    user: Mapped["User"] = relationship()

    def __repr__(self) -> str:  # pragma: no cover
        return f"<UserSession user={self.user_id} expires_at={self.expires_at}>"
