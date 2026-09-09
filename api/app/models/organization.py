from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Enum as SAEnum
from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.base import TimestampMixin, UUIDPKMixin
from app.models.enums import AccountType

if TYPE_CHECKING:
    from app.models.event import Event
    from app.models.photographer import Photographer
    from app.models.user import User


class Organization(Base, UUIDPKMixin, TimestampMixin):
    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    cr_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    account_type: Mapped[AccountType] = mapped_column(
        SAEnum(AccountType, name="account_type", native_enum=True), nullable=False
    )

    users: Mapped[list["User"]] = relationship(back_populates="organization")
    events: Mapped[list["Event"]] = relationship(back_populates="organization")
    photographers: Mapped[list["Photographer"]] = relationship(back_populates="organization")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Organization {self.id} {self.name!r}>"
