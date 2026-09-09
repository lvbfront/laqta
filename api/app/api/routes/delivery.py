from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.utils import client_ip
from app.config import settings
from app.db import get_db
from app.models.audit_log import AuditLog
from app.models.download import Download
from app.models.enums import MatchFeedback
from app.models.guest import Guest
from app.models.match import Match
from app.models.photo import Photo
from app.storage import minio_client

router = APIRouter(prefix="/api/guest", tags=["delivery"])


class SignedUrlResponse(BaseModel):
    url: str
    expires_in_seconds: int


def _current_guest(
    db: Annotated[Session, Depends(get_db)],
    authorization: Annotated[str | None, Header()] = None,
) -> Guest:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail={"code": "missing_session", "message": "Guest session required."})
    token = authorization[len("bearer ") :].strip()
    guest = db.query(Guest).filter(Guest.session_token == token).first()
    if guest is None:
        raise HTTPException(status_code=401, detail={"code": "invalid_session", "message": "Invalid or expired guest session."})
    return guest


@router.get("/photos/{photo_id}/url", response_model=SignedUrlResponse)
def get_signed_photo_url(
    photo_id: uuid.UUID,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    guest: Annotated[Guest, Depends(_current_guest)],
    variant: Literal["preview", "original"] = "preview",
) -> SignedUrlResponse:
    """A guest session token scopes every URL this issues: the only
    question that matters is "does a Match row connect this guest to this
    photo" -- not the photo's event, not its moderation state beyond that,
    nothing else. That single check is what makes a photo from a
    different event, or one the guest never matched (including a below-
    threshold candidate that consequently never got a Match row in the
    first place -- see app/api/routes/match.py), come back 404 rather than
    ever being enumerable. See tests/test_delivery_scoping.py.
    """
    photo = db.get(Photo, photo_id)
    if photo is None:
        raise HTTPException(status_code=404, detail={"code": "photo_not_found", "message": "Photo not found."})

    match = db.query(Match).filter(Match.guest_id == guest.id, Match.photo_id == photo_id).first()
    # published is checked again here, not just trusted from match-time --
    # a future moderation action could unpublish a photo after it was
    # matched, and this must revoke delivery immediately, not just future
    # matching (CLAUDE.md: strict-mode events must never return an
    # unapproved photo).
    if match is None or not photo.published:
        raise HTTPException(status_code=404, detail={"code": "photo_not_found", "message": "Photo not found."})

    key = photo.s3_key_preview if variant == "preview" else photo.s3_key_original
    url = minio_client.presigned_get_url(key, settings.signed_url_ttl_seconds)

    db.add(
        Download(
            guest_id=guest.id,
            photo_id=photo.id,
            ip=client_ip(request),
        )
    )
    db.commit()

    return SignedUrlResponse(url=url, expires_in_seconds=settings.signed_url_ttl_seconds)


class FeedbackResponse(BaseModel):
    photo_id: uuid.UUID
    feedback: str


def _guest_match_or_404(db: Session, guest: Guest, photo_id: uuid.UUID) -> Match:
    match = db.query(Match).filter(Match.guest_id == guest.id, Match.photo_id == photo_id).first()
    if match is None:
        raise HTTPException(status_code=404, detail={"code": "photo_not_found", "message": "Photo not found."})
    return match


@router.post("/matches/{photo_id}/not-me", response_model=FeedbackResponse)
def report_not_me(
    photo_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    guest: Annotated[Guest, Depends(_current_guest)],
) -> FeedbackResponse:
    """Feedback signal only -- doesn't remove the photo from anyone's
    matches (it's presumably someone else's correct match), just records
    that this guest says it isn't them. Same 404-if-no-Match scoping as
    every other guest-facing endpoint here.
    """
    match = _guest_match_or_404(db, guest, photo_id)
    match.feedback = MatchFeedback.not_me
    db.commit()
    return FeedbackResponse(photo_id=photo_id, feedback=match.feedback.value)


@router.post("/matches/{photo_id}/remove", response_model=FeedbackResponse)
def request_photo_removal(
    photo_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    guest: Annotated[Guest, Depends(_current_guest)],
) -> FeedbackResponse:
    """"Remove this photo of me": unlike not-me, this hides the photo
    globally, not just for the requesting guest -- the person asking is
    asserting they're identifiable in it and don't want it shown to
    *anyone*. Reuses the existing published gate (the same one match/
    delivery already enforce for moderation) rather than a parallel
    mechanism: setting published=False here takes effect immediately and
    everywhere those checks already run.
    """
    match = _guest_match_or_404(db, guest, photo_id)
    match.feedback = MatchFeedback.remove_requested

    photo = db.get(Photo, photo_id)
    if photo is not None:
        photo.published = False

    db.add(
        AuditLog(
            actor=f"guest:{guest.id}",
            action="remove_requested",
            subject=f"photo:{photo_id}",
            meta={"event_id": str(guest.event_id)},
        )
    )
    db.commit()
    return FeedbackResponse(photo_id=photo_id, feedback=match.feedback.value)
