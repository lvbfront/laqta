"""Every dashboard/org/event/moderation endpoint, hit two ways:

1. With no Authorization header at all -- must be 401.
2. With a valid session for a user in a *different* org than the
   resource -- must be 404 (anti-enumeration: a non-member can't tell
   "doesn't exist" from "exists but isn't yours", matching the existing
   guest-facing pattern in app/api/routes/delivery.py).

Role enforcement (403 for a wrong-role member of the *right* org) is
covered separately, per endpoint, at the bottom of this file.
"""

from __future__ import annotations

import io
from datetime import datetime, timedelta, timezone

from app.models.enums import UserRole
from tests.factories import auth_headers, make_event, make_organization, make_photo, make_user


def _other_org_headers(db_session):
    other_org = make_organization(db_session, name="Other Org")
    other_user = make_user(db_session, other_org, role=UserRole.owner)
    return auth_headers(db_session, other_user)


def test_get_event_requires_auth_and_is_hidden_from_other_orgs(client, db_session):
    org = make_organization(db_session)
    event = make_event(db_session, org)
    db_session.flush()

    no_auth = client.get(f"/api/events/{event.id}")
    assert no_auth.status_code == 401

    other_headers = _other_org_headers(db_session)
    cross_org = client.get(f"/api/events/{event.id}", headers=other_headers)
    assert cross_org.status_code == 404


def test_list_org_events_requires_auth_and_is_hidden_from_other_orgs(client, db_session):
    org = make_organization(db_session)
    make_event(db_session, org)
    db_session.flush()

    no_auth = client.get(f"/api/organizations/{org.id}/events")
    assert no_auth.status_code == 401

    other_headers = _other_org_headers(db_session)
    cross_org = client.get(f"/api/organizations/{org.id}/events", headers=other_headers)
    assert cross_org.status_code == 404


def test_create_event_requires_auth_and_is_hidden_from_other_orgs(client, db_session):
    org = make_organization(db_session)
    db_session.flush()
    payload = {
        "name_ar": "ح",
        "name_en": "E",
        "ends_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
    }

    no_auth = client.post(f"/api/organizations/{org.id}/events", json=payload)
    assert no_auth.status_code == 401

    other_headers = _other_org_headers(db_session)
    cross_org = client.post(f"/api/organizations/{org.id}/events", headers=other_headers, json=payload)
    assert cross_org.status_code == 404


def test_list_photos_requires_auth_and_is_hidden_from_other_orgs(client, db_session):
    org = make_organization(db_session)
    event = make_event(db_session, org)
    make_photo(db_session, event)
    db_session.flush()

    no_auth = client.get(f"/api/events/{event.id}/photos")
    assert no_auth.status_code == 401

    other_headers = _other_org_headers(db_session)
    cross_org = client.get(f"/api/events/{event.id}/photos", headers=other_headers)
    assert cross_org.status_code == 404


def test_upload_photos_requires_auth_and_is_hidden_from_other_orgs(client, db_session):
    org = make_organization(db_session)
    event = make_event(db_session, org)
    db_session.flush()
    files = [("files", ("a.jpg", io.BytesIO(b"x"), "image/jpeg"))]

    no_auth = client.post(f"/api/events/{event.id}/photos", files=files)
    assert no_auth.status_code == 401

    other_headers = _other_org_headers(db_session)
    cross_org = client.post(f"/api/events/{event.id}/photos", files=files, headers=other_headers)
    assert cross_org.status_code == 404


def test_moderate_photo_requires_auth_and_is_hidden_from_other_orgs(client, db_session):
    org = make_organization(db_session)
    event = make_event(db_session, org)
    photo = make_photo(db_session, event)
    db_session.flush()

    no_auth = client.post(f"/api/events/{event.id}/photos/{photo.id}/moderate", params={"action": "approve"})
    assert no_auth.status_code == 401

    other_headers = _other_org_headers(db_session)
    cross_org = client.post(
        f"/api/events/{event.id}/photos/{photo.id}/moderate",
        params={"action": "approve"},
        headers=other_headers,
    )
    assert cross_org.status_code == 404


