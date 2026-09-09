from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.base import TimestampMixin, UUIDPKMixin

if TYPE_CHECKING:
    from app.models.organization import Organization
    from app.models.photo import Photo
    from app.models.user import User


class Photographer(Base, UUIDPKMixin, TimestampMixin):
    """A photographer profile within an org — shoots photos across that org's events."""

    __tablename__ = "photographers"

    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, unique=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    organization: Mapped["Organization"] = relationship(back_populates="photographers")
    user: Mapped["User | None"] = relationship(back_populates="photographer_profile")
    photos: Mapped[list["Photo"]] = relationship(back_populates="photographer")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Photographer {self.id} {self.name!r}>"
