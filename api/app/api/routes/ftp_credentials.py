from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import require_event_access, require_role
from app.db import get_db
from app.models.enums import UserRole
from app.models.event import Event
from app.models.event_ftp_credential import EventFtpCredential
from app.models.user import User
from app.services.ftp_credentials import create_credential, revoke_credential

router = APIRouter(prefix="/api/events/{event_id}/ftp-credentials", tags=["ftp-credentials"])

# Same roles as REST photo ingest (app/api/routes/photos.py's
# INGEST_ROLES) -- issuing a credential is itself a way to grant ingest
# access, so it should require the same permission as ingesting directly.
ISSUE_ROLES = (UserRole.owner, UserRole.staff, UserRole.photographer)


class FtpCredentialIssued(BaseModel):
    id: uuid.UUID
    username: str
    password: str  # plaintext -- shown exactly once, this response only
    created_at: datetime


class FtpCredentialSummary(BaseModel):
    id: uuid.UUID
    username: str
    created_at: datetime
    revoked_at: datetime | None


@router.post("", response_model=FtpCredentialIssued, status_code=201)
def issue_ftp_credential(
    db: Annotated[Session, Depends(get_db)],
    event: Annotated[Event, Depends(require_event_access)],
    user: Annotated[User, Depends(require_role(*ISSUE_ROLES))],
) -> FtpCredentialIssued:
    issued = create_credential(db, event, created_by=user.id)
    db.commit()
    return FtpCredentialIssued(
        id=issued.credential.id,
        username=issued.credential.username,
        password=issued.password,
        created_at=issued.credential.created_at,
    )


@router.get("", response_model=list[FtpCredentialSummary])
def list_ftp_credentials(
    db: Annotated[Session, Depends(get_db)],
    event: Annotated[Event, Depends(require_event_access)],
    _role: Annotated[User, Depends(require_role(*ISSUE_ROLES))],
) -> list[FtpCredentialSummary]:
    rows = (
        db.query(EventFtpCredential)
        .filter(EventFtpCredential.event_id == event.id)
        .order_by(EventFtpCredential.created_at.desc())
        .all()
    )
    return [
        FtpCredentialSummary(id=r.id, username=r.username, created_at=r.created_at, revoked_at=r.revoked_at)
        for r in rows
    ]


@router.delete("/{credential_id}", status_code=204, response_model=None)
def revoke_ftp_credential(
    credential_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    event: Annotated[Event, Depends(require_event_access)],
    _role: Annotated[User, Depends(require_role(*ISSUE_ROLES))],
) -> None:
    credential = (
        db.query(EventFtpCredential)
        .filter(EventFtpCredential.id == credential_id, EventFtpCredential.event_id == event.id)
        .first()
    )
    if credential is None:
        raise HTTPException(
            status_code=404, detail={"code": "credential_not_found", "message": "FTP credential not found."}
        )
    revoke_credential(db, credential)
    db.commit()
