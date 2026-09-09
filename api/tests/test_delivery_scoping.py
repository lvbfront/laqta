from __future__ import annotations

from datetime import datetime, timezone

from app.models.download import Download
from app.models.guest import Guest
from app.models.match import Match
from tests.factories import make_event, make_organization, make_photo


def _make_guest(db, event, token) -> Guest:
    guest = Guest(event_id=event.id, consent_at=datetime.now(timezone.utc), session_token=token)
    db.add(guest)
    db.flush()
    return guest


def test_valid_guest_gets_signed_url_for_matched_photo(client, db_session):
    org = make_organization(db_session)
    event = make_event(db_session, org)
    photo = make_photo(db_session, event, published=True)
    guest = _make_guest(db_session, event, "tok-valid")
    db_session.add(Match(guest_id=guest.id, photo_id=photo.id, score=0.5))
    db_session.flush()

    resp = client.get(
        f"/api/guest/photos/{photo.id}/url",
        headers={"Authorization": f"Bearer {guest.session_token}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["url"]
    assert body["expires_in_seconds"] > 0

    assert (
        db_session.query(Download)
        .filter(Download.guest_id == guest.id, Download.photo_id == photo.id)
        .count()
        == 1
    )


def test_guest_from_event_a_gets_404_for_photo_in_event_b(client, db_session):
    org = make_organization(db_session)
    event_a = make_event(db_session, org, name_en="Event A")
    event_b = make_event(db_session, org, name_en="Event B")

    photo_a = make_photo(db_session, event_a, published=True)
    photo_b = make_photo(db_session, event_b, published=True)

    guest_a = _make_guest(db_session, event_a, "tok-a")
    db_session.add(Match(guest_id=guest_a.id, photo_id=photo_a.id, score=0.5))
    db_session.flush()

    resp = client.get(
        f"/api/guest/photos/{photo_b.id}/url",
        headers={"Authorization": f"Bearer {guest_a.session_token}"},
    )
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "photo_not_found"


def test_guest_cannot_retrieve_photo_matched_below_threshold(client, db_session):
    # A below-threshold "match" never gets a Match row in the first place
    # (app/api/routes/match.py only persists matches >= MATCH_THRESHOLD),
    # so "matched below threshold" and "never matched at all" are the same
    # state here -- this pins that at the delivery layer directly.
    org = make_organization(db_session)
    event = make_event(db_session, org)
    photo = make_photo(db_session, event, published=True)
    guest = _make_guest(db_session, event, "tok-below-threshold")
    db_session.flush()  # deliberately: no Match row for (guest, photo)

    resp = client.get(
        f"/api/guest/photos/{photo.id}/url",
        headers={"Authorization": f"Bearer {guest.session_token}"},
    )
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "photo_not_found"


def test_missing_session_token_returns_401(client, db_session):
    org = make_organization(db_session)
    event = make_event(db_session, org)
    photo = make_photo(db_session, event, published=True)
    db_session.flush()

    resp = client.get(f"/api/guest/photos/{photo.id}/url")
    assert resp.status_code == 401


def test_invalid_session_token_returns_401(client, db_session):
    org = make_organization(db_session)
    event = make_event(db_session, org)
    photo = make_photo(db_session, event, published=True)
    db_session.flush()

    resp = client.get(
        f"/api/guest/photos/{photo.id}/url",
        headers={"Authorization": "Bearer not-a-real-token"},
    )
    assert resp.status_code == 401


def test_unpublished_photo_returns_404_even_with_a_match(client, db_session):
    # Defense in depth: a photo could be unpublished after being matched
    # (a future moderation "reject" action) -- delivery re-checks
    # published status itself rather than trusting match-time state.
    org = make_organization(db_session)
    event = make_event(db_session, org)
    photo = make_photo(db_session, event, published=False)
    guest = _make_guest(db_session, event, "tok-unpublished")
    db_session.add(Match(guest_id=guest.id, photo_id=photo.id, score=0.9))
    db_session.flush()

    resp = client.get(
        f"/api/guest/photos/{photo.id}/url",
        headers={"Authorization": f"Bearer {guest.session_token}"},
    )
    assert resp.status_code == 404
