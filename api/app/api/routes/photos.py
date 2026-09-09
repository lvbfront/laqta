from __future__ import annotations

import hashlib
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.enums import PhotoStatus
from app.models.event import Event
from app.models.photo import Photo
from app.storage import minio_client
from app.workers.jobs import process_photo
from app.workers.queue import get_photo_processing_queue

router = APIRouter(prefix="/api/events/{event_id}/photos", tags=["photos"])


class PhotoUploadResult(BaseModel):
    filename: str
    status: str  # "queued" | "duplicate" | "error"
    photo_id: uuid.UUID | None = None
    duplicate_of: uuid.UUID | None = None
    error: str | None = None


class PhotoBatchUploadResponse(BaseModel):
    results: list[PhotoUploadResult]


def _original_key(event_id: uuid.UUID, photo_id: uuid.UUID) -> str:
    return f"events/{event_id}/photos/{photo_id}/original.jpg"


def _find_by_md5(db: Session, event_id: uuid.UUID, md5: str) -> Photo | None:
    return db.query(Photo).filter(Photo.event_id == event_id, Photo.md5 == md5).first()


@router.post("", response_model=PhotoBatchUploadResponse, status_code=201)
async def upload_photos(
    event_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    files: Annotated[list[UploadFile], File(...)],
) -> PhotoBatchUploadResponse:
    """Batch photo ingest. No image processing happens here -- cameras
    send bursts and this must stay fast: read bytes, MD5 dedupe, write the
    raw upload straight to MinIO, insert a 'pending' photos row, enqueue
    the worker job, move to the next file. All actual image work (EXIF,
    thumbnailing, face detection/embedding, and re-stripping the original
    of GPS) happens in app.workers.jobs.process_photo.
    """
    event = db.get(Event, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")

    queue = get_photo_processing_queue()
    results: list[PhotoUploadResult] = []

    for upload in files:
        filename = upload.filename or "unnamed"
        try:
            content = await upload.read()
            if not content:
                results.append(PhotoUploadResult(filename=filename, status="error", error="empty file"))
                continue

            md5 = hashlib.md5(content).hexdigest()

            # Fast-path dedupe check -- avoids an unnecessary MinIO upload
            # in the common case. The DB-level uq_photos_event_md5
            # constraint (caught below) is what actually guarantees
            # correctness under concurrent uploads of the same file.
            existing = _find_by_md5(db, event_id, md5)
            if existing is not None:
                results.append(
                    PhotoUploadResult(filename=filename, status="duplicate", duplicate_of=existing.id)
                )
                continue

            photo = Photo(event_id=event_id, s3_key_original="pending", md5=md5, status=PhotoStatus.pending)
            db.add(photo)
            try:
                db.flush()  # assigns photo.id, and is where the unique constraint fires
            except IntegrityError:
                db.rollback()
                existing = _find_by_md5(db, event_id, md5)
                results.append(
                    PhotoUploadResult(filename=filename, status="duplicate", duplicate_of=existing.id if existing else None)
                )
                continue

            key = _original_key(event_id, photo.id)
            photo.s3_key_original = key
            minio_client.upload_bytes(key, content, upload.content_type or "image/jpeg")
            db.commit()

            queue.enqueue(process_photo, str(photo.id))

            results.append(PhotoUploadResult(filename=filename, status="queued", photo_id=photo.id))
        except Exception as exc:  # noqa: BLE001 -- one bad file must not sink the rest of the batch
            db.rollback()
            results.append(PhotoUploadResult(filename=filename, status="error", error=str(exc)))

    return PhotoBatchUploadResponse(results=results)
