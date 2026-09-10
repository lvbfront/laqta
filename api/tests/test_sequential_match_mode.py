"""match_mode='sequential': a photo booth where staff taps "next guest"
between subjects (POST .../next-guest) and every photo that lands while
a number is "open" is auto-tagged with it -- no camera integration, no
staff typing a code in afterward. Same guest-facing lookup as
match_mode='code' (match_by_code), just a different way the PhotoCode
row gets created.
"""

from __future__ import annotations

import io

from app.models.enums import MatchMode, UserRole
from app.models.event import Event
from app.models.face import Face
from app.models.photo_code import PhotoCode
from tests.factories import auth_headers, make_event, make_organization, make_photo, make_user


def test_next_guest_starts_at_one_and_increments(client, db_session):
    org = make_organization(db_session)
    user = make_user(db_session, org, role=UserRole.photographer)
    headers = auth_headers(db_session, user)
    event = make_event(db_session, org, match_mode=MatchMode.sequential)
    db_session.flush()

    first = client.post(f"/api/events/{event.id}/next-guest", headers=headers)
    assert first.status_code == 200
    assert first.json()["current_solo_number"] == 1

    second = client.post(f"/api/events/{event.id}/next-guest", headers=headers)
    assert second.json()["current_solo_number"] == 2


def test_next_guest_requires_auth_and_is_hidden_from_other_orgs(client, db_session):
    org = make_organization(db_session)
    event = make_event(db_session, org, match_mode=MatchMode.sequential)
    db_session.flush()

    no_auth = client.post(f"/api/events/{event.id}/next-guest")
    assert no_auth.status_code == 401

    other_org = make_organization(db_session, name="Other Org")
    other_user = make_user(db_session, other_org, role=UserRole.owner)
    other_headers = auth_headers(db_session, other_user)
    cross_org = client.post(f"/api/events/{event.id}/next-guest", headers=other_headers)
    assert cross_org.status_code == 404


def test_next_guest_forbidden_for_moderator(client, db_session):
    org = make_organization(db_session)
    event = make_event(db_session, org, match_mode=MatchMode.sequential)
    db_session.flush()
    user = make_user(db_session, org, role=UserRole.moderator)
    headers = auth_headers(db_session, user)

    resp = client.post(f"/api/events/{event.id}/next-guest", headers=headers)
    assert resp.status_code == 403


def test_next_guest_rejected_for_a_non_sequential_event(client, db_session):
    org = make_organization(db_session)
    event = make_event(db_session, org, match_mode=MatchMode.code)
    db_session.flush()
    user = make_user(db_session, org, role=UserRole.owner)
    headers = auth_headers(db_session, user)

    resp = client.post(f"/api/events/{event.id}/next-guest", headers=headers)
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "wrong_match_mode"


def test_upload_before_any_next_guest_tap_is_not_tagged(client, db_session):
    org = make_organization(db_session)
    event = make_event(db_session, org, match_mode=MatchMode.sequential)
    db_session.flush()
    user = make_user(db_session, org, role=UserRole.photographer)
    headers = auth_headers(db_session, user)

    resp = client.post(
        f"/api/events/{event.id}/photos",
        files=[("files", ("a.jpg", io.BytesIO(b"x"), "image/jpeg"))],
        headers=headers,
    )
    photo_id = resp.json()["results"][0]["photo_id"]
    assert db_session.query(PhotoCode).filter(PhotoCode.photo_id == photo_id).count() == 0


