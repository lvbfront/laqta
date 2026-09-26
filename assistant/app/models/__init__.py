"""Import every model so app.db.Base.metadata is fully populated — required
for Alembic autogenerate.
"""

from app.models.booking import Booking
from app.models.booking_event import BookingEvent
from app.models.confirmation import Confirmation
from app.models.contact import Contact
from app.models.interaction import Interaction
from app.models.kb_chunk import KBChunk
from app.models.scheduled_action import ScheduledAction
from app.models.staff import Staff
from app.models.ticket import Ticket
from app.models.tool_call import ToolCall

__all__ = [
    "Booking",
    "BookingEvent",
    "Confirmation",
    "Contact",
    "Interaction",
    "KBChunk",
    "ScheduledAction",
    "Staff",
    "Ticket",
    "ToolCall",
]
