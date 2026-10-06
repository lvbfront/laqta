from __future__ import annotations

import uuid

from app.models.guest import Guest
from app.models.guest_face import GuestFace
from app.models.match import Match
from app.services.face_model import detect_and_embed
from tests import image_fixtures
from tests.factories import make_event, make_face, make_organization, make_photo


def _embedding_for_fixture_face() -> list[float]:
    img = image_fixtures.load_group_photo_bgr()
    faces = detect_and_embed(img)
    best = max(faces, key=lambda f: f.bbox_width * f.bbox_height)
    return best.embedding


def test_match_finds_published_photo_with_matching_face(client, db_session):
    org = make_organization(db_session)
    event = make_event(db_session, org)
    photo = make_photo(db_session, event, published=True)
    make_face(db_session, photo, _embedding_for_fixture_face())
    db_session.flush()

    selfie_bytes = image_fixtures.single_face_selfie_jpeg()
    resp = client.post(
        f"/api/events/{event.id}/match",
        files={"selfie": ("selfie.jpg", selfie_bytes, "image/jpeg")},
        data={"consent": "true"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["guest_session_token"]
    assert len(body["matches"]) == 1
    assert body["matches"][0]["photo_id"] == str(photo.id)
    assert body["matches"][0]["score"] >= 0.38

    guest = db_session.query(Guest).filter(Guest.session_token == body["guest_session_token"]).first()
    assert guest is not None
    assert guest.event_id == event.id
    # The selfie's embedding is used for this search and then dropped --
    # nothing selfie-derived is stored (a guest_faces row was never read again).
    assert db_session.query(GuestFace).count() == 0
    assert db_session.query(Match).filter(Match.guest_id == guest.id).count() == 1


def test_match_excludes_unpublished_photo(client, db_session):
    org = make_organization(db_session)
    event = make_event(db_session, org)
    photo = make_photo(db_session, event, published=False)
    make_face(db_session, photo, _embedding_for_fixture_face())
    db_session.flush()

    selfie_bytes = image_fixtures.single_face_selfie_jpeg()
    resp = client.post(
        f"/api/events/{event.id}/match",
        files={"selfie": ("selfie.jpg", selfie_bytes, "image/jpeg")},
        data={"consent": "true"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["matches"] == []
    # No Match row for a photo that was never actually surfaced.
    assert db_session.query(Match).filter(Match.photo_id == photo.id).count() == 0


def test_match_requires_consent(client, db_session):
    org = make_organization(db_session)
    event = make_event(db_session, org)
    db_session.flush()

    resp = client.post(
        f"/api/events/{event.id}/match",
        files={"selfie": ("selfie.jpg", image_fixtures.single_face_selfie_jpeg(), "image/jpeg")},
        data={"consent": "false"},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "consent_required"


def test_match_rejects_multi_face_selfie(client, db_session):
    org = make_organization(db_session)
    event = make_event(db_session, org)
    db_session.flush()

    resp = client.post(
        f"/api/events/{event.id}/match",
        files={"selfie": ("selfie.jpg", image_fixtures.multi_face_photo_jpeg(), "image/jpeg")},
        data={"consent": "true"},
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "multiple_faces_detected"


def test_match_rejects_no_face_selfie(client, db_session):
    org = make_organization(db_session)
    event = make_event(db_session, org)
    db_session.flush()

    resp = client.post(
        f"/api/events/{event.id}/match",
        files={"selfie": ("selfie.jpg", image_fixtures.no_face_photo_jpeg(), "image/jpeg")},
        data={"consent": "true"},
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "no_face_detected"


def test_match_404_for_nonexistent_event(client):
    resp = client.post(
        f"/api/events/{uuid.uuid4()}/match",
        files={"selfie": ("selfie.jpg", image_fixtures.no_face_photo_jpeg(), "image/jpeg")},
        data={"consent": "true"},
    )
    assert resp.status_code == 404
