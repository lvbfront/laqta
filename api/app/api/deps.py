from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.enums import UserRole
from app.models.event import Event
from app.models.user import User
from app.models.user_session import UserSession
from app.services.agent_pairing import authenticate_agent_token


def get_current_user(
    db: Annotated[Session, Depends(get_db)],
    authorization: Annotated[str | None, Header()] = None,
) -> User:
    """Every dashboard/org/event/moderation endpoint depends on this --
    bearer token, the same pattern guest sessions already use
    (app/api/routes/delivery.py's _current_guest), just backed by its own
    table (see app/models/user_session.py for why a staff session isn't a
    column on User the way a guest's is).
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=401, detail={"code": "missing_session", "message": "Authentication required."}
        )
    token = authorization[len("bearer ") :].strip()

    session = db.query(UserSession).filter(UserSession.token == token).first()
    if session is None or session.expires_at < datetime.now(timezone.utc):
        raise HTTPException(
            status_code=401, detail={"code": "invalid_session", "message": "Invalid or expired session."}
        )

    user = db.get(User, session.user_id)
    if user is None:
        raise HTTPException(
            status_code=401, detail={"code": "invalid_session", "message": "Invalid or expired session."}
        )
    return user


def require_org_member(
    org_id: uuid.UUID,
    user: Annotated[User, Depends(get_current_user)],
) -> User:
    """For routes with {org_id} directly in the path. A different org's id
    404s here, not 403 -- a non-member of that org shouldn't be able to
    tell the id is even valid, same anti-enumeration reasoning as the
    guest-facing endpoints (just for a different audience).
    """
    if user.org_id != org_id:
        raise HTTPException(
            status_code=404, detail={"code": "organization_not_found", "message": "Organization not found."}
        )
    return user


def require_event_access(
    event_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> Event:
    """For routes with {event_id} in the path -- loads the event and
    checks org membership in exactly one place, so every event-scoped
    route enforces the identical rule rather than each re-deriving it.
    Returns the loaded Event so the route doesn't have to re-query it.
    404 for "belongs to another org", same reasoning as require_org_member.
    """
    event = db.get(Event, event_id)
    if event is None or event.org_id != user.org_id:
        raise HTTPException(status_code=404, detail={"code": "event_not_found", "message": "Event not found."})
    return event


def get_agent_event(
    db: Annotated[Session, Depends(get_db)],
    authorization: Annotated[str | None, Header()] = None,
) -> Event:
    """Auth for the desktop agent's own upload endpoint
    (app/api/routes/agent.py) -- a bearer AgentToken, not a UserSession.
    The agent never has a staff login; its token is scoped to exactly one
    event (set at pairing time), so there's no separate org/role check to
    layer on top the way require_event_access needs for a human session.
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=401, detail={"code": "missing_agent_token", "message": "Agent token required."}
        )
    token = authorization[len("bearer ") :].strip()

    agent_token = authenticate_agent_token(db, token)
    if agent_token is None:
        raise HTTPException(
            status_code=401, detail={"code": "invalid_agent_token", "message": "Invalid or revoked agent token."}
        )

    event = db.get(Event, agent_token.event_id)
    if event is None:
        raise HTTPException(
            status_code=401, detail={"code": "invalid_agent_token", "message": "Invalid or revoked agent token."}
        )
    return event


def require_role(*roles: UserRole):
    """Layer on top of require_org_member/require_event_access (both
    already require a valid session) to also gate by role, e.g.
    Depends(require_role(UserRole.owner, UserRole.staff)). A visible
    resource the caller just isn't permitted to act on is 403, not 404 --
    unlike the org/event-scope checks above, there's nothing to hide here.
    """

    def _check(user: Annotated[User, Depends(get_current_user)]) -> User:
        if user.role not in roles:
            raise HTTPException(
                status_code=403, detail={"code": "forbidden", "message": "Insufficient permissions for this action."}
            )
        return user

    return _check
