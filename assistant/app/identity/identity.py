from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class Identity:
    """Who is speaking, as established by an authenticator (DevAuth now,
    LaqtaAuth later). Tools trust this and nothing the user says."""

    kind: Literal["anonymous", "customer", "staff"]
    contact_id: int | None = None
    staff_id: int | None = None
    # Laqta ids are UUIDs (api/app/models/base.py UUIDPKMixin).
    laqta_user_id: uuid.UUID | None = None
    laqta_org_id: uuid.UUID | None = None

    def __post_init__(self) -> None:
        # A half-built identity is how scoping bugs start: reject it here so
        # no tool ever has to wonder whether contact_id can be None.
        if self.kind == "anonymous":
            if any(v is not None for v in (self.contact_id, self.staff_id, self.laqta_user_id, self.laqta_org_id)):
                raise ValueError("an anonymous identity carries no ids")
        elif self.kind == "customer":
            if self.contact_id is None or self.laqta_user_id is None or self.laqta_org_id is None:
                raise ValueError("a customer identity needs contact_id, laqta_user_id and laqta_org_id")
            if self.staff_id is not None:
                raise ValueError("a customer identity has no staff_id")
        elif self.kind == "staff":
            if self.staff_id is None:
                raise ValueError("a staff identity needs staff_id")
            if self.contact_id is not None:
                raise ValueError("a staff identity has no contact_id")
        else:
            raise ValueError(f"unknown identity kind: {self.kind!r}")
