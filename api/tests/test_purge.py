from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from app.models.audit_log import AuditLog
from app.models.event import Event
from app.models.guest import Guest
from app.models.guest_face import GuestFace
from app.models.match import Match
from app.models.photo import Photo
from app.workers.purge import PURGE_ADVISORY_LOCK_KEY, run_purge
from tests.factories import in_days, make_event, make_face, make_organization, make_photo, now_utc


def _make_guest(db, event, token) -> Guest:
    guest = Guest(event_id=event.id, consent_at=now_utc(), session_token=token)
    db.add(guest)
    db.flush()
    return guest


def test_purge_deletes_expired_guest_faces_and_leaves_others_untouched(db_session):
    org = make_organization(db_session)
    event = make_event(db_session, org)

    expired_guest = _make_guest(db_session, event, "tok-expired-face")
    db_session.add(GuestFace(guest_id=expired_guest.id, embedding=[0.01] * 512, expires_at=now_utc() - timedelta(days=1)))

    live_guest = _make_guest(db_session, event, "tok-live-face")
    db_session.add(GuestFace(guest_id=live_guest.id, embedding=[0.02] * 512, expires_at=in_days(10)))
    db_session.flush()

    report = run_purge(db=db_session, dry_run=False)

    assert report.ran is True
    assert report.guest_faces_deleted == 1

    remaining = db_session.query(GuestFace).all()
    assert len(remaining) == 1
    assert remaining[0].guest_id == live_guest.id

    entries = db_session.query(AuditLog).filter(AuditLog.action == "purge_expired_guest_faces").all()
    assert len(entries) == 1
    assert entries[0].meta["count"] == 1


def test_purge_deletes_event_data_and_minio_objects_past_retention(db_session):
    org = make_organization(db_session)

    expired_event = make_event(db_session, org, name_en="Expired Event")
    expired_event.retention_until = now_utc() - timedelta(days=1)

    live_event = make_event(db_session, org, name_en="Live Event")
    live_event.retention_until = in_days(30)
    db_session.flush()

    expired_photo = make_photo(db_session, expired_event)
    make_face(db_session, expired_photo, [0.03] * 512)
    expired_guest = _make_guest(db_session, expired_event, "tok-in-expired-event")
    db_session.add(Match(guest_id=expired_guest.id, photo_id=expired_photo.id, score=0.5))

    live_photo = make_photo(db_session, live_event)
    make_face(db_session, live_photo, [0.04] * 512)
    live_guest = _make_guest(db_session, live_event, "tok-in-live-event")
    db_session.add(Match(guest_id=live_guest.id, photo_id=live_photo.id, score=0.5))
    db_session.flush()

    expired_keys = {expired_photo.s3_key_original, expired_photo.s3_key_thumbnail, expired_photo.s3_key_preview}

    # Captured before run_purge(): the expired_* objects get hard-deleted
    # by it, and SQLAlchemy expires all identity-map objects on commit --
    # accessing an attribute on one whose row is now gone raises
    # ObjectDeletedError instead of returning the (still perfectly valid
    # to use in a filter) id it had a moment ago.
    expired_event_id = expired_event.id
    expired_guest_id = expired_guest.id
    live_event_id = live_event.id
    live_guest_id = live_guest.id

    with patch("app.workers.purge.minio_client.delete_objects", return_value=[]) as mock_delete:
        report = run_purge(db=db_session, dry_run=False)

    assert report.ran is True
    assert len(report.events) == 1
    result = report.events[0]
    assert result.event_id == expired_event_id
    assert result.photos_deleted == 1
    assert result.guests_deleted == 1
    assert result.minio_objects_deleted == 3

    mock_delete.assert_called_once()
    assert set(mock_delete.call_args[0][0]) == expired_keys

    # expired event's data gone
    assert db_session.query(Photo).filter(Photo.event_id == expired_event_id).count() == 0
    assert db_session.query(Guest).filter(Guest.event_id == expired_event_id).count() == 0
    assert db_session.query(Match).filter(Match.guest_id == expired_guest_id).count() == 0

    # live event's data untouched
    assert db_session.query(Photo).filter(Photo.event_id == live_event_id).count() == 1
    assert db_session.query(Guest).filter(Guest.event_id == live_event_id).count() == 1
    assert db_session.query(Match).filter(Match.guest_id == live_guest_id).count() == 1

    # the event row itself is retained -- only its data is purged
    assert db_session.get(Event, expired_event_id) is not None

    entries = db_session.query(AuditLog).filter(AuditLog.action == "purge_event_data").all()
    assert len(entries) == 1
    assert entries[0].subject == f"event:{expired_event_id}"
    assert entries[0].meta["photos_deleted"] == 1
    assert entries[0].meta["minio_objects_deleted"] == 3


