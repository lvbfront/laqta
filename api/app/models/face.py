from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from pgvector.sqlalchemy import Vector
from sqlalchemy import Float, ForeignKeyConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.base import TimestampMixin, UUIDPKMixin

if TYPE_CHECKING:
    from app.models.event import Event
    from app.models.photo import Photo

EMBEDDING_DIM = 512


class Face(Base, UUIDPKMixin, TimestampMixin):
    """One detected+aligned+embedded face within a photo.

    The embedding is an L2-normalized 512-d ArcFace vector produced from a
    112x112 crop that was aligned via the five InsightFace landmarks — never
    from a raw crop. HNSW index (cosine ops) is added in the initial
    migration for fast approximate nearest-neighbor search at match time.

    event_id is denormalized from photo.event_id specifically so match
    queries can filter by event on this same table as the ORDER BY/LIMIT
    vector search, matching pgvector's documented filtered-ANN pattern —
    see app/services/face_search.py for why that matters for recall.

    That denormalization could drift (a face's event_id disagreeing with
    its own photo's event_id), which would let a guest at one event match
    a face that actually belongs to another -- a real cross-event leak, not
    just a data-quality issue. The composite FK below makes that
    structurally impossible: (photo_id, event_id) must exist together as a
    row in photos (see uq_photos_id_event_id), so a mismatched pair is
    rejected by Postgres at insert time, not just by convention in
    app/workers/jobs.py.
    """

    __tablename__ = "faces"
    __table_args__ = (
        ForeignKeyConstraint(
            ["photo_id", "event_id"],
            ["photos.id", "photos.event_id"],
            ondelete="CASCADE",
            name="fk_faces_photo_event",
        ),
    )

    photo_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)

    # Bounding box in original-image pixel coordinates.
    bbox_x1: Mapped[float] = mapped_column(Float, nullable=False)
    bbox_y1: Mapped[float] = mapped_column(Float, nullable=False)
    bbox_x2: Mapped[float] = mapped_column(Float, nullable=False)
    bbox_y2: Mapped[float] = mapped_column(Float, nullable=False)

    det_score: Mapped[float] = mapped_column(Float, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM), nullable=False)

    photo: Mapped["Photo"] = relationship(back_populates="faces")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Face {self.id} photo={self.photo_id} det_score={self.det_score:.2f}>"
