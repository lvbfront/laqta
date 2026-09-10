from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_agent_event
from app.db import get_db
from app.models.event import Event
from app.services.agent_pairing import redeem_pairing_code
from app.services.ingest import ingest_photo

router = APIRouter(prefix="/api/agent", tags=["agent"])


class PairRequest(BaseModel):
    code: str
    device_label: str | None = None


class PairResponse(BaseModel):
    token: str  # plaintext -- shown to the agent exactly once, stored in its OS keychain
    event_id: uuid.UUID


@router.post("/pair", response_model=PairResponse)
def pair_agent(body: PairRequest, db: Annotated[Session, Depends(get_db)]) -> PairResponse:
    """Deliberately unauthenticated by session -- a photographer running
    the desktop agent (agent/) never has a staff login, only this code
    read off the dashboard. See app/models/agent_pairing_code.py for why
    a wrong/expired/already-used code gets the same 401 regardless of
    which of those three it is (nothing here should help someone guess
    codes by telling them why one failed).
    """
    result = redeem_pairing_code(db, body.code, body.device_label)
    if result is None:
        raise HTTPException(
            status_code=401,
            detail={"code": "invalid_pairing_code", "message": "That code is invalid, expired, or already used."},
        )
    db.commit()
    return PairResponse(token=result.token, event_id=result.event_id)


class AgentUploadResult(BaseModel):
    status: str  # "queued" | "duplicate" | "error"
    photo_id: uuid.UUID | None = None
    duplicate_of: uuid.UUID | None = None
    error: str | None = None


@router.post("/photos", response_model=AgentUploadResult, status_code=201)
async def upload_via_agent(
    db: Annotated[Session, Depends(get_db)],
    event: Annotated[Event, Depends(get_agent_event)],
    file: Annotated[UploadFile, File(...)],
) -> AgentUploadResult:
    """One file per call, not a batch -- the agent uploads each photo the
    instant its own file-stability check clears it (agent/laqta_agent/
    stability.py), so there's rarely more than one file actually ready at
    once; batching here would just add latency waiting to group files
    that don't need grouping. Same shared ingest_photo() as the REST
    dashboard upload and the FTPS handler.
    """
    content = await file.read()
    result = ingest_photo(db, event.id, content, file.content_type or "image/jpeg")
    return AgentUploadResult(
        status=result.status,
        photo_id=result.photo_id,
        duplicate_of=result.duplicate_of,
        error=result.error,
    )
