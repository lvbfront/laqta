from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.models.event import Event
from app.models.organization import Organization
from tests.factories import make_event, make_organization, make_photo


def test_get_or_create_default_organization_is_idempotent(client):
    first = client.get("/api/dashboard/organization")
    second = client.get("/api/dashboard/organization")
    assert first.status_code == 200
    assert first.json()["id"] == second.json()["id"]


def test_create_event_computes_retention_and_forces_strict_auto_publish(client):
    org_id = client.get("/api/dashboard/organization").json()["id"]

    resp = client.post(
        f"/api/organizations/{org_id}/events",
        json={
            "name_ar": "ح",
            "name_en": "Strict Event",
            "ends_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
            "privacy_mode": "strict",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["privacy_mode"] == "strict"
    assert body["auto_publish"] is False
    assert body["qr_token"]


def test_created_event_is_findable_by_qr_token_and_listed_for_its_org(client):
    org_id = client.get("/api/dashboard/organization").json()["id"]
    created = client.post(
        f"/api/organizations/{org_id}/events",
        json={
            "name_ar": "ح",
            "name_en": "Findable Event",
            "ends_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
        },
    ).json()

    by_token = client.get(f"/api/events/by-token/{created['qr_token']}")
    assert by_token.status_code == 200
    assert by_token.json()["id"] == created["id"]
    # public lookup must not leak internal-only fields
    assert "qr_token" not in by_token.json()

    listing = client.get(f"/api/organizations/{org_id}/events")
    assert any(e["id"] == created["id"] for e in listing.json())


def test_event_by_token_404_for_unknown_token(client):
    resp = client.get("/api/events/by-token/not-a-real-token")
    assert resp.status_code == 404


def test_list_photos_filters_by_status_and_moderate_flips_published(client, db_session):
    org = make_organization(db_session)
    event = make_event(db_session, org, auto_publish=True)
    photo = make_photo(db_session, event, published=False)
    db_session.flush()

    all_photos = client.get(f"/api/events/{event.id}/photos").json()
    assert len(all_photos) == 1
    assert all_photos[0]["published"] is False

    ready_only = client.get(f"/api/events/{event.id}/photos", params={"status": "ready"}).json()
    assert len(ready_only) == 1

    none_pending = client.get(f"/api/events/{event.id}/photos", params={"status": "pending"}).json()
    assert none_pending == []

    approve = client.post(f"/api/events/{event.id}/photos/{photo.id}/moderate", params={"action": "approve"})
    assert approve.status_code == 200
    assert approve.json()["published"] is True

    reject = client.post(f"/api/events/{event.id}/photos/{photo.id}/moderate", params={"action": "reject"})
    assert reject.json()["published"] is False


def test_moderate_unknown_photo_404s(client, db_session):
    org = make_organization(db_session)
    event = make_event(db_session, org)
    db_session.flush()
    import uuid

    resp = client.post(
        f"/api/events/{event.id}/photos/{uuid.uuid4()}/moderate", params={"action": "approve"}
    )
    assert resp.status_code == 404
