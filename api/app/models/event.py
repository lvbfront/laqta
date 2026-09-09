from __future__ import annotations

import secrets
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, String, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.base import TimestampMixin, UUIDPKMixin
from app.models.enums import EventStatus, MatchMode, PrivacyMode

if TYPE_CHECKING:
    from app.models.guest import Guest
    from app.models.organization import Organization
    from app.models.photo import Photo


def _generate_qr_token() -> str:
    # URL-safe token embedded in the guest-facing QR code (/e/[qr_token]).
    # Unguessable — this is the only way in for a guest, no enumeration.
    return secrets.token_urlsafe(16)


class Event(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "events"
    __table_args__ = (
        CheckConstraint(
            "privacy_mode <> 'strict' OR auto_publish = false",
            name="ck_events_strict_requires_no_autopublish",
        ),
    )

    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    name_ar: Mapped[str] = mapped_column(String(255), nullable=False)
    name_en: Mapped[str] = mapped_column(String(255), nullable=False)
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[EventStatus] = mapped_column(
        SAEnum(EventStatus, name="event_status"), nullable=False, default=EventStatus.draft
    )

    qr_token: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, index=True, default=_generate_qr_token
    )

    retention_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    consent_text_ar: Mapped[str] = mapped_column(Text, nullable=False)
    consent_text_en: Mapped[str] = mapped_column(Text, nullable=False)

    privacy_mode: Mapped[PrivacyMode] = mapped_column(
        SAEnum(PrivacyMode, name="privacy_mode"), nullable=False, default=PrivacyMode.standard
    )
    match_mode: Mapped[MatchMode] = mapped_column(
        SAEnum(MatchMode, name="match_mode"), nullable=False, default=MatchMode.face
    )
    # Forced to false at the DB layer (see check constraint above) whenever
    # privacy_mode == 'strict'. Also enforced in the API layer — never rely
    # on the constraint alone for a strict event's photo visibility.
    auto_publish: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    brand_logo_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    sponsor_overlay_key: Mapped[str | None] = mapped_column(String(512), nullable=True)

    organization: Mapped["Organization"] = relationship(back_populates="events")
    photos: Mapped[list["Photo"]] = relationship(back_populates="event")
    guests: Mapped[list["Guest"]] = relationship(back_populates="event")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Event {self.id} {self.name_en!r} privacy={self.privacy_mode}>"
