from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.enums import MatchMode, PhotoStatus
from app.models.event import Event
from app.models.photo import Photo
from app.models.photo_code import PhotoCode
from app.storage import minio_client
from app.workers.jobs import process_photo
from app.workers.queue import get_photo_processing_queue


@dataclass(frozen=True)
class IngestResult:
    status: str  # "queued" | "duplicate" | "error"
    photo_id: uuid.UUID | None = None
    duplicate_of: uuid.UUID | None = None
    error: str | None = None


def _original_key(event_id: uuid.UUID, photo_id: uuid.UUID) -> str:
    return f"events/{event_id}/photos/{photo_id}/original.jpg"


def _find_by_md5(db: Session, event_id: uuid.UUID, md5: str) -> Photo | None:
    return db.query(Photo).filter(Photo.event_id == event_id, Photo.md5 == md5).first()


def ingest_photo(db: Session, event_id: uuid.UUID, content: bytes, content_type: str) -> IngestResult:
    """One photo, from raw bytes to a queued worker job. Shared by the REST
    ingest endpoint (app/api/routes/photos.py) and the FTPS handler
    (app/ftps/handler.py) -- cameras push over FTPS, browsers/scripts push
    over REST, but from here on it's the identical dedupe/MinIO/enqueue
    path either way. No image processing here -- see
    app.workers.jobs.process_photo for that (this function must stay fast;
    camera FTP queues and REST batch uploads both send bursts).
    """
    if not content:
        return IngestResult(status="error", error="empty file")

    md5 = hashlib.md5(content).hexdigest()

    # Fast-path dedupe check -- avoids an unnecessary MinIO upload in the
    # common case. The DB-level uq_photos_event_md5 constraint (caught
    # below) is what actually guarantees correctness under concurrent
    # uploads of the same file.
    existing = _find_by_md5(db, event_id, md5)
    if existing is not None:
        return IngestResult(status="duplicate", duplicate_of=existing.id)

    photo = Photo(event_id=event_id, s3_key_original="pending", md5=md5, status=PhotoStatus.pending)
    db.add(photo)
    try:
        db.flush()  # assigns photo.id, and is where the unique constraint fires
    except IntegrityError:
        db.rollback()
        existing = _find_by_md5(db, event_id, md5)
        return IngestResult(status="duplicate", duplicate_of=existing.id if existing else None)

    key = _original_key(event_id, photo.id)
    photo.s3_key_original = key
    minio_client.upload_bytes(key, content, content_type)

    # match_mode='sequential' (a photo-booth: staff taps "next guest"
    # between subjects, app/api/routes/events.py's advance_solo_number) --
    # every photo that lands while a number is "open" gets auto-tagged
    # with it, so nobody ever has to type a code in by hand. NULL means no
    # "next guest" tap has happened yet (e.g. a stray upload before the
    # booth actually opened) -- left untagged rather than guessed at;
    # staff can still tag it manually via add_photo_code if needed.
    event = db.get(Event, event_id)
    if event is not None and event.match_mode == MatchMode.sequential and event.current_solo_number is not None:
        db.add(PhotoCode(photo_id=photo.id, code=str(event.current_solo_number)))

    db.commit()

    get_photo_processing_queue().enqueue(process_photo, str(photo.id))

    return IngestResult(status="queued", photo_id=photo.id)
