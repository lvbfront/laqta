from __future__ import annotations

from datetime import datetime, timezone

from app.models.guest import Guest
from app.models.match import Match
from app.models.photo import Photo
from tests.factories import make_event, make_organization, make_photo


def _make_guest(db, event, token) -> Guest:
    guest = Guest(event_id=event.id, consent_at=datetime.now(timezone.utc), session_token=token)
    db.add(guest)
    db.flush()
    return guest


def test_not_me_records_feedback_without_unpublishing(client, db_session):
    org = make_organization(db_session)
    event = make_event(db_session, org)
    photo = make_photo(db_session, event, published=True)
    guest = _make_guest(db_session, event, "tok-not-me")
    db_session.add(Match(guest_id=guest.id, photo_id=photo.id, score=0.5))
    db_session.flush()

    resp = client.post(
        f"/api/guest/matches/{photo.id}/not-me", headers={"Authorization": f"Bearer {guest.session_token}"}
    )
    assert resp.status_code == 200
    assert resp.json()["feedback"] == "not_me"

    assert db_session.get(Photo, photo.id).published is True


def test_remove_request_unpublishes_the_photo_globally(client, db_session):
    org = make_organization(db_session)
    event = make_event(db_session, org)
    photo = make_photo(db_session, event, published=True)

    requesting_guest = _make_guest(db_session, event, "tok-requester")
    other_guest = _make_guest(db_session, event, "tok-other")
    db_session.add(Match(guest_id=requesting_guest.id, photo_id=photo.id, score=0.5))
    db_session.add(Match(guest_id=other_guest.id, photo_id=photo.id, score=0.6))
    db_session.flush()

    resp = client.post(
        f"/api/guest/matches/{photo.id}/remove",
        headers={"Authorization": f"Bearer {requesting_guest.session_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["feedback"] == "remove_requested"

    assert db_session.get(Photo, photo.id).published is False

    # hidden for the *other* guest too, not just the one who requested it
    other_delivery = client.get(
        f"/api/guest/photos/{photo.id}/url", headers={"Authorization": f"Bearer {other_guest.session_token}"}
    )
    assert other_delivery.status_code == 404


def test_feedback_404s_for_a_photo_the_guest_never_matched(client, db_session):
    org = make_organization(db_session)
    event = make_event(db_session, org)
    photo = make_photo(db_session, event, published=True)
    guest = _make_guest(db_session, event, "tok-no-match")
    db_session.flush()  # deliberately no Match row

    resp = client.post(
        f"/api/guest/matches/{photo.id}/not-me", headers={"Authorization": f"Bearer {guest.session_token}"}
    )
    assert resp.status_code == 404


def test_feedback_requires_a_valid_session(client, db_session):
    org = make_organization(db_session)
    event = make_event(db_session, org)
    photo = make_photo(db_session, event, published=True)
    db_session.flush()

    resp = client.post(f"/api/guest/matches/{photo.id}/remove")
    assert resp.status_code == 401
