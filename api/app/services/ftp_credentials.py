from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import hash_password, verify_password
from app.models.event import Event
from app.models.event_ftp_credential import EventFtpCredential

_USERNAME_RANDOM_HEX_LEN = 6
_MAX_USERNAME_COLLISION_RETRIES = 5


@dataclass(frozen=True)
class IssuedCredential:
    credential: EventFtpCredential
    password: str  # plaintext, available only right here -- never persisted


def _generate_username(event_id: uuid.UUID) -> str:
    # Short and event-identifiable (helps an organizer eyeball which
    # credential belongs to which event in a camera's saved FTP settings)
    # plus a random suffix so re-issuing for the same event doesn't collide
    # with a still-active previous credential.
    return f"evt-{event_id.hex[:8]}-{secrets.token_hex(_USERNAME_RANDOM_HEX_LEN)}"


def _generate_password() -> str:
    # Needs to be typed into a camera's on-body FTP settings screen by a
    # photographer standing at a venue, not just pasted -- url-safe base64
    # avoids characters a camera's D-pad text entry makes painful (quotes,
    # backslashes, ambiguous punctuation), while staying long enough
    # (~27 chars from 20 random bytes) to be a real secret.
    return secrets.token_urlsafe(20)


def create_credential(db: Session, event: Event, created_by: uuid.UUID | None) -> IssuedCredential:
    for _ in range(_MAX_USERNAME_COLLISION_RETRIES):
        password = _generate_password()
        credential = EventFtpCredential(
            event_id=event.id,
            username=_generate_username(event.id),
            password_hash=hash_password(password),
            created_by=created_by,
        )
        db.add(credential)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            continue
        return IssuedCredential(credential=credential, password=password)
    raise RuntimeError("could not generate a unique FTPS username after several attempts")


def revoke_credential(db: Session, credential: EventFtpCredential) -> None:
    credential.revoked_at = datetime.now(timezone.utc)
    db.flush()


def authenticate(db: Session, username: str, password: str) -> EventFtpCredential | None:
    """Used by app.ftps.authorizer on every FTPS login attempt. Returns
    None (not raises) for any failure reason -- unknown username, wrong
    password, revoked credential, or an event that's since been deleted
    (ON DELETE CASCADE means the row itself would already be gone, but the
    revoked_at check covers the more common "event ended" case) -- the
    caller doesn't need to distinguish why, only whether to let the
    connection through.
    """
    credential = db.query(EventFtpCredential).filter(EventFtpCredential.username == username).first()
    if credential is None or credential.revoked_at is not None:
        return None
    if not verify_password(password, credential.password_hash):
        return None
    return credential
