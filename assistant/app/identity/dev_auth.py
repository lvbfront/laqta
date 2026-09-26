"""Terminal-only authenticator: the identity is *chosen* with `--as`, not
proven. LaqtaAuth (bearer token → GET /api/auth/me) replaces it with the
same parse-a-credential-into-an-Identity shape.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.identity.identity import Identity
from app.models import Contact, Staff

ANONYMOUS_SPECS = frozenset({"anon", "anonymous"})


class AuthError(Exception):
    pass


class DevAuth:
    def __init__(self, session: Session) -> None:
        self._session = session

    def parse(self, spec: str) -> Identity:
        """`anon` | `customer:<contact_id>` | `staff:<staff_id>`."""
        spec = spec.strip()
        if spec in ANONYMOUS_SPECS:
            return Identity(kind="anonymous")

        kind, sep, raw_id = spec.partition(":")
        if not sep or kind not in ("customer", "staff") or not raw_id.isdigit():
            raise AuthError(f"expected anon, customer:<id> or staff:<id>, got {spec!r}")
        row_id = int(raw_id)

        if kind == "customer":
            contact = self._session.get(Contact, row_id)
            if contact is None:
                raise AuthError(f"no contact with id {row_id}")
            if contact.laqta_user_id is None or contact.laqta_org_id is None:
                # A customer session means "logged in to Laqta". A contact
                # without a Laqta account (e.g. an anonymous visitor's lead)
                # can't be one.
                raise AuthError(f"contact {row_id} has no Laqta account")
            return Identity(
                kind="customer",
                contact_id=contact.id,
                laqta_user_id=contact.laqta_user_id,
                laqta_org_id=contact.laqta_org_id,
            )

        staff = self._session.get(Staff, row_id)
        if staff is None or not staff.active:
            raise AuthError(f"no active staff member with id {row_id}")
        return Identity(kind="staff", staff_id=staff.id, laqta_user_id=staff.laqta_user_id)