def test_uploads_are_auto_tagged_with_the_current_number(client, db_session):
    org = make_organization(db_session)
    event = make_event(db_session, org, match_mode=MatchMode.sequential)
    db_session.flush()
    user = make_user(db_session, org, role=UserRole.photographer)
    headers = auth_headers(db_session, user)

    client.post(f"/api/events/{event.id}/next-guest", headers=headers)  # -> 1

    # Two shots of the same guest, matching the "retakes happen" case --
    # both should land under the same open number.
    r1 = client.post(
        f"/api/events/{event.id}/photos",
        files=[("files", ("a.jpg", io.BytesIO(b"shot-a"), "image/jpeg"))],
        headers=headers,
    )
    r2 = client.post(
        f"/api/events/{event.id}/photos",
        files=[("files", ("b.jpg", io.BytesIO(b"shot-b"), "image/jpeg"))],
        headers=headers,
    )
    photo_id_1 = r1.json()["results"][0]["photo_id"]
    photo_id_2 = r2.json()["results"][0]["photo_id"]

    codes_1 = [c.code for c in db_session.query(PhotoCode).filter(PhotoCode.photo_id == photo_id_1)]
    codes_2 = [c.code for c in db_session.query(PhotoCode).filter(PhotoCode.photo_id == photo_id_2)]
    assert codes_1 == ["1"]
    assert codes_2 == ["1"]

    client.post(f"/api/events/{event.id}/next-guest", headers=headers)  # -> 2
    r3 = client.post(
        f"/api/events/{event.id}/photos",
        files=[("files", ("c.jpg", io.BytesIO(b"shot-c"), "image/jpeg"))],
        headers=headers,
    )
    photo_id_3 = r3.json()["results"][0]["photo_id"]
    codes_3 = [c.code for c in db_session.query(PhotoCode).filter(PhotoCode.photo_id == photo_id_3)]
    assert codes_3 == ["2"]


def test_guest_enters_their_number_and_gets_all_photos_tagged_with_it(client, db_session):
    org = make_organization(db_session)
    event = make_event(db_session, org, match_mode=MatchMode.sequential, current_solo_number=5)
    db_session.flush()
    photo_a = make_photo(db_session, event, published=True)
    photo_b = make_photo(db_session, event, published=True)
    db_session.add(PhotoCode(photo_id=photo_a.id, code="5"))
    db_session.add(PhotoCode(photo_id=photo_b.id, code="5"))
    db_session.flush()

    resp = client.post(f"/api/events/{event.id}/match/code", json={"code": "5"})
    assert resp.status_code == 200
    ids = {m["photo_id"] for m in resp.json()["matches"]}
    assert ids == {str(photo_a.id), str(photo_b.id)}


def test_sequential_event_creates_no_biometric_data(client, db_session):
    """The point of this mode, same as match_mode='code': no face
    embedding, ever, regardless of what's actually in the photo.
    """
    org = make_organization(db_session)
    event = make_event(db_session, org, match_mode=MatchMode.sequential)
    db_session.flush()
    user = make_user(db_session, org, role=UserRole.photographer)
    headers = auth_headers(db_session, user)
    client.post(f"/api/events/{event.id}/next-guest", headers=headers)

    resp = client.post(
        f"/api/events/{event.id}/photos",
        files=[("files", ("a.jpg", io.BytesIO(b"x"), "image/jpeg"))],
        headers=headers,
    )
    photo_id = resp.json()["results"][0]["photo_id"]
    assert db_session.query(Face).filter(Face.photo_id == photo_id).count() == 0


def test_selfie_match_rejects_a_sequential_event(client, db_session):
    org = make_organization(db_session)
    event = make_event(db_session, org, match_mode=MatchMode.sequential)
    db_session.flush()

    resp = client.post(
        f"/api/events/{event.id}/match",
        data={"consent": "true"},
        files={"selfie": ("s.jpg", b"not-a-real-image", "image/jpeg")},
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "wrong_match_mode"


def test_create_event_defaults_to_sequential_consent_text(client, db_session):
    org = make_organization(db_session)
    user = make_user(db_session, org, role=UserRole.owner)
    headers = auth_headers(db_session, user)

    from datetime import datetime, timedelta, timezone

    resp = client.post(
        f"/api/organizations/{org.id}/events",
        headers=headers,
        json={
            "name_ar": "بوث",
            "name_en": "Booth",
            "ends_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
            "match_mode": "sequential",
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert "رقمًا" in body["consent_text_ar"]
    assert body["current_solo_number"] is None
