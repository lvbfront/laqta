from __future__ import annotations

import os

from pyftpdlib.authorizers import AuthenticationFailed, AuthorizerError

from app.config import settings
from app.db import SessionLocal
from app.services.ftp_credentials import authenticate

# Write-only, on purpose -- CLAUDE.md's "no browse-all-photos endpoint or
# view, for any role, at any time" is written about the REST API, but the
# same principle applies here: an FTPS credential exists to push photos
# in, never to list or pull anything back out. No retrieve ('r'), no
# directory listing ('l'), no delete/rename/mkdir.
_UPLOAD_ONLY_PERMS = "w"


class EventCredentialAuthorizer:
    """A pyftpdlib authorizer backed by EventFtpCredential rows instead of
    an in-memory user table (pyftpdlib.authorizers.DummyAuthorizer's usual
    approach) -- credentials are issued/revoked live via the API
    (app/api/routes/ftp_credentials.py), so there's no fixed user list to
    preload at server startup. Each method opens and closes its own short
    DB session; pyftpdlib's default handler runs a single-threaded
    asyncore loop, so these calls are never concurrent with each other.

    Implements the duck-typed interface pyftpdlib.servers.FTPServer
    expects (validate_authentication, get_home_dir, get_msg_login,
    get_msg_quit, has_user, has_perm, get_perms, impersonate_user,
    terminate_impersonation) -- see pyftpdlib's authorizers module docs.
    """

    def validate_authentication(self, username: str, password: str, handler) -> None:  # noqa: ANN001
        db = SessionLocal()
        try:
            credential = authenticate(db, username, password)
        finally:
            db.close()
        if credential is None:
            raise AuthenticationFailed("Authentication failed.")
        # Cached on the handler so on_file_received (app/ftps/handler.py)
        # doesn't need a second DB round-trip per upload to resolve which
        # event this connection belongs to.
        handler.laqta_event_id = credential.event_id

    def get_home_dir(self, username: str) -> str:
        home = os.path.join(settings.ftps_upload_root, username)
        os.makedirs(home, exist_ok=True)
        return home

    def get_msg_login(self, username: str) -> str:
        return "Welcome. This connection can upload photos only."

    def get_msg_quit(self, username: str) -> str:
        return "Goodbye."

    def has_user(self, username: str) -> bool:
        db = SessionLocal()
        try:
            from app.models.event_ftp_credential import EventFtpCredential

            return (
                db.query(EventFtpCredential)
                .filter(EventFtpCredential.username == username, EventFtpCredential.revoked_at.is_(None))
                .first()
                is not None
            )
        finally:
            db.close()

    def has_perm(self, username: str, perm: str, path: str | None = None) -> bool:
        return perm in _UPLOAD_ONLY_PERMS

    def get_perms(self, username: str) -> str:
        return _UPLOAD_ONLY_PERMS

    def impersonate_user(self, username: str, password: str) -> None:
        # No OS-level user switching -- every credential maps to the same
        # process user, scoped only by its own upload-root subdirectory
        # and the DB-side event_id association. Required by the
        # authorizer interface; intentionally a no-op.
        pass

    def terminate_impersonation(self, username: str) -> None:
        pass


__all__ = ["EventCredentialAuthorizer", "AuthorizerError"]
