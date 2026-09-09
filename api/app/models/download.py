from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import INET, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.base import UUIDPKMixin

if TYPE_CHECKING:
    from app.models.guest import Guest
    from app.models.photo import Photo


class Download(Base, UUIDPKMixin):
    """Every delivery of an original/preview to a guest, logged for audit
    and abuse detection (e.g. a session hammering the delivery endpoint).
    """

    __tablename__ = "downloads"

    guest_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("guests.id", ondelete="CASCADE"), nullable=False, index=True
    )
    photo_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("photos.id", ondelete="CASCADE"), nullable=False, index=True
    )
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    ip: Mapped[str | None] = mapped_column(INET, nullable=True)

    guest: Mapped["Guest"] = relationship(back_populates="downloads")
    photo: Mapped["Photo"] = relationship()

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Download guest={self.guest_id} photo={self.photo_id} at={self.at}>"
