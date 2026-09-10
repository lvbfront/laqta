from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import require_event_access, require_role
from app.db import get_db
from app.models.agent_token import AgentToken
from app.models.enums import UserRole
from app.models.event import Event
from app.models.user import User
from app.services.agent_pairing import issue_pairing_code, revoke_agent_token

router = APIRouter(tags=["agent-pairing"])

# Same roles as FTP credential issuance / REST photo ingest -- pairing an
# agent is itself a way to grant ingest access.
ISSUE_ROLES = (UserRole.owner, UserRole.staff, UserRole.photographer)


class PairingCodeIssued(BaseModel):
    code: str
    expires_at: datetime


class AgentTokenSummary(BaseModel):
    id: uuid.UUID
    device_label: str | None
    created_at: datetime
    last_seen_at: datetime | None
    revoked_at: datetime | None


@router.post(
    "/api/events/{event_id}/agent-pairing-codes", response_model=PairingCodeIssued, status_code=201
)
def issue_agent_pairing_code(
    db: Annotated[Session, Depends(get_db)],
    event: Annotated[Event, Depends(require_event_access)],
    user: Annotated[User, Depends(require_role(*ISSUE_ROLES))],
) -> PairingCodeIssued:
    pairing_code = issue_pairing_code(db, event, created_by=user.id)
    db.commit()
    return PairingCodeIssued(code=pairing_code.code, expires_at=pairing_code.expires_at)


@router.get("/api/events/{event_id}/agent-tokens", response_model=list[AgentTokenSummary])
def list_agent_tokens(
    db: Annotated[Session, Depends(get_db)],
    event: Annotated[Event, Depends(require_event_access)],
    _role: Annotated[User, Depends(require_role(*ISSUE_ROLES))],
) -> list[AgentTokenSummary]:
    rows = db.query(AgentToken).filter(AgentToken.event_id == event.id).order_by(AgentToken.created_at.desc()).all()
    return [
        AgentTokenSummary(
            id=r.id,
            device_label=r.device_label,
            created_at=r.created_at,
            last_seen_at=r.last_seen_at,
            revoked_at=r.revoked_at,
        )
        for r in rows
    ]


@router.delete("/api/events/{event_id}/agent-tokens/{token_id}", status_code=204, response_model=None)
def revoke_agent_token_route(
    token_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    event: Annotated[Event, Depends(require_event_access)],
    _role: Annotated[User, Depends(require_role(*ISSUE_ROLES))],
) -> None:
    agent_token = db.query(AgentToken).filter(AgentToken.id == token_id, AgentToken.event_id == event.id).first()
    if agent_token is None:
        raise HTTPException(status_code=404, detail={"code": "agent_token_not_found", "message": "Agent not found."})
    revoke_agent_token(db, agent_token)
    db.commit()
