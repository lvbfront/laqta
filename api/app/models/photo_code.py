from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.base import TimestampMixin, UUIDPKMixin

if TYPE_CHECKING:
    from app.models.photo import Photo


class PhotoCode(Base, UUIDPKMixin, TimestampMixin):
    """A bib/badge/wristband code manually tagged onto a photo -- what
    match_mode='code' matches against instead of a face embedding. A
    many-to-one table (not a single column on Photo) on purpose: a race
    photo routinely shows several runners, each with their own visible
    bib, and each should be independently findable.

    There is no OCR/detection pipeline that populates this automatically
    -- staff tag codes via the dashboard (see
    POST /api/events/{id}/photos/{photo_id}/codes), same trust boundary as
    moderation.
    """

    __tablename__ = "photo_codes"
    __table_args__ = (UniqueConstraint("photo_id", "code", name="uq_photo_codes_photo_code"),)

    photo_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("photos.id", ondelete="CASCADE"), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    photo: Mapped["Photo"] = relationship(back_populates="codes")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<PhotoCode photo={self.photo_id} code={self.code!r}>"
