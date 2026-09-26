from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
    text,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.base import TimestampMixin
from app.models.enums import BookingStatus, MatchMode

if TYPE_CHECKING:
    from app.models.booking_event import BookingEvent


class Booking(Base, TimestampMixin):
    """The commercial side of an activation window: tentative/paid, package,
    add-ons. The window itself is owned by the Laqta event (laqta_event_id)."""

    __tablename__ = "bookings"
    __table_args__ = (
        CheckConstraint("ends_at > starts_at", name="ck_bookings_ends_after_starts"),
        CheckConstraint("expected_guests > 0", name="ck_bookings_guests_positive"),
        CheckConstraint("photographers > 0", name="ck_bookings_photographers_positive"),
        # Serves the onsite-capacity count: same city, overlapping days.
        Index("ix_bookings_city_starts_at", "city", "starts_at"),
        # Two bookings must never point at one Laqta event. This is what
        # makes the adapter's idempotency key (booking.id) enforced rather
        # than merely intended. Partial, because most rows are NULL until the
        # event is created.
        Index(
            "uq_bookings_laqta_event_id",
            "laqta_event_id",
            unique=True,
            postgresql_where=text("laqta_event_id IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id"), nullable=False, index=True)
    laqta_org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    laqta_event_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    status: Mapped[BookingStatus] = mapped_column(
        SAEnum(BookingStatus, name="booking_status"), nullable=False
    )
    event_name: Mapped[str] = mapped_column(String(255), nullable=False)
    city: Mapped[str] = mapped_column(String(64), nullable=False)
    venue: Mapped[str] = mapped_column(String(255), nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expected_guests: Mapped[int] = mapped_column(Integer, nullable=False)
    photographers: Mapped[int] = mapped_column(Integer, nullable=False)
    match_mode: Mapped[MatchMode] = mapped_column(SAEnum(MatchMode, name="match_mode"), nullable=False)
    strict_mode: Mapped[bool] = mapped_column(Boolean, nullable=False)
    # Validated against policy.yaml's packages, so not a DB enum: adding a
    # package must not need a migration.
    package: Mapped[str] = mapped_column(String(32), nullable=False)
    addons: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    onsite_support: Mapped[bool] = mapped_column(Boolean, nullable=False)
    payment_due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    events: Mapped[list["BookingEvent"]] = relationship(
        back_populates="booking",
        cascade="all, delete-orphan",
        order_by="BookingEvent.id",
    )

    # Optimistic locking, with the application supplying the counter
    # (booking_state.apply() increments it) rather than SQLAlchemy. Every
    # UPDATE then carries `WHERE version = <the value we read>`, so a second
    # writer working from a stale copy raises StaleDataError instead of
    # silently overwriting the first. See tests/test_state_machine.py.
    __mapper_args__ = {"version_id_col": version, "version_id_generator": False}
