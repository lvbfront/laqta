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
    from app.models.user import User


class EventFtpCredential(Base, UUIDPKMixin, TimestampMixin):
    """A username/password pair scoped to exactly one event, for FTPS
    camera/desktop-agent ingest (docs/plan.md: "per-event username,
    generated password"). Deliberately per-event, not per-photographer --
    a photographer shooting three events this month gets three separate
    credentials, so revoking access to one event (the gig ended, the
    laptop was lost) never touches the other two. Supersedes the
    ftp_username/ftp_password_hash columns speculatively reserved on
    Photographer in Phase 1 -- those were never populated and are dropped
    by this migration in favor of this table.

    The plaintext password is generated once at creation
    (app.services.ftp_credentials.create_credential) and returned to the
    caller exactly once -- only password_hash is ever persisted, same
    bcrypt-direct approach as app.core.security for staff passwords.
    """

    __tablename__ = "event_ftp_credentials"

    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("events.id", ondelete="CASCADE"), nullable=False, index=True
    )
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # Revocation is a timestamp, not a delete -- an organizer might want to
    # know a credential existed and when it stopped working (audit trail),
    # and app.ftps.authorizer checks this on every login attempt.
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    event: Mapped["Event"] = relationship()
    creator: Mapped["User | None"] = relationship()

    def __repr__(self) -> str:  # pragma: no cover
        return f"<EventFtpCredential {self.id} username={self.username!r} event_id={self.event_id}>"
