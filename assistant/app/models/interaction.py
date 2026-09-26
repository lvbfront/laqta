from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, Text, text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.enums import Channel, IdentityKind


class Interaction(Base):
    """One conversation session."""

    __tablename__ = "interactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    contact_id: Mapped[int | None] = mapped_column(
        ForeignKey("contacts.id"), nullable=True, index=True
    )
    staff_id: Mapped[int | None] = mapped_column(ForeignKey("staff.id"), nullable=True)
    channel: Mapped[Channel] = mapped_column(SAEnum(Channel, name="channel"), nullable=False)
    identity_kind: Mapped[IdentityKind] = mapped_column(
        SAEnum(IdentityKind, name="identity_kind"), nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    transcript: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    # 2–3 line summary written when the session ends.
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    # booked | answered | handed_off | abandoned ... — open-ended on purpose,
    # so not a DB enum.
    outcome: Mapped[str | None] = mapped_column(String(32), nullable=True)
