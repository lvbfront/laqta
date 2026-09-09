from __future__ import annotations

from app.models.enums import UserRole
from app.services.ftp_credentials import authenticate
from tests.factories import auth_headers, make_event, make_organization, make_user


def _other_org_headers(db_session):
    other_org = make_organization(db_session, name="Other Org")
    other_user = make_user(db_session, other_org, role=UserRole.owner)
    return auth_headers(db_session, other_user)


def test_issue_requires_auth_and_is_hidden_from_other_orgs(client, db_session):
    org = make_organization(db_session)
    event = make_event(db_session, org)
    db_session.flush()

    no_auth = client.post(f"/api/events/{event.id}/ftp-credentials")
    assert no_auth.status_code == 401

    other_headers = _other_org_headers(db_session)
    cross_org = client.post(f"/api/events/{event.id}/ftp-credentials", headers=other_headers)
    assert cross_org.status_code == 404


def test_issue_forbidden_for_moderator(client, db_session):
    org = make_organization(db_session)
    event = make_event(db_session, org)
    db_session.flush()
    user = make_user(db_session, org, role=UserRole.moderator)
    headers = auth_headers(db_session, user)

    resp = client.post(f"/api/events/{event.id}/ftp-credentials", headers=headers)
    assert resp.status_code == 403


def test_issue_allowed_for_photographer_and_returns_plaintext_password_once(client, db_session):
    org = make_organization(db_session)
    event = make_event(db_session, org)
    db_session.flush()
    user = make_user(db_session, org, role=UserRole.photographer)
    headers = auth_headers(db_session, user)

    resp = client.post(f"/api/events/{event.id}/ftp-credentials", headers=headers)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["username"].startswith("evt-")
    assert body["password"]

    # the credential actually works
    credential = authenticate(db_session, body["username"], body["password"])
    assert credential is not None
    assert str(credential.event_id) == str(event.id)


def test_list_never_includes_the_password_and_shows_revoked_state(client, db_session):
    org = make_organization(db_session)
    event = make_event(db_session, org)
    db_session.flush()
    user = make_user(db_session, org, role=UserRole.owner)
    headers = auth_headers(db_session, user)

    issued = client.post(f"/api/events/{event.id}/ftp-credentials", headers=headers).json()

    listing = client.get(f"/api/events/{event.id}/ftp-credentials", headers=headers)
    assert listing.status_code == 200
    rows = listing.json()
    assert len(rows) == 1
    assert rows[0]["username"] == issued["username"]
    assert "password" not in rows[0]
    assert rows[0]["revoked_at"] is None

    revoke = client.delete(f"/api/events/{event.id}/ftp-credentials/{issued['id']}", headers=headers)
    assert revoke.status_code == 204

    listing_after = client.get(f"/api/events/{event.id}/ftp-credentials", headers=headers).json()
    assert listing_after[0]["revoked_at"] is not None

    # and it stops authenticating
    assert authenticate(db_session, issued["username"], issued["password"]) is None


def test_revoke_unknown_credential_404s(client, db_session):
    import uuid

    org = make_organization(db_session)
    event = make_event(db_session, org)
    db_session.flush()
    user = make_user(db_session, org, role=UserRole.owner)
    headers = auth_headers(db_session, user)

    resp = client.delete(f"/api/events/{event.id}/ftp-credentials/{uuid.uuid4()}", headers=headers)
    assert resp.status_code == 404
