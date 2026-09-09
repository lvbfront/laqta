"""Drives a real FTPS server (app.ftps.server.build_server) with a real
ftplib.FTP_TLS client over an actual TLS socket -- not a mock of
pyftpdlib, not a direct call into the handler. This is the strongest
verification available for "FTPS ingest with per-event credentials
issued by the API" (the user's own words for this feature): a genuine
camera or desktop agent speaks exactly this protocol.

The server's authorizer/handler open their own DB sessions via
app.db.SessionLocal (they're not FastAPI routes, so there's no
get_db dependency to override) -- each test rebinds that name, on both
modules, to a sessionmaker over the same test engine conftest.py's
`engine` fixture already migrated, so rows land in the real test
database rather than talking to whatever DATABASE_URL happens to be. Each
test cleans up what it created (deleting the org cascades through event/
credential/photo).
"""

from __future__ import annotations

import datetime
import ssl
import threading

import ftplib
import pytest
from sqlalchemy.orm import sessionmaker

import app.ftps.authorizer as authorizer_module
import app.ftps.handler as handler_module
from app.ftps.server import build_server
from app.models.enums import AccountType, EventStatus, MatchMode, PrivacyMode
from app.models.event import Event
from app.models.organization import Organization
from app.models.photo import Photo
from app.services.ftp_credentials import create_credential, revoke_credential


@pytest.fixture()
def ftps_session_factory(engine, monkeypatch):
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    monkeypatch.setattr(authorizer_module, "SessionLocal", factory)
    monkeypatch.setattr(handler_module, "SessionLocal", factory)
    return factory


@pytest.fixture()
def running_server(ftps_session_factory, tmp_path, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "ftps_upload_root", str(tmp_path / "uploads"))
    monkeypatch.setattr(settings, "ftps_cert_file", str(tmp_path / "cert.pem"))
    monkeypatch.setattr(settings, "ftps_key_file", str(tmp_path / "key.pem"))

    server = build_server(bind_port=0)
    port = server.socket.getsockname()[1]

    def _serve():
        try:
            server.serve_forever()
        except OSError:
            # close_all() (below) closes the kqueue fd out from under a
            # poll() that's already in flight on some platforms -- a
            # cosmetic shutdown race, not a functional failure; every
            # assertion in the test has already run by the time teardown
            # gets here.
            pass

    thread = threading.Thread(target=_serve, daemon=True)
    thread.start()
    yield port
    server.close_all()
    thread.join(timeout=2)


def _make_event(db, **kwargs):
    org = Organization(name="FTPS Test Org", account_type=AccountType.organizer)
    db.add(org)
    db.flush()
    event = Event(
        org_id=org.id,
        name_ar="حدث",
        name_en=kwargs.get("name_en", "FTPS Event"),
        status=EventStatus.active,
        ends_at=datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=4),
        consent_text_ar="x",
        consent_text_en="x",
        privacy_mode=PrivacyMode.standard,
        match_mode=MatchMode.face,
        auto_publish=True,
    )
    db.add(event)
    db.flush()
    return org, event


def _tls_client(port: int) -> ftplib.FTP_TLS:
    ctx = ssl._create_unverified_context()  # self-signed dev cert, see app/ftps/certs.py
    ftp = ftplib.FTP_TLS(context=ctx)
    ftp.connect("127.0.0.1", port, timeout=10)
    return ftp


def test_ftps_upload_ingests_a_photo_for_the_credentials_event(ftps_session_factory, running_server, tmp_path):
    db = ftps_session_factory()
    try:
        org, event = _make_event(db)
        issued = create_credential(db, event, created_by=None)
        db.commit()
        username, password, event_id = issued.credential.username, issued.password, event.id

        src = tmp_path / "photo.jpg"
        src.write_bytes(b"\xff\xd8\xff\xe0" + b"not-a-real-jpeg-but-real-bytes" * 20)  # JPEG magic bytes + filler

        ftp = _tls_client(running_server)
        ftp.auth()
        ftp.login(username, password)
        ftp.prot_p()
        with open(src, "rb") as f:
            ftp.storbinary("STOR camera001.jpg", f)
        ftp.quit()

        photos = db.query(Photo).filter(Photo.event_id == event_id).all()
        assert len(photos) == 1
        assert photos[0].status.value == "pending"  # no worker running in this test -- ingest only enqueues
    finally:
        # Bulk delete (not session.delete(org)) -- Organization.events has
        # no cascade config, so session.delete would try to NULL out
        # events.org_id (a NOT NULL column) for any Event already loaded
        # in this session, instead of letting the DB's real ON DELETE
        # CASCADE handle it. A Core-level DELETE bypasses ORM cascade
        # management entirely.
        db.query(Organization).filter(Organization.id == org.id).delete()
        db.commit()
        db.close()