def test_add_and_remove_photo_code_require_auth_and_are_hidden_from_other_orgs(client, db_session):
    org = make_organization(db_session)
    event = make_event(db_session, org)
    photo = make_photo(db_session, event)
    db_session.flush()

    no_auth_add = client.post(f"/api/events/{event.id}/photos/{photo.id}/codes", json={"code": "BIB1"})
    assert no_auth_add.status_code == 401
    no_auth_remove = client.delete(f"/api/events/{event.id}/photos/{photo.id}/codes/BIB1")
    assert no_auth_remove.status_code == 401

    other_headers = _other_org_headers(db_session)
    cross_org_add = client.post(
        f"/api/events/{event.id}/photos/{photo.id}/codes", json={"code": "BIB1"}, headers=other_headers
    )
    assert cross_org_add.status_code == 404
    cross_org_remove = client.delete(
        f"/api/events/{event.id}/photos/{photo.id}/codes/BIB1", headers=other_headers
    )
    assert cross_org_remove.status_code == 404


def test_org_a_member_can_reach_their_own_org_a_event(client, db_session):
    """Sanity check paired with the cross-org tests above: a legitimate
    member of the *right* org is not accidentally caught by the same
    org-scoping check that blocks org B.
    """
    org = make_organization(db_session)
    user = make_user(db_session, org, role=UserRole.owner)
    headers = auth_headers(db_session, user)
    event = make_event(db_session, org)
    db_session.flush()

    resp = client.get(f"/api/events/{event.id}", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["id"] == str(event.id)


# --- Role enforcement (403): right org, wrong role -------------------------


def test_create_event_forbidden_for_photographer_and_moderator(client, db_session):
    org = make_organization(db_session)
    db_session.flush()
    payload = {
        "name_ar": "ح",
        "name_en": "E",
        "ends_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
    }

    for role in (UserRole.photographer, UserRole.moderator):
        user = make_user(db_session, org, role=role)
        headers = auth_headers(db_session, user)
        resp = client.post(f"/api/organizations/{org.id}/events", headers=headers, json=payload)
        assert resp.status_code == 403, f"role={role} expected 403, got {resp.status_code}"


def test_create_event_allowed_for_owner_and_staff(client, db_session):
    org = make_organization(db_session)
    db_session.flush()
    payload = {
        "name_ar": "ح",
        "name_en": "E",
        "ends_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
    }

    for role in (UserRole.owner, UserRole.staff):
        user = make_user(db_session, org, role=role)
        headers = auth_headers(db_session, user)
        resp = client.post(f"/api/organizations/{org.id}/events", headers=headers, json=payload)
        assert resp.status_code == 201, f"role={role} expected 201, got {resp.status_code}: {resp.text}"


def test_upload_photos_forbidden_for_moderator(client, db_session):
    org = make_organization(db_session)
    event = make_event(db_session, org)
    db_session.flush()
    user = make_user(db_session, org, role=UserRole.moderator)
    headers = auth_headers(db_session, user)

    resp = client.post(
        f"/api/events/{event.id}/photos",
        files=[("files", ("a.jpg", io.BytesIO(b"x"), "image/jpeg"))],
        headers=headers,
    )
    assert resp.status_code == 403


def test_upload_photos_allowed_for_photographer(client, db_session):
    org = make_organization(db_session)
    event = make_event(db_session, org)
    db_session.flush()
    user = make_user(db_session, org, role=UserRole.photographer)
    headers = auth_headers(db_session, user)

    resp = client.post(
        f"/api/events/{event.id}/photos",
        files=[("files", ("a.jpg", io.BytesIO(b"x"), "image/jpeg"))],
        headers=headers,
    )
    assert resp.status_code == 201


def test_moderate_photo_forbidden_for_photographer(client, db_session):
    org = make_organization(db_session)
    event = make_event(db_session, org)
    photo = make_photo(db_session, event)
    db_session.flush()
    user = make_user(db_session, org, role=UserRole.photographer)
    headers = auth_headers(db_session, user)

    resp = client.post(
        f"/api/events/{event.id}/photos/{photo.id}/moderate", params={"action": "approve"}, headers=headers
    )
    assert resp.status_code == 403


def test_moderate_photo_allowed_for_moderator(client, db_session):
    org = make_organization(db_session)
    event = make_event(db_session, org)
    photo = make_photo(db_session, event)
    db_session.flush()
    user = make_user(db_session, org, role=UserRole.moderator)
    headers = auth_headers(db_session, user)

    resp = client.post(
        f"/api/events/{event.id}/photos/{photo.id}/moderate", params={"action": "approve"}, headers=headers
    )
    assert resp.status_code == 200
