from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.enums import BookingStatus

if TYPE_CHECKING:
    from app.models.booking import Booking


class BookingEvent(Base):
    """One row per state transition."""

    __tablename__ = "booking_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    booking_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("bookings.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # NULL for the creating transition (— → tentative).
    from_status: Mapped[BookingStatus | None] = mapped_column(
        SAEnum(BookingStatus, name="booking_status"), nullable=True
    )
    to_status: Mapped[BookingStatus] = mapped_column(
        SAEnum(BookingStatus, name="booking_status"), nullable=False
    )
    trigger: Mapped[str] = mapped_column(String(32), nullable=False)
    actor: Mapped[str] = mapped_column(String(64), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The transition's `now`, not the DB clock.
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    booking: Mapped["Booking"] = relationship(back_populates="events")
