from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models.audit_log import AuditLog
from app.models.event import Event
from app.models.guest import Guest
from app.models.guest_face import GuestFace
from app.models.photo import Photo
from app.storage import minio_client

logger = logging.getLogger(__name__)

# Arbitrary but stable key for this job's Postgres session-level advisory
# lock. A concurrent purge run (manual + scheduled overlapping, more than
# one worker) must not do the deletion work twice or race on the same
# rows -- pg_try_advisory_lock is non-blocking, so a second run just
# reports "skipped" and exits rather than piling up waiting.
PURGE_ADVISORY_LOCK_KEY = 727271001


@dataclass(frozen=True)
class EventPurgeResult:
    event_id: uuid.UUID
    photos_deleted: int
    minio_objects_deleted: int
    guests_deleted: int


@dataclass
class PurgeReport:
    dry_run: bool
    ran: bool  # False only if another purge run held the advisory lock
    guest_faces_deleted: int = 0
    events: list[EventPurgeResult] = field(default_factory=list)


def _collect_photo_keys(photos: list[Photo]) -> list[str]:
    keys: list[str] = []
    for photo in photos:
        for key in (photo.s3_key_original, photo.s3_key_thumbnail, photo.s3_key_preview):
            if key:
                keys.append(key)
    return keys


def _purge_event(db: Session, event: Event, *, dry_run: bool) -> EventPurgeResult | None:
    photos = db.query(Photo).filter(Photo.event_id == event.id).all()
    guests = db.query(Guest).filter(Guest.event_id == event.id).all()

    if not photos and not guests:
        return None  # already purged (or never had data) -- stay quiet, keeps this idempotent

    keys = _collect_photo_keys(photos)

    if dry_run:
        return EventPurgeResult(
            event_id=event.id, photos_deleted=len(photos), minio_objects_deleted=len(keys), guests_deleted=len(guests)
        )

    # MinIO first, DB rows second -- on purpose. If a MinIO object fails to
    # delete and we'd already deleted the DB row pointing at it, that
    # object becomes permanently unreachable from any query: an orphaned
    # original sitting in object storage that PDPL retention says should
    # be gone, with no way to find it again. Keeping the DB row means the
    # next scheduled run's photo query finds it and retries -- safe,
    # because S3/MinIO delete is idempotent (re-deleting an
    # already-deleted key is a no-op, not an error).
    failed = minio_client.delete_objects(keys)
    if failed:
        logger.error(
            "purge: event %s -- %d/%d MinIO object(s) failed to delete, deferring DB deletion to next run: %s",
            event.id, len(failed), len(keys), failed,
        )
        return None

    db.add(
        AuditLog(
            actor="system:purge",
            action="purge_event_data",
            subject=f"event:{event.id}",
            meta={
                "photos_deleted": len(photos),
                "guests_deleted": len(guests),
                "minio_objects_deleted": len(keys),
                "retention_until": event.retention_until.isoformat() if event.retention_until else None,
            },
        )
    )

    # Plain bulk DELETEs -- Postgres's own ON DELETE CASCADE (faces via
    # photos; guest_faces/matches/downloads via guests) handles the rest
    # at the DB layer, independent of SQLAlchemy's ORM-level cascade
    # settings. The Event row itself is deliberately NOT deleted: it's
    # organizational metadata (name, dates), not personal/biometric data,
    # and an organizer dashboard can still show "this event's data was
    # purged on schedule" against it.
    db.query(Photo).filter(Photo.event_id == event.id).delete(synchronize_session=False)
    db.query(Guest).filter(Guest.event_id == event.id).delete(synchronize_session=False)

    return EventPurgeResult(
        event_id=event.id, photos_deleted=len(photos), minio_objects_deleted=len(keys), guests_deleted=len(guests)
    )


def run_purge(*, db: Session | None = None, dry_run: bool = False) -> PurgeReport:
    """Hard-delete expired guest_faces vectors and, for events past
    retention_until, all of that event's photos/faces/guests/matches/
    downloads plus the corresponding MinIO objects. Never a soft-delete
    flag -- an expired guest_faces row is gone, not marked expired.

    Pass `db` to reuse an existing session (tests do this, to stay inside
    the same rollback-isolated transaction as the rest of the test); the
    RQ job and CLI leave it unset and get their own short-lived session.
    """
    owns_session = db is None
    if db is None:
        db = SessionLocal()

    try:
        got_lock = db.execute(text("SELECT pg_try_advisory_lock(:key)"), {"key": PURGE_ADVISORY_LOCK_KEY}).scalar()
        if not got_lock:
            logger.warning("purge: another purge run holds the advisory lock, skipping")
            return PurgeReport(dry_run=dry_run, ran=False)

        try:
            now = datetime.now(timezone.utc)

            expired_faces = db.query(GuestFace).filter(GuestFace.expires_at < now).all()
            guest_faces_count = len(expired_faces)

            # retention_until is NOT NULL (see app/models/event.py) -- no
            # IS NOT NULL guard needed; every event is eligible for this
            # comparison, not just ones that happened to have a value set.
            expired_events = db.query(Event).filter(Event.retention_until < now).all()

            event_results = [
                result
                for event in expired_events
                if (result := _purge_event(db, event, dry_run=dry_run)) is not None
            ]

            if not dry_run and guest_faces_count:
                # Written before the DELETE, in the same transaction they
                # commit together in: audit_log has no FK to guest_faces
                # (see app/models/audit_log.py) specifically so this entry
                # remains valid evidence after the row it describes is gone.
                db.add(
                    AuditLog(
                        actor="system:purge",
                        action="purge_expired_guest_faces",
                        subject="guest_faces",
                        meta={"count": guest_faces_count},
                    )
                )
                db.query(GuestFace).filter(GuestFace.expires_at < now).delete(synchronize_session=False)

            if not dry_run:
                # Unconditional -- one row per invocation, even (especially)
                # when nothing was deleted. Without this, a scheduler that's
                # silently stopped firing looks identical to one firing
                # daily and finding nothing to do: both leave zero trace.
                # This is what actually lets anyone confirm retention is
                # being enforced, not just that the code to enforce it
                # exists. The per-category entries above are additional
                # detail, not a substitute -- they only appear when there
                # was something to report.
                db.add(
                    AuditLog(
                        actor="system:purge",
                        action="purge_run",
                        subject="system",
                        meta={
                            "guest_faces_deleted": guest_faces_count,
                            "events_purged": len(event_results),
                            "event_ids": [str(r.event_id) for r in event_results],
                        },
                    )
                )
                db.commit()
            # dry_run performs no db.add()/.delete() at all above (see the
            # early return in _purge_event and the `not dry_run` guard on
            # the guest_faces delete) -- there is nothing to roll back, so
            # this deliberately doesn't call db.rollback() here. It used
            # to, defensively; that turned out to be actively wrong under
            # a session joined to an external transaction (the pattern
            # tests/conftest.py uses for isolation): a rollback() with no
            # prior commit() on such a session can unwind past this
            # function's own no-op work and back into the caller's
            # transaction, discarding state the caller flushed before
            # calling run_purge(). Caught by
            # test_dry_run_reports_without_deleting_or_touching_minio.

            return PurgeReport(dry_run=dry_run, ran=True, guest_faces_deleted=guest_faces_count, events=event_results)
        finally:
            db.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": PURGE_ADVISORY_LOCK_KEY})
            db.commit()
    finally:
        if owns_session:
            db.close()
