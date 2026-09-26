from __future__ import annotations

import uuid

from sqlalchemy import Enum as SAEnum
from sqlalchemy import String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import TimestampMixin
from app.models.enums import ContactSource, Gender


class Contact(Base, TimestampMixin):
    """Someone the assistant has dealt with. Laqta owns who they are (account,
    login, org); this row owns what happened between us (spec §0)."""

    __tablename__ = "contacts"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Laqta users.id. NULL for an anonymous visitor who left a name + phone.
    laqta_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), unique=True, nullable=True
    )
    laqta_org_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    org_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # NULL unless the person stated it. The assistant addresses a NULL-gender
    # contact in gender-neutral Arabic (taxonomy 8).
    gender: Mapped[Gender | None] = mapped_column(
        SAEnum(Gender, name="contact_gender"), nullable=True
    )
    source: Mapped[ContactSource] = mapped_column(
        SAEnum(ContactSource, name="contact_source"), nullable=False
    )
