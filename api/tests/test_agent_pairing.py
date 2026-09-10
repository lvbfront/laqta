"""The desktop watch-folder agent (agent/) never has a staff login -- it
pairs via a short-lived code (issued on the dashboard, session-
authenticated) exchanged for a long-lived token (app/api/routes/agent.py,
unauthenticated by design), then uploads through that token.
"""

from __future__ import annotations

import io
from datetime import timedelta

from app.models.agent_pairing_code import AgentPairingCode
from app.models.agent_token import AgentToken
from app.models.enums import UserRole
from app.models.photo import Photo
from app.services.agent_pairing import authenticate_agent_token, issue_pairing_code, redeem_pairing_code
from tests.factories import auth_headers, make_event, make_organization, make_user, now_utc


def test_issue_pairing_code_requires_auth_and_is_hidden_from_other_orgs(client, db_session):
    org = make_organization(db_session)
    event = make_event(db_session, org)
    db_session.flush()

    no_auth = client.post(f"/api/events/{event.id}/agent-pairing-codes")
    assert no_auth.status_code == 401

    other_org = make_organization(db_session, name="Other Org")
    other_user = make_user(db_session, other_org, role=UserRole.owner)
    other_headers = auth_headers(db_session, other_user)
    cross_org = client.post(f"/api/events/{event.id}/agent-pairing-codes", headers=other_headers)
    assert cross_org.status_code == 404


def test_issue_pairing_code_forbidden_for_moderator(client, db_session):
    org = make_organization(db_session)
    event = make_event(db_session, org)
    db_session.flush()
    user = make_user(db_session, org, role=UserRole.moderator)
    headers = auth_headers(db_session, user)

    resp = client.post(f"/api/events/{event.id}/agent-pairing-codes", headers=headers)
    assert resp.status_code == 403


def test_issue_pairing_code_returns_a_six_char_code_with_expiry(client, db_session):
    org = make_organization(db_session)
    event = make_event(db_session, org)
    db_session.flush()
    user = make_user(db_session, org, role=UserRole.photographer)
    headers = auth_headers(db_session, user)

    resp = client.post(f"/api/events/{event.id}/agent-pairing-codes", headers=headers)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert len(body["code"]) == 6
    assert body["expires_at"]


def test_pair_agent_with_a_valid_code_returns_a_working_token(client, db_session):
    org = make_organization(db_session)
    event = make_event(db_session, org)
    db_session.flush()
    pairing_code = issue_pairing_code(db_session, event, created_by=None)
    db_session.commit()

    resp = client.post("/api/agent/pair", json={"code": pairing_code.code, "device_label": "Ahmad's MacBook"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["event_id"] == str(event.id)
    assert body["token"]

    authenticated = authenticate_agent_token(db_session, body["token"])
    assert authenticated is not None
    assert authenticated.event_id == event.id
    assert authenticated.device_label == "Ahmad's MacBook"


def test_pair_agent_code_is_single_use(client, db_session):
    org = make_organization(db_session)
    event = make_event(db_session, org)
    db_session.flush()
    pairing_code = issue_pairing_code(db_session, event, created_by=None)
    db_session.commit()

    first = client.post("/api/agent/pair", json={"code": pairing_code.code})
    assert first.status_code == 200

    second = client.post("/api/agent/pair", json={"code": pairing_code.code})
    assert second.status_code == 401
    assert second.json()["detail"]["code"] == "invalid_pairing_code"


def test_pair_agent_rejects_expired_code(client, db_session):
    org = make_organization(db_session)
    event = make_event(db_session, org)
    db_session.flush()
    expired = AgentPairingCode(event_id=event.id, expires_at=now_utc() - timedelta(minutes=1))
    db_session.add(expired)
    db_session.commit()

    resp = client.post("/api/agent/pair", json={"code": expired.code})
    assert resp.status_code == 401


def test_pair_agent_rejects_unknown_code(client):
    resp = client.post("/api/agent/pair", json={"code": "ZZZZZZ"})
    assert resp.status_code == 401


def test_pairing_code_is_case_insensitive(client, db_session):
    org = make_organization(db_session)
    event = make_event(db_session, org)
    db_session.flush()
    pairing_code = issue_pairing_code(db_session, event, created_by=None)
    db_session.commit()

    resp = client.post("/api/agent/pair", json={"code": pairing_code.code.lower()})
    assert resp.status_code == 200


def test_upload_via_agent_requires_a_valid_token(client, db_session):
    org = make_organization(db_session)
    event = make_event(db_session, org)
    db_session.flush()

    no_auth = client.post(
        "/api/agent/photos", files={"file": ("a.jpg", io.BytesIO(b"x"), "image/jpeg")}
    )
    assert no_auth.status_code == 401

    bad_token = client.post(
        "/api/agent/photos",
        headers={"Authorization": "Bearer not-a-real-token"},
        files={"file": ("a.jpg", io.BytesIO(b"x"), "image/jpeg")},
    )
    assert bad_token.status_code == 401


def test_upload_via_agent_ingests_into_the_paired_event(client, db_session):
    org = make_organization(db_session)
    event = make_event(db_session, org)
    db_session.flush()
    pairing_code = issue_pairing_code(db_session, event, created_by=None)
    db_session.commit()
    token = client.post("/api/agent/pair", json={"code": pairing_code.code}).json()["token"]

    resp = client.post(
        "/api/agent/photos",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("shot.jpg", io.BytesIO(b"camera-bytes"), "image/jpeg")},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "queued"
    photo = db_session.get(Photo, body["photo_id"])
    assert photo.event_id == event.id


def test_upload_via_agent_rejected_after_token_revoked(client, db_session):
    org = make_organization(db_session)
    event = make_event(db_session, org)
    db_session.flush()
    pairing_code = issue_pairing_code(db_session, event, created_by=None)
    db_session.commit()
    token = client.post("/api/agent/pair", json={"code": pairing_code.code}).json()["token"]

    agent_token = db_session.query(AgentToken).filter(AgentToken.event_id == event.id).first()
    user = make_user(db_session, org, role=UserRole.owner)
    headers = auth_headers(db_session, user)
    revoke = client.delete(f"/api/events/{event.id}/agent-tokens/{agent_token.id}", headers=headers)
    assert revoke.status_code == 204

    resp = client.post(
        "/api/agent/photos",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("shot.jpg", io.BytesIO(b"x"), "image/jpeg")},
    )
    assert resp.status_code == 401


def test_list_agent_tokens_requires_auth_and_role(client, db_session):
    org = make_organization(db_session)
    event = make_event(db_session, org)
    db_session.flush()

    no_auth = client.get(f"/api/events/{event.id}/agent-tokens")
    assert no_auth.status_code == 401

    moderator = make_user(db_session, org, role=UserRole.moderator)
    headers = auth_headers(db_session, moderator)
    forbidden = client.get(f"/api/events/{event.id}/agent-tokens", headers=headers)
    assert forbidden.status_code == 403


def test_redeem_pairing_code_service_returns_none_for_reused_code(db_session):
    org = make_organization(db_session)
    event = make_event(db_session, org)
    db_session.flush()
    pairing_code = issue_pairing_code(db_session, event, created_by=None)
    db_session.commit()

    first = redeem_pairing_code(db_session, pairing_code.code, None)
    assert first is not None
    second = redeem_pairing_code(db_session, pairing_code.code, None)
    assert second is None
