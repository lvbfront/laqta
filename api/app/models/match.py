from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Enum as SAEnum
from sqlalchemy import Float, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.base import TimestampMixin, UUIDPKMixin
from app.models.enums import MatchFeedback

if TYPE_CHECKING:
    from app.models.guest import Guest
    from app.models.photo import Photo


class Match(Base, UUIDPKMixin, TimestampMixin):
    """One guest-to-photo match: the max cosine score across that photo's
    faces against the guest's selfie embedding, at or above match_threshold.
    """

    __tablename__ = "matches"
    __table_args__ = (UniqueConstraint("guest_id", "photo_id", name="uq_matches_guest_photo"),)

    guest_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("guests.id", ondelete="CASCADE"), nullable=False, index=True
    )
    photo_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("photos.id", ondelete="CASCADE"), nullable=False, index=True
    )
    score: Mapped[float] = mapped_column(Float, nullable=False)

    # null = no feedback yet. 'not_me' = guest flagged a false positive.
    # 'remove_requested' = guest asked for the photo to be hidden/removed —
    # hidden from all matches immediately, flagged for the organizer.
    feedback: Mapped[MatchFeedback | None] = mapped_column(
        SAEnum(MatchFeedback, name="match_feedback"), nullable=True
    )

    guest: Mapped["Guest"] = relationship(back_populates="matches")
    photo: Mapped["Photo"] = relationship()

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Match guest={self.guest_id} photo={self.photo_id} score={self.score:.3f}>"