def test_dry_run_reports_without_deleting_or_touching_minio(db_session):
    org = make_organization(db_session)
    event = make_event(db_session, org)
    event.retention_until = now_utc() - timedelta(days=1)
    db_session.flush()

    make_photo(db_session, event)
    guest = _make_guest(db_session, event, "tok-dry-run")
    db_session.add(GuestFace(guest_id=guest.id, embedding=[0.05] * 512, expires_at=now_utc() - timedelta(days=1)))
    db_session.flush()

    with patch("app.workers.purge.minio_client.delete_objects") as mock_delete:
        report = run_purge(db=db_session, dry_run=True)

    mock_delete.assert_not_called()
    assert report.dry_run is True
    assert report.ran is True
    assert report.guest_faces_deleted == 1
    assert len(report.events) == 1
    assert report.events[0].photos_deleted == 1
    assert report.events[0].minio_objects_deleted == 3

    # nothing actually deleted
    assert db_session.query(Photo).filter(Photo.event_id == event.id).count() == 1
    assert db_session.query(GuestFace).filter(GuestFace.guest_id == guest.id).count() == 1
    assert db_session.query(AuditLog).count() == 0


def test_purge_defers_db_deletion_when_minio_deletion_fails(db_session):
    org = make_organization(db_session)
    event = make_event(db_session, org)
    event.retention_until = now_utc() - timedelta(days=1)
    db_session.flush()
    photo = make_photo(db_session, event)
    db_session.flush()

    with patch("app.workers.purge.minio_client.delete_objects", return_value=[photo.s3_key_original]):
        report = run_purge(db=db_session, dry_run=False)

    # Not reported as purged, and critically the DB row survives -- an
    # orphaned MinIO object with no DB row left pointing at it would be
    # unrecoverable, so this event is retried whole on the next run.
    assert report.events == []
    assert db_session.query(Photo).filter(Photo.event_id == event.id).count() == 1
    assert db_session.query(AuditLog).filter(AuditLog.action == "purge_event_data").count() == 0


def test_purge_is_idempotent_second_run_finds_nothing(db_session):
    org = make_organization(db_session)
    event = make_event(db_session, org)
    event.retention_until = now_utc() - timedelta(days=1)
    db_session.flush()
    make_photo(db_session, event)
    db_session.flush()

    with patch("app.workers.purge.minio_client.delete_objects", return_value=[]):
        first = run_purge(db=db_session, dry_run=False)
        second = run_purge(db=db_session, dry_run=False)

    assert len(first.events) == 1
    assert second.events == []  # nothing left to report -- already purged
    assert second.guest_faces_deleted == 0


def test_advisory_lock_prevents_concurrent_purge_runs(db_session, engine):
    from sqlalchemy import text

    other_connection = engine.connect()
    other_connection.execute(text("SELECT pg_try_advisory_lock(:key)"), {"key": PURGE_ADVISORY_LOCK_KEY})
    try:
        report = run_purge(db=db_session, dry_run=False)
        assert report.ran is False
    finally:
        other_connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": PURGE_ADVISORY_LOCK_KEY})
        other_connection.commit()
        other_connection.close()
