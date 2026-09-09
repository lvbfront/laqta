from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.base import TimestampMixin, UUIDPKMixin
from app.models.enums import PhotoStatus

if TYPE_CHECKING:
    from app.models.event import Event
    from app.models.face import Face
    from app.models.photo_code import PhotoCode
    from app.models.photographer import Photographer
    from app.models.user import User


class Photo(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "photos"
    __table_args__ = (
        # MD5 dedupe is scoped per event — the same JPEG re-uploaded (burst
        # retry, sweep-upload after a live-path drop) is a no-op, not a
        # duplicate photo. Enforced here (not just at the API layer) to
        # survive concurrent uploads of the same file.
        UniqueConstraint("event_id", "md5", name="uq_photos_event_md5"),
        # Lets faces reference (photo_id, event_id) as a composite FK (see
        # app/models/face.py) so a face's event_id can never drift from its
        # own photo's event_id -- structurally, not just by convention.
        # `id` alone is already the PK/unique; this just also exposes the
        # (id, event_id) pair as a referenceable unique key.
        UniqueConstraint("id", "event_id", name="uq_photos_id_event_id"),
    )

    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("events.id", ondelete="CASCADE"), nullable=False, index=True
    )
    photographer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("photographers.id", ondelete="SET NULL"), nullable=True
    )

    # Original is written straight to MinIO by the ingest endpoint.
    # Thumbnail/preview keys are filled in by the worker once processing
    # finishes (null while status is 'pending'/'processing').
    s3_key_original: Mapped[str] = mapped_column(String(512), nullable=False)
    s3_key_thumbnail: Mapped[str | None] = mapped_column(String(512), nullable=True)
    s3_key_preview: Mapped[str | None] = mapped_column(String(512), nullable=True)

    md5: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)

    status: Mapped[PhotoStatus] = mapped_column(
        SAEnum(PhotoStatus, name="photo_status"), nullable=False, default=PhotoStatus.pending
    )

    # Moderation / visibility. For a standard event with auto_publish=true,
    # the worker sets published=true as soon as status becomes 'ready'. For
    # a strict event (auto_publish is forced false), published stays false
    # until a moderator explicitly approves it — enforced again at query
    # time in the match/delivery APIs, not just here.
    published: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    moderated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    moderated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    event: Mapped["Event"] = relationship(back_populates="photos")
    photographer: Mapped["Photographer | None"] = relationship(back_populates="photos")
    moderator: Mapped["User | None"] = relationship(foreign_keys=[moderated_by])
    faces: Mapped[list["Face"]] = relationship(back_populates="photo", cascade="all, delete-orphan")
    codes: Mapped[list["PhotoCode"]] = relationship(back_populates="photo", cascade="all, delete-orphan")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Photo {self.id} status={self.status} published={self.published}>"
