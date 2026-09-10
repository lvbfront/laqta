from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.models.agent_pairing_code import AgentPairingCode
from app.models.agent_token import AgentToken
from app.models.event import Event

_MAX_CODE_COLLISION_RETRIES = 5


@dataclass(frozen=True)
class RedeemResult:
    token: str  # plaintext -- returned to the agent exactly once, never persisted
    agent_token: AgentToken
    event_id: uuid.UUID


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def issue_pairing_code(db: Session, event: Event, created_by: uuid.UUID | None) -> AgentPairingCode:
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=settings.agent_pairing_code_ttl_minutes)
    for _ in range(_MAX_CODE_COLLISION_RETRIES):
        pairing_code = AgentPairingCode(event_id=event.id, expires_at=expires_at, created_by=created_by)
        db.add(pairing_code)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            continue
        return pairing_code
    raise RuntimeError("could not generate a unique pairing code after several attempts")


def redeem_pairing_code(db: Session, code: str, device_label: str | None) -> RedeemResult | None:
    """Called by the agent itself (app/api/routes/agent.py's pair_agent),
    not the dashboard -- unauthenticated by session, because the whole
    point is the photographer never logs in, they just type this code.
    Returns None for any failure reason (unknown code, expired, already
    redeemed) -- the caller doesn't need to distinguish why, only whether
    to hand back a token.
    """
    pairing_code = db.query(AgentPairingCode).filter(AgentPairingCode.code == code.strip().upper()).first()
    if pairing_code is None:
        return None
    if pairing_code.redeemed_at is not None:
        return None
    if pairing_code.expires_at < datetime.now(timezone.utc):
        return None

    token = secrets.token_urlsafe(32)
    agent_token = AgentToken(
        event_id=pairing_code.event_id,
        token_hash=_hash_token(token),
        device_label=device_label,
    )
    db.add(agent_token)
    pairing_code.redeemed_at = datetime.now(timezone.utc)
    db.flush()

    return RedeemResult(token=token, agent_token=agent_token, event_id=pairing_code.event_id)


def authenticate_agent_token(db: Session, token: str) -> AgentToken | None:
    """Used on every app/api/routes/agent.py's upload_via_agent call. Also
    bumps last_seen_at -- purely informational (a dashboard "last active"
    display, not yet built, could use it), never part of the auth
    decision itself.
    """
    agent_token = db.query(AgentToken).filter(AgentToken.token_hash == _hash_token(token)).first()
    if agent_token is None or agent_token.revoked_at is not None:
        return None
    agent_token.last_seen_at = datetime.now(timezone.utc)
    db.flush()
    return agent_token


def revoke_agent_token(db: Session, agent_token: AgentToken) -> None:
    agent_token.revoked_at = datetime.now(timezone.utc)
    db.flush()