def test_ftps_login_rejected_for_wrong_password(ftps_session_factory, running_server):
    db = ftps_session_factory()
    try:
        org, event = _make_event(db)
        issued = create_credential(db, event, created_by=None)
        db.commit()
        username = issued.credential.username

        ftp = _tls_client(running_server)
        ftp.auth()
        with pytest.raises(ftplib.error_perm):
            ftp.login(username, "wrong-password")
    finally:
        # Bulk delete (not session.delete(org)) -- Organization.events has
        # no cascade config, so session.delete would try to NULL out
        # events.org_id (a NOT NULL column) for any Event already loaded
        # in this session, instead of letting the DB's real ON DELETE
        # CASCADE handle it. A Core-level DELETE bypasses ORM cascade
        # management entirely.
        db.query(Organization).filter(Organization.id == org.id).delete()
        db.commit()
        db.close()


def test_ftps_login_rejected_after_revocation(ftps_session_factory, running_server):
    db = ftps_session_factory()
    try:
        org, event = _make_event(db)
        issued = create_credential(db, event, created_by=None)
        db.commit()
        revoke_credential(db, issued.credential)
        db.commit()
        username, password = issued.credential.username, issued.password

        ftp = _tls_client(running_server)
        ftp.auth()
        with pytest.raises(ftplib.error_perm):
            ftp.login(username, password)
    finally:
        # Bulk delete (not session.delete(org)) -- Organization.events has
        # no cascade config, so session.delete would try to NULL out
        # events.org_id (a NOT NULL column) for any Event already loaded
        # in this session, instead of letting the DB's real ON DELETE
        # CASCADE handle it. A Core-level DELETE bypasses ORM cascade
        # management entirely.
        db.query(Organization).filter(Organization.id == org.id).delete()
        db.commit()
        db.close()


def test_ftps_connection_cannot_list_or_retrieve(ftps_session_factory, running_server, tmp_path):
    """Write-only, on purpose -- see app/ftps/authorizer.py's
    _UPLOAD_ONLY_PERMS comment: an FTPS credential is for pushing photos
    in, never for browsing what's there, matching CLAUDE.md's "no
    browse-all-photos" constraint in spirit even though that rule is
    written about the REST API.
    """
    db = ftps_session_factory()
    try:
        org, event = _make_event(db)
        issued = create_credential(db, event, created_by=None)
        db.commit()
        username, password = issued.credential.username, issued.password

        src = tmp_path / "photo.jpg"
        src.write_bytes(b"\xff\xd8\xff\xe0filler" * 10)

        ftp = _tls_client(running_server)
        ftp.auth()
        ftp.login(username, password)
        ftp.prot_p()
        with open(src, "rb") as f:
            ftp.storbinary("STOR a.jpg", f)

        with pytest.raises(ftplib.error_perm):
            ftp.retrlines("LIST")
        with pytest.raises(ftplib.error_perm):
            ftp.retrbinary("RETR a.jpg", lambda _b: None)
    finally:
        # Bulk delete (not session.delete(org)) -- Organization.events has
        # no cascade config, so session.delete would try to NULL out
        # events.org_id (a NOT NULL column) for any Event already loaded
        # in this session, instead of letting the DB's real ON DELETE
        # CASCADE handle it. A Core-level DELETE bypasses ORM cascade
        # management entirely.
        db.query(Organization).filter(Organization.id == org.id).delete()
        db.commit()
        db.close()
