from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.base import TimestampMixin, UUIDPKMixin
from app.models.enums import EventStatus, MatchMode, PrivacyMode

if TYPE_CHECKING:
    from sqlalchemy.engine.default import DefaultExecutionContext

    from app.models.guest import Guest
    from app.models.organization import Organization
    from app.models.photo import Photo

# How long past an event's end its data is retained by default, before
# the purge job hard-deletes it -- see app/workers/purge.py. Strict events
# (women's events, the privacy-first wedge -- docs/plan.md) default
# shorter deliberately, not because a technical constraint demands it.
STRICT_RETENTION_DAYS = 7
STANDARD_RETENTION_DAYS = 30


def _generate_qr_token() -> str:
    # URL-safe token embedded in the guest-facing QR code (/e/[qr_token]).
    # Unguessable — this is the only way in for a guest, no enumeration.
    return secrets.token_urlsafe(16)


def _default_retention_until(context: "DefaultExecutionContext") -> datetime:
    """Computed from the row's own ends_at + privacy_mode at INSERT time --
    not a DB-generated column, specifically so it stays a one-time default
    that a caller can still override (e.g. an organizer requesting
    extended retention for a specific event), not an immutable formula.
    Requires ends_at and privacy_mode to already be present in the same
    insert (both are NOT NULL / always-defaulted columns), which is why
    this must run as a column default, not a Python-side dataclass
    default -- it needs get_current_parameters() to see sibling columns
    being inserted in the same row.
    """
    params = context.get_current_parameters()
    ends_at: datetime | None = params["ends_at"]
    if ends_at is None:
        # ends_at is a NOT NULL column, so Postgres would reject this row
        # anyway -- but this default callable runs client-side, before the
        # INSERT is even sent, so without this check the failure here
        # would be an opaque TypeError on `None + timedelta`, not a
        # message that points at the actual missing field.
        raise ValueError("Event.ends_at must be set -- retention_until's default is computed from it")
    privacy_mode: PrivacyMode = params["privacy_mode"]
    days = STRICT_RETENTION_DAYS if privacy_mode == PrivacyMode.strict else STANDARD_RETENTION_DAYS
    return ends_at + timedelta(days=days)


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
    # NOT NULL: retention_until's default is computed from this -- an
    # event with no known end has no way to derive a retention date, and
    # would then never become eligible for purge (see the NOT NULL note
    # on retention_until below).
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[EventStatus] = mapped_column(
        SAEnum(EventStatus, name="event_status"), nullable=False, default=EventStatus.draft
    )

    qr_token: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, index=True, default=_generate_qr_token
    )

    # NOT NULL, on purpose: a nullable retention_until is how an event
    # silently becomes permanently unpurgeable -- the purge job's WHERE
    # retention_until < now() clause simply never matches a NULL, no
    # error, no warning, retention quietly unenforced. Defaulted from
    # ends_at + privacy_mode (see _default_retention_until) but always
    # overridable by passing an explicit value.
    retention_until: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_default_retention_until
    )
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

    # match_mode='sequential' only: the number currently being auto-tagged
    # onto incoming photos. NULL until the first "next guest" tap
    # (app/api/routes/events.py's advance_solo_number); every ingested
    # photo checks this at upload time and, if set, gets a matching
    # PhotoCode (app/services/ingest.py). Meaningless for every other
    # match_mode -- left NULL and ignored.
    current_solo_number: Mapped[int | None] = mapped_column(Integer, nullable=True)

    organization: Mapped["Organization"] = relationship(back_populates="events")
    photos: Mapped[list["Photo"]] = relationship(back_populates="event")
    guests: Mapped[list["Guest"]] = relationship(back_populates="event")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Event {self.id} {self.name_en!r} privacy={self.privacy_mode}>"
