from __future__ import annotations

from app.models.enums import MatchMode, UserRole
from app.models.face import Face
from app.models.guest import Guest
from app.models.guest_face import GuestFace
from tests.factories import auth_headers, make_event, make_organization, make_photo, make_user


def _tag(client, headers, event_id, photo_id, code):
    resp = client.post(f"/api/events/{event_id}/photos/{photo_id}/codes", json={"code": code}, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp


def test_match_by_code_finds_the_tagged_published_photo(client, db_session):
    org = make_organization(db_session)
    user = make_user(db_session, org, role=UserRole.moderator)
    headers = auth_headers(db_session, user)
    event = make_event(db_session, org, match_mode=MatchMode.code)
    photo = make_photo(db_session, event, published=True)
    db_session.flush()
    _tag(client, headers, event.id, photo.id, "BIB1234")

    resp = client.post(f"/api/events/{event.id}/match/code", json={"code": "BIB1234"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["guest_session_token"]
    assert [m["photo_id"] for m in body["matches"]] == [str(photo.id)]
    assert body["matches"][0]["score"] == 1.0


def test_match_by_code_no_result_for_unknown_code(client, db_session):
    org = make_organization(db_session)
    event = make_event(db_session, org, match_mode=MatchMode.code)
    db_session.flush()

    resp = client.post(f"/api/events/{event.id}/match/code", json={"code": "NOTHING"})
    assert resp.status_code == 200
    assert resp.json()["matches"] == []


def test_match_by_code_never_returns_an_unpublished_photo(client, db_session):
    org = make_organization(db_session)
    user = make_user(db_session, org, role=UserRole.moderator)
    headers = auth_headers(db_session, user)
    event = make_event(db_session, org, match_mode=MatchMode.code)
    photo = make_photo(db_session, event, published=False)
    db_session.flush()
    _tag(client, headers, event.id, photo.id, "BIB9999")

    resp = client.post(f"/api/events/{event.id}/match/code", json={"code": "BIB9999"})
    assert resp.status_code == 200
    assert resp.json()["matches"] == []


def test_match_by_code_creates_no_biometric_data(client, db_session):
    """The whole point of match_mode='code': no face embedding, no
    GuestFace row, ever -- for a code match there was never a selfie to
    embed in the first place.
    """
    org = make_organization(db_session)
    user = make_user(db_session, org, role=UserRole.moderator)
    headers = auth_headers(db_session, user)
    event = make_event(db_session, org, match_mode=MatchMode.code)
    photo = make_photo(db_session, event, published=True)
    db_session.flush()
    _tag(client, headers, event.id, photo.id, "BIB42")

    resp = client.post(f"/api/events/{event.id}/match/code", json={"code": "BIB42"})
    assert resp.status_code == 200
    guest_id = resp.json()["guest_session_token"]  # just to force a flush below
    assert guest_id

    guest = db_session.query(Guest).filter(Guest.event_id == event.id).one()
    assert guest.selfie_deleted_at is None  # no selfie ever existed for this guest
    assert db_session.query(GuestFace).filter(GuestFace.guest_id == guest.id).count() == 0
    assert db_session.query(Face).filter(Face.photo_id == photo.id).count() == 0


def test_empty_code_is_rejected(client, db_session):
    org = make_organization(db_session)
    event = make_event(db_session, org, match_mode=MatchMode.code)
    db_session.flush()

    resp = client.post(f"/api/events/{event.id}/match/code", json={"code": "   "})
    assert resp.status_code == 422


def test_code_match_rejects_a_face_mode_event(client, db_session):
    org = make_organization(db_session)
    event = make_event(db_session, org, match_mode=MatchMode.face)
    db_session.flush()

    resp = client.post(f"/api/events/{event.id}/match/code", json={"code": "X"})
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "wrong_match_mode"


def test_selfie_match_rejects_a_code_mode_event(client, db_session):
    org = make_organization(db_session)
    event = make_event(db_session, org, match_mode=MatchMode.code)
    db_session.flush()

    resp = client.post(
        f"/api/events/{event.id}/match",
        data={"consent": "true"},
        files={"selfie": ("s.jpg", b"not-a-real-image", "image/jpeg")},
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "wrong_match_mode"


def test_both_mode_event_accepts_either_match_path(client, db_session):
    org = make_organization(db_session)
    user = make_user(db_session, org, role=UserRole.moderator)
    headers = auth_headers(db_session, user)
    event = make_event(db_session, org, match_mode=MatchMode.both)
    photo = make_photo(db_session, event, published=True)
    db_session.flush()
    _tag(client, headers, event.id, photo.id, "BIB7")

    code_resp = client.post(f"/api/events/{event.id}/match/code", json={"code": "BIB7"})
    assert code_resp.status_code == 200
    assert [m["photo_id"] for m in code_resp.json()["matches"]] == [str(photo.id)]


def test_add_photo_code_is_idempotent_and_remove_photo_code_deletes_it(client, db_session):
    org = make_organization(db_session)
    user = make_user(db_session, org, role=UserRole.moderator)
    headers = auth_headers(db_session, user)
    event = make_event(db_session, org)
    photo = make_photo(db_session, event)
    db_session.flush()

    first = _tag(client, headers, event.id, photo.id, "DUP1")
    assert first.json()["codes"] == ["DUP1"]
    second = _tag(client, headers, event.id, photo.id, "DUP1")
    assert second.json()["codes"] == ["DUP1"]  # not ["DUP1", "DUP1"]

    removed = client.delete(f"/api/events/{event.id}/photos/{photo.id}/codes/DUP1", headers=headers)
    assert removed.status_code == 200
    assert removed.json()["codes"] == []
