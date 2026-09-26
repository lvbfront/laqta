from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.orm import Mapped, mapped_column


class TimestampMixin:
    # Audit timestamp only. Anything a business rule reads (due dates,
    # expiries, transition times) is set from the caller's `now` instead, so
    # a fake clock in tests and layer 4 stays consistent.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
