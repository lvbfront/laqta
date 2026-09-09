from __future__ import annotations

from app.models.event_ftp_credential import EventFtpCredential
from app.services.ftp_credentials import authenticate, create_credential, revoke_credential
from tests.factories import make_event, make_organization


def test_create_credential_returns_a_working_plaintext_password_shown_once(db_session):
    org = make_organization(db_session)
    event = make_event(db_session, org)
    db_session.flush()

    issued = create_credential(db_session, event, created_by=None)
    db_session.commit()

    assert issued.credential.event_id == event.id
    assert issued.credential.username.startswith("evt-")
    # never the plaintext -- same convention as app.core.security for staff passwords
    assert issued.credential.password_hash != issued.password

    authenticated = authenticate(db_session, issued.credential.username, issued.password)
    assert authenticated is not None
    assert authenticated.id == issued.credential.id


def test_authenticate_rejects_wrong_password(db_session):
    org = make_organization(db_session)
    event = make_event(db_session, org)
    db_session.flush()
    issued = create_credential(db_session, event, created_by=None)
    db_session.commit()

    assert authenticate(db_session, issued.credential.username, "not-the-password") is None


def test_authenticate_rejects_unknown_username(db_session):
    assert authenticate(db_session, "no-such-user", "whatever") is None


def test_authenticate_rejects_a_revoked_credential(db_session):
    org = make_organization(db_session)
    event = make_event(db_session, org)
    db_session.flush()
    issued = create_credential(db_session, event, created_by=None)
    db_session.commit()

    revoke_credential(db_session, issued.credential)
    db_session.commit()

    assert authenticate(db_session, issued.credential.username, issued.password) is None


def test_credentials_are_scoped_per_event_not_shared(db_session):
    org = make_organization(db_session)
    event_a = make_event(db_session, org, name_en="Event A")
    event_b = make_event(db_session, org, name_en="Event B")
    db_session.flush()

    issued_a = create_credential(db_session, event_a, created_by=None)
    issued_b = create_credential(db_session, event_b, created_by=None)
    db_session.commit()

    assert issued_a.credential.username != issued_b.credential.username
    a = authenticate(db_session, issued_a.credential.username, issued_a.password)
    assert a.event_id == event_a.id
    b = authenticate(db_session, issued_b.credential.username, issued_b.password)
    assert b.event_id == event_b.id


def test_deleting_an_event_cascades_to_its_credentials(db_session):
    from app.models.event import Event

    org = make_organization(db_session)
    event = make_event(db_session, org)
    db_session.flush()
    issued = create_credential(db_session, event, created_by=None)
    db_session.commit()
    credential_id = issued.credential.id

    db_session.delete(db_session.get(Event, event.id))
    db_session.commit()

    assert db_session.get(EventFtpCredential, credential_id) is None
