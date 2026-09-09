from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.base import TimestampMixin, UUIDPKMixin
from app.models.face import EMBEDDING_DIM

if TYPE_CHECKING:
    from app.models.guest import Guest


class GuestFace(Base, UUIDPKMixin, TimestampMixin):
    """The guest's selfie, reduced to a vector — this row is the only trace
    of the selfie that ever exists. Purged by the scheduled purge job once
    expires_at passes (event end + retention window), hard-deleted with an
    audit_log entry.
    """

    __tablename__ = "guest_faces"

    guest_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("guests.id", ondelete="CASCADE"), nullable=False, index=True
    )
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)

    guest: Mapped["Guest"] = relationship(back_populates="faces")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<GuestFace {self.id} guest={self.guest_id} expires_at={self.expires_at}>"
