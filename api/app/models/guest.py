from __future__ import annotations

import secrets
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import INET, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.base import TimestampMixin, UUIDPKMixin

if TYPE_CHECKING:
    from app.models.download import Download
    from app.models.event import Event
    from app.models.guest_face import GuestFace
    from app.models.match import Match


def _generate_session_token() -> str:
    # Bearer token for the guest's own session — scopes every delivery API
    # call to exactly this guest's matches. Never derived from anything
    # guessable (not phone, not guest id).
    return secrets.token_urlsafe(32)


class Guest(Base, UUIDPKMixin, TimestampMixin):
    """A guest's consent + session record. NEVER stores the selfie image or
    a plaintext phone number — see guest_faces for the embedding.
    """

    __tablename__ = "guests"

    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("events.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Hashed (never plaintext), optional — only collected if the flow asks
    # for it (e.g. to notify when new matches land).
    phone_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    consent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consent_ip: Mapped[str | None] = mapped_column(INET, nullable=True)

    session_token: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, index=True, default=_generate_session_token
    )

    # Set the instant the in-memory selfie is discarded post-embedding —
    # always ~now at creation, since the image is never written anywhere
    # to begin with. Kept as an explicit audit trail field per the consent
    # log requirement, not because deletion is ever deferred.
    selfie_deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    event: Mapped["Event"] = relationship(back_populates="guests")
    faces: Mapped[list["GuestFace"]] = relationship(back_populates="guest", cascade="all, delete-orphan")
    matches: Mapped[list["Match"]] = relationship(back_populates="guest", cascade="all, delete-orphan")
    downloads: Mapped[list["Download"]] = relationship(back_populates="guest", cascade="all, delete-orphan")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Guest {self.id} event={self.event_id}>"
