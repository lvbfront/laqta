from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.security import hash_password, verify_password
from app.db import get_db
from app.models.enums import AccountType, UserRole
from app.models.organization import Organization
from app.models.user import User
from app.models.user_session import UserSession

router = APIRouter(prefix="/api/auth", tags=["auth"])

SESSION_TTL_DAYS = 7
MIN_PASSWORD_LENGTH = 8


class RegisterRequest(BaseModel):
    org_name: str
    email: EmailStr
    password: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class UserPublic(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    email: str
    role: str


class AuthResponse(BaseModel):
    session_token: str
    user: UserPublic


def _user_public(user: User) -> UserPublic:
    return UserPublic(id=user.id, org_id=user.org_id, email=user.email, role=user.role.value)


def _create_session(db: Session, user: User) -> UserSession:
    session = UserSession(user_id=user.id, expires_at=datetime.now(timezone.utc) + timedelta(days=SESSION_TTL_DAYS))
    db.add(session)
    db.flush()
    return session


@router.post("/register", response_model=AuthResponse, status_code=201)
def register(body: RegisterRequest, db: Annotated[Session, Depends(get_db)]) -> AuthResponse:
    """Creates a new organization and its first user (role=owner) together
    -- there's no separate "create an org" step, and no invite-a-teammate
    flow yet (Phase 2 scope, not asked for here). This replaces the old
    GET /api/dashboard/organization "get-or-create a single dev org" hack
    from Phase 1, which is incompatible with real multi-tenant auth by
    construction.
    """
    existing = db.query(User).filter(User.email == body.email).first()
    if existing is not None:
        raise HTTPException(
            status_code=409, detail={"code": "email_taken", "message": "An account with this email already exists."}
        )
    if len(body.password) < MIN_PASSWORD_LENGTH:
        raise HTTPException(
            status_code=422,
            detail={"code": "weak_password", "message": f"Password must be at least {MIN_PASSWORD_LENGTH} characters."},
        )

    org = Organization(name=body.org_name, account_type=AccountType.organizer)
    db.add(org)
    db.flush()

    user = User(org_id=org.id, email=body.email, password_hash=hash_password(body.password), role=UserRole.owner)
    db.add(user)
    db.flush()

    session = _create_session(db, user)
    db.commit()
    return AuthResponse(session_token=session.token, user=_user_public(user))


@router.post("/login", response_model=AuthResponse)
def login(body: LoginRequest, db: Annotated[Session, Depends(get_db)]) -> AuthResponse:
    user = db.query(User).filter(User.email == body.email).first()
    # Identical error for "no such user" and "wrong password" -- a login
    # attempt must not reveal whether an email is registered.
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(
            status_code=401, detail={"code": "invalid_credentials", "message": "Incorrect email or password."}
        )

    session = _create_session(db, user)
    db.commit()
    return AuthResponse(session_token=session.token, user=_user_public(user))


@router.post("/logout", status_code=204, response_model=None)
def logout(
    db: Annotated[Session, Depends(get_db)],
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[len("bearer ") :].strip()
        db.query(UserSession).filter(UserSession.token == token).delete()
        db.commit()


@router.get("/me", response_model=UserPublic)
def me(user: Annotated[User, Depends(get_current_user)]) -> UserPublic:
    return _user_public(user)
