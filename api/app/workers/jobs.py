from __future__ import annotations

import logging
import uuid

from app.db import SessionLocal
from app.models.enums import MatchMode, PhotoStatus
from app.models.face import Face
from app.models.photo import Photo
from app.storage import minio_client
from app.workers.pipeline import process_photo_bytes
from app.workers.purge import run_purge

logger = logging.getLogger(__name__)


def process_photo(photo_id: str) -> None:
    """RQ job: fetch the raw-uploaded original from MinIO, run the
    detection/embedding pipeline, overwrite s3_key_original with the
    re-encoded (autorotated, GPS/EXIF-stripped) version, write the
    thumbnail/preview derivatives, insert faces rows, and flip the photo to
    'ready' (or 'failed'). One job per photo, enqueued by the ingest
    endpoint right after the DB row + raw original upload -- no image
    processing happens in the request handler itself.

    The raw upload can carry GPS EXIF between upload and this job running;
    that's fine because nothing exposes a photo before status='ready', and
    by the time this job sets that, s3_key_original has already been
    overwritten with the stripped version -- no guest-reachable state ever
    has GPS in it.
    """
    db = SessionLocal()
    try:
        photo = db.get(Photo, uuid.UUID(photo_id))
        if photo is None:
            logger.warning("process_photo: photo %s not found, skipping", photo_id)
            return
        if photo.status != PhotoStatus.pending:
            # Already processed (or in flight) -- avoids double-inserting
            # faces if a job is retried/redelivered.
            logger.info("process_photo: photo %s is %s, not pending, skipping", photo_id, photo.status)
            return

        try:
            original_bytes = minio_client.download_bytes(photo.s3_key_original)
            # See pipeline.process_photo_bytes' docstring: a code-mode
            # event never runs face detection on its photos at all, not
            # just "doesn't use the result".
            run_face_detection = photo.event.match_mode != MatchMode.code
            result = process_photo_bytes(original_bytes, run_face_detection=run_face_detection)

            thumbnail_key = minio_client.derived_key(photo.s3_key_original, "thumbnail")
            preview_key = minio_client.derived_key(photo.s3_key_original, "preview")
            # Overwrite the raw upload -- see the GPS/EXIF note in this
            # function's docstring. Same key, not a derived one: there is
            # only ever one "original" object for a photo.
            minio_client.upload_bytes(photo.s3_key_original, result.original_jpeg, "image/jpeg")
            minio_client.upload_bytes(thumbnail_key, result.thumbnail_jpeg, "image/jpeg")
            minio_client.upload_bytes(preview_key, result.preview_jpeg, "image/jpeg")

            for face in result.faces:
                x1, y1, x2, y2 = face.bbox
                db.add(
                    Face(
                        photo_id=photo.id,
                        event_id=photo.event_id,
                        bbox_x1=x1,
                        bbox_y1=y1,
                        bbox_x2=x2,
                        bbox_y2=y2,
                        det_score=face.det_score,
                        embedding=face.embedding,
                    )
                )

            photo.s3_key_thumbnail = thumbnail_key
            photo.s3_key_preview = preview_key
            photo.width = result.width
            photo.height = result.height
            photo.captured_at = result.captured_at
            photo.status = PhotoStatus.ready
            # Strict-mode events force auto_publish=false (DB check
            # constraint + enforced again here): a photo only becomes
            # visible to guests once a moderator explicitly approves it.
            # See CLAUDE.md -- a strict event must never auto-expose a photo.
            photo.published = bool(photo.event.auto_publish)

            db.commit()
        except Exception:
            db.rollback()
            photo = db.get(Photo, uuid.UUID(photo_id))
            if photo is not None:
                photo.status = PhotoStatus.failed
                db.commit()
            logger.exception("process_photo: failed for photo %s", photo_id)
            raise
    finally:
        db.close()


def purge_expired_data() -> None:
    """RQ job for the 'purge' queue (see docker-compose.yml's worker
    command). Actually *scheduling* this periodically -- cron, rq-scheduler,
    a platform's own scheduled-job feature -- is a deployment concern not
    wired up yet; this is the job body to point that at. See
    scripts/purge.py for a manual/cron-friendly CLI with --dry-run.
    """
    report = run_purge(dry_run=False)
    if not report.ran:
        logger.warning("purge_expired_data: skipped -- another purge run holds the advisory lock")
        return
    logger.info(
        "purge_expired_data: deleted %d expired guest_faces row(s); purged data for %d event(s): %s",
        report.guest_faces_deleted,
        len(report.events),
        [str(r.event_id) for r in report.events],
    )
