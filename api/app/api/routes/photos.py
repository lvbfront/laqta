from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import require_event_access, require_role
from app.config import settings
from app.db import get_db
from app.models.audit_log import AuditLog
from app.models.enums import PhotoStatus, UserRole
from app.models.event import Event
from app.models.photo import Photo
from app.models.photo_code import PhotoCode
from app.models.user import User
from app.services.ingest import ingest_photo
from app.storage import minio_client

router = APIRouter(prefix="/api/events/{event_id}/photos", tags=["photos"])

# Who may do what to an event's photos. Ingest includes 'photographer'
# (cameras/staff pushing bursts, not just owner/staff); moderation and
# code-tagging are staff-review actions, so 'photographer' is deliberately
# left out of those two.
INGEST_ROLES = (UserRole.owner, UserRole.staff, UserRole.photographer)
MODERATE_ROLES = (UserRole.owner, UserRole.staff, UserRole.moderator)


class PhotoUploadResult(BaseModel):
    filename: str
    status: str  # "queued" | "duplicate" | "error"
    photo_id: uuid.UUID | None = None
    duplicate_of: uuid.UUID | None = None
    error: str | None = None


class PhotoBatchUploadResponse(BaseModel):
    results: list[PhotoUploadResult]


@router.post("", response_model=PhotoBatchUploadResponse, status_code=201)
async def upload_photos(
    db: Annotated[Session, Depends(get_db)],
    event: Annotated[Event, Depends(require_event_access)],
    _role: Annotated[User, Depends(require_role(*INGEST_ROLES))],
    files: Annotated[list[UploadFile], File(...)],
) -> PhotoBatchUploadResponse:
    """Batch photo ingest over REST -- see app/services/ingest.py for the
    actual dedupe/MinIO/enqueue logic, shared with the FTPS path
    (app/ftps/handler.py). No image processing happens here: reading the
    upload and handing bytes to ingest_photo() is all this does, so
    bursts stay fast.
    """
    results: list[PhotoUploadResult] = []

    for upload in files:
        filename = upload.filename or "unnamed"
        try:
            content = await upload.read()
            result = ingest_photo(db, event.id, content, upload.content_type or "image/jpeg")
            results.append(
                PhotoUploadResult(
                    filename=filename,
                    status=result.status,
                    photo_id=result.photo_id,
                    duplicate_of=result.duplicate_of,
                    error=result.error,
                )
            )
        except Exception as exc:  # noqa: BLE001 -- one bad file must not sink the rest of the batch
            db.rollback()
            results.append(PhotoUploadResult(filename=filename, status="error", error=str(exc)))

    return PhotoBatchUploadResponse(results=results)


class PhotoListItem(BaseModel):
    id: uuid.UUID
    status: str
    published: bool
    thumbnail_url: str | None
    codes: list[str]
    created_at: datetime


@router.get("", response_model=list[PhotoListItem])
def list_photos(
    db: Annotated[Session, Depends(get_db)],
    event: Annotated[Event, Depends(require_event_access)],
    status: str | None = None,
) -> list[PhotoListItem]:
    """Dashboard-side listing (photo grid, moderation queue). Any
    authenticated member of the event's org can view -- `?status=pending`
    is what the moderation queue uses.
    """
    query = db.query(Photo).filter(Photo.event_id == event.id)
    if status:
        query = query.filter(Photo.status == status)
    photos = query.order_by(Photo.created_at.desc()).limit(500).all()

    items = []
    for photo in photos:
        thumb_url = (
            minio_client.presigned_get_url(photo.s3_key_thumbnail, settings.signed_url_ttl_seconds)
            if photo.s3_key_thumbnail
            else None
        )
        items.append(
            PhotoListItem(
                id=photo.id,
                status=photo.status.value,
                published=photo.published,
                thumbnail_url=thumb_url,
                codes=[c.code for c in photo.codes],
                created_at=photo.created_at,
            )
        )
    return items


class ModerationResult(BaseModel):
    id: uuid.UUID
    status: str
    published: bool


@router.post("/{photo_id}/moderate", response_model=ModerationResult)
def moderate_photo(
    photo_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    event: Annotated[Event, Depends(require_event_access)],
    user: Annotated[User, Depends(require_role(*MODERATE_ROLES))],
    action: Literal["approve", "reject"],
) -> ModerationResult:
    photo = db.query(Photo).filter(Photo.id == photo_id, Photo.event_id == event.id).first()
    if photo is None:
        raise HTTPException(status_code=404, detail={"code": "photo_not_found", "message": "Photo not found."})
    if photo.status != PhotoStatus.ready:
        raise HTTPException(
            status_code=409,
            detail={"code": "photo_not_ready", "message": "Photo hasn't finished processing yet."},
        )

    photo.published = action == "approve"
    photo.moderated_by = user.id
    photo.moderated_at = datetime.now(timezone.utc)
    db.add(
        AuditLog(
            actor=f"user:{user.id}",
            action=f"moderate_{action}",
            subject=f"photo:{photo.id}",
            meta={"event_id": str(event.id)},
        )
    )
    db.commit()

    return ModerationResult(id=photo.id, status=photo.status.value, published=photo.published)


class AddCodeRequest(BaseModel):
    code: str


class PhotoCodesResult(BaseModel):
    photo_id: uuid.UUID
    codes: list[str]


@router.post("/{photo_id}/codes", response_model=PhotoCodesResult, status_code=201)
def add_photo_code(
    photo_id: uuid.UUID,
    body: AddCodeRequest,
    db: Annotated[Session, Depends(get_db)],
    event: Annotated[Event, Depends(require_event_access)],
    _role: Annotated[User, Depends(require_role(*MODERATE_ROLES))],
) -> PhotoCodesResult:
    """Manually tags a bib/badge/wristband code onto a photo -- what
    match_mode='code' matches against (see app/api/routes/match.py's
    match_by_code). There's no OCR: staff enter the code themselves,
    typically while moderating. Idempotent -- re-tagging the same code is
    a no-op, not an error (uq_photo_codes_photo_code).
    """
    photo = db.query(Photo).filter(Photo.id == photo_id, Photo.event_id == event.id).first()
    if photo is None:
        raise HTTPException(status_code=404, detail={"code": "photo_not_found", "message": "Photo not found."})

    code = body.code.strip()
    if not code:
        raise HTTPException(status_code=422, detail={"code": "empty_code", "message": "Code cannot be empty."})

    existing = db.query(PhotoCode).filter(PhotoCode.photo_id == photo_id, PhotoCode.code == code).first()
    if existing is None:
        db.add(PhotoCode(photo_id=photo_id, code=code))
        db.commit()
        db.refresh(photo)

    return PhotoCodesResult(photo_id=photo.id, codes=[c.code for c in photo.codes])


@router.delete("/{photo_id}/codes/{code}", response_model=PhotoCodesResult)
def remove_photo_code(
    photo_id: uuid.UUID,
    code: str,
    db: Annotated[Session, Depends(get_db)],
    event: Annotated[Event, Depends(require_event_access)],
    _role: Annotated[User, Depends(require_role(*MODERATE_ROLES))],
) -> PhotoCodesResult:
    photo = db.query(Photo).filter(Photo.id == photo_id, Photo.event_id == event.id).first()
    if photo is None:
        raise HTTPException(status_code=404, detail={"code": "photo_not_found", "message": "Photo not found."})

    db.query(PhotoCode).filter(PhotoCode.photo_id == photo_id, PhotoCode.code == code).delete()
    db.commit()
    db.refresh(photo)

    return PhotoCodesResult(photo_id=photo.id, codes=[c.code for c in photo.codes])
