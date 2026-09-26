from __future__ import annotations

from pgvector.sqlalchemy import Vector
from sqlalchemy import String, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.config import EMBEDDING_DIM
from app.db import Base
from app.models.enums import KBAudience


class KBChunk(Base):
    __tablename__ = "kb_chunks"

    id: Mapped[int] = mapped_column(primary_key=True)
    section_title: Mapped[str] = mapped_column(String(255), nullable=False)
    audience: Mapped[KBAudience] = mapped_column(
        SAEnum(KBAudience, name="kb_audience"), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # Upsert key for scripts/index_kb.py.
    content_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM), nullable=False)
