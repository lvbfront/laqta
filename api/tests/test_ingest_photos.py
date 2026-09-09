from __future__ import annotations

import io
import uuid

from app.models.photo import Photo
from app.workers.queue import get_photo_processing_queue
from tests.factories import auth_headers, make_event, make_organization, make_user


def _upload(client, event_id, files, headers=None):
    return client.post(f"/api/events/{event_id}/photos", files=files, headers=headers)


def test_upload_creates_pending_photo_and_enqueues_job(client, db_session):
    org = make_organization(db_session)
    user = make_user(db_session, org)
    headers = auth_headers(db_session, user)
    event = make_event(db_session, org)

    resp = _upload(
        client, event.id, [("files", ("a.jpg", io.BytesIO(b"fake-jpeg-bytes-1"), "image/jpeg"))], headers
    )
    assert resp.status_code == 201
    body = resp.json()
    assert len(body["results"]) == 1
    result = body["results"][0]
    assert result["status"] == "queued"
    assert result["photo_id"] is not None

    photo = db_session.get(Photo, uuid.UUID(result["photo_id"]))
    assert photo is not None
    assert photo.event_id == event.id
    assert photo.status.value == "pending"
    assert photo.s3_key_original == f"events/{event.id}/photos/{photo.id}/original.jpg"

    queue = get_photo_processing_queue()
    assert queue.count >= 1


def test_duplicate_md5_within_event_is_not_reprocessed(client, db_session):
    org = make_organization(db_session)
    user = make_user(db_session, org)
    headers = auth_headers(db_session, user)
    event = make_event(db_session, org)
    content = b"identical-bytes-for-dedupe-test"

    first = _upload(client, event.id, [("files", ("a.jpg", io.BytesIO(content), "image/jpeg"))], headers)
    second = _upload(
        client, event.id, [("files", ("a-reupload.jpg", io.BytesIO(content), "image/jpeg"))], headers
    )

    first_result = first.json()["results"][0]
    second_result = second.json()["results"][0]

    assert first_result["status"] == "queued"
    assert second_result["status"] == "duplicate"
    assert second_result["duplicate_of"] == first_result["photo_id"]

    count = db_session.query(Photo).filter(Photo.event_id == event.id).count()
    assert count == 1


def test_same_bytes_different_events_are_not_deduped(client, db_session):
    # MD5 dedupe is scoped per event (uq_photos_event_md5) -- the same
    # photographer shooting two events with overlapping test/calibration
    # frames shouldn't have the second event silently drop a real upload.
    org = make_organization(db_session)
    user = make_user(db_session, org)
    headers = auth_headers(db_session, user)
    event_a = make_event(db_session, org, name_en="Event A")
    event_b = make_event(db_session, org, name_en="Event B")
    content = b"same-bytes-different-events"

    resp_a = _upload(client, event_a.id, [("files", ("a.jpg", io.BytesIO(content), "image/jpeg"))], headers)
    resp_b = _upload(client, event_b.id, [("files", ("a.jpg", io.BytesIO(content), "image/jpeg"))], headers)

    assert resp_a.json()["results"][0]["status"] == "queued"
    assert resp_b.json()["results"][0]["status"] == "queued"


def test_batch_upload_multiple_distinct_files(client, db_session):
    org = make_organization(db_session)
    user = make_user(db_session, org)
    headers = auth_headers(db_session, user)
    event = make_event(db_session, org)

    resp = _upload(
        client,
        event.id,
        [
            ("files", ("a.jpg", io.BytesIO(b"content-a"), "image/jpeg")),
            ("files", ("b.jpg", io.BytesIO(b"content-b"), "image/jpeg")),
            ("files", ("c.jpg", io.BytesIO(b"content-c"), "image/jpeg")),
        ],
        headers,
    )
    assert resp.status_code == 201
    results = resp.json()["results"]
    assert len(results) == 3
    assert all(r["status"] == "queued" for r in results)
    assert len({r["photo_id"] for r in results}) == 3


def test_upload_to_nonexistent_event_returns_404(client, db_session):
    # A real (but unaffiliated) authenticated user -- require_event_access
    # 404s regardless of role once the event itself doesn't resolve.
    user = make_user(db_session)
    headers = auth_headers(db_session, user)
    resp = _upload(client, uuid.uuid4(), [("files", ("a.jpg", io.BytesIO(b"x"), "image/jpeg"))], headers)
    assert resp.status_code == 404


def test_upload_without_auth_is_rejected(client, db_session):
    org = make_organization(db_session)
    event = make_event(db_session, org)
    resp = _upload(client, event.id, [("files", ("a.jpg", io.BytesIO(b"x"), "image/jpeg"))])
    assert resp.status_code == 401
