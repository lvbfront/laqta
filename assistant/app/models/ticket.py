from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import TimestampMixin
from app.models.enums import Team, TicketPriority, TicketReason, TicketStatus


class Ticket(Base, TimestampMixin):
    __tablename__ = "tickets"
    __table_args__ = (
        # Serves "assign to the team member with the fewest open tickets".
        Index("ix_tickets_assignee_status", "assignee_staff_id", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    contact_id: Mapped[int | None] = mapped_column(
        ForeignKey("contacts.id"), nullable=True, index=True
    )
    interaction_id: Mapped[int] = mapped_column(ForeignKey("interactions.id"), nullable=False)
    team: Mapped[Team] = mapped_column(SAEnum(Team, name="team"), nullable=False)
    assignee_staff_id: Mapped[int | None] = mapped_column(ForeignKey("staff.id"), nullable=True)
    priority: Mapped[TicketPriority] = mapped_column(
        SAEnum(TicketPriority, name="ticket_priority"), nullable=False
    )
    reason_code: Mapped[TicketReason] = mapped_column(
        SAEnum(TicketReason, name="ticket_reason"), nullable=False
    )
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[TicketStatus] = mapped_column(
        SAEnum(TicketStatus, name="ticket_status"), nullable=False, default=TicketStatus.open
    )
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
