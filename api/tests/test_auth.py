from __future__ import annotations

from app.models.user import User
from app.models.user_session import UserSession
from tests.factories import auth_headers, make_organization, make_user


def test_register_creates_org_and_owner_and_returns_a_working_session(client, db_session):
    resp = client.post(
        "/api/auth/register",
        json={"org_name": "New Org", "email": "owner@example.com", "password": "correcthorse123"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["user"]["role"] == "owner"
    assert body["session_token"]

    user = db_session.query(User).filter(User.email == "owner@example.com").first()
    assert user is not None
    # never store the plaintext password anywhere
    assert user.password_hash != "correcthorse123"

    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {body['session_token']}"})
    assert me.status_code == 200
    assert me.json()["email"] == "owner@example.com"


def test_register_rejects_duplicate_email(client, db_session):
    make_user(db_session, email="taken@example.com")
    db_session.flush()

    resp = client.post(
        "/api/auth/register",
        json={"org_name": "Another Org", "email": "taken@example.com", "password": "correcthorse123"},
    )
    assert resp.status_code == 409


def test_register_rejects_weak_password(client):
    resp = client.post(
        "/api/auth/register",
        json={"org_name": "Weak Pw Org", "email": "weak@example.com", "password": "short"},
    )
    assert resp.status_code == 422


def test_login_succeeds_with_correct_password_and_fails_with_wrong_one(client):
    client.post(
        "/api/auth/register",
        json={"org_name": "Login Org", "email": "login@example.com", "password": "correcthorse123"},
    )

    good = client.post("/api/auth/login", json={"email": "login@example.com", "password": "correcthorse123"})
    assert good.status_code == 200
    assert good.json()["session_token"]

    bad = client.post("/api/auth/login", json={"email": "login@example.com", "password": "wrong-password"})
    assert bad.status_code == 401


def test_login_unknown_email_gets_the_same_error_as_wrong_password(client):
    """Anti-enumeration: a login attempt must not reveal whether the email
    is registered at all -- both cases return the identical 401 body.
    """
    unknown = client.post("/api/auth/login", json={"email": "nobody@example.com", "password": "whatever123"})
    assert unknown.status_code == 401
    assert unknown.json()["detail"]["code"] == "invalid_credentials"


def test_logout_invalidates_the_session_token(client, db_session):
    org = make_organization(db_session)
    user = make_user(db_session, org)
    headers = auth_headers(db_session, user)

    still_good = client.get("/api/auth/me", headers=headers)
    assert still_good.status_code == 200

    logout = client.post("/api/auth/logout", headers=headers)
    assert logout.status_code == 204

    after_logout = client.get("/api/auth/me", headers=headers)
    assert after_logout.status_code == 401


def test_me_rejects_missing_and_garbage_tokens(client):
    no_header = client.get("/api/auth/me")
    assert no_header.status_code == 401
    assert no_header.json()["detail"]["code"] == "missing_session"

    garbage = client.get("/api/auth/me", headers={"Authorization": "Bearer not-a-real-token"})
    assert garbage.status_code == 401
    assert garbage.json()["detail"]["code"] == "invalid_session"


def test_expired_session_is_rejected(client, db_session):
    from datetime import timedelta

    from tests.factories import now_utc

    org = make_organization(db_session)
    user = make_user(db_session, org)
    session = UserSession(user_id=user.id, expires_at=now_utc() - timedelta(days=1))
    db_session.add(session)
    db_session.flush()

    resp = client.get("/api/auth/me", headers={"Authorization": f"Bearer {session.token}"})
    assert resp.status_code == 401
    assert resp.json()["detail"]["code"] == "invalid_session"
