from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import UUIDPKMixin


class AuditLog(Base, UUIDPKMixin):
    """Append-only trail for actions that matter for PDPL accountability:
    consent capture, moderation decisions, purge-job deletions, and any
    staff access to originals on a closed strict-mode event.

    Intentionally has no FK constraints — it must remain writable/readable
    even after the row it refers to (e.g. a purged guest_faces row) is gone.
    """

    __tablename__ = "audit_log"

    actor: Mapped[str] = mapped_column(String(255), nullable=False)  # user id, or 'system'/job name
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)  # e.g. "photo:<uuid>"
    meta: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<AuditLog {self.actor} {self.action} {self.subject} at={self.at}>"
