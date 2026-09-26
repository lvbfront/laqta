"""Who the client is allowed to say it is.

DevAuth's identity is chosen, not proven — that is what its name says and
what makes it safe only behind a flag. With the flag off, the request's
identity field is not validated and rejected; it is not read at all, so there
is no code path where a client-supplied string reaches DevAuth.parse.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.identity.dev_auth import AuthError, DevAuth
from app.identity.identity import Identity

ANONYMOUS = "anon"


def resolve(db: Session, requested: str | None, *, dev: bool) -> tuple[Identity, str]:
    """Returns the identity and the spec it was actually built from, which is
    what the session reports back — so a client that asked for customer:1 and
    got anonymous can see that it did."""
    if not dev or requested is None:
        return Identity(kind="anonymous"), ANONYMOUS
    spec = requested.strip()
    return DevAuth(db).parse(spec), spec


__all__ = ["ANONYMOUS", "AuthError", "resolve"]
