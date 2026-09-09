from __future__ import annotations

import logging
import mimetypes
import os

from pyftpdlib.handlers import TLS_FTPHandler

from app.db import SessionLocal
from app.services.ingest import ingest_photo

logger = logging.getLogger(__name__)


class LaqtaFTPSHandler(TLS_FTPHandler):
    """TLS_FTPHandler is per-connection state (pyftpdlib instantiates one
    per client); app.ftps.authorizer.EventCredentialAuthorizer stashes the
    authenticated credential's event_id on `self.laqta_event_id` at login,
    so every STOR on this connection knows which event it belongs to
    without a second DB lookup.
    """

    def on_file_received(self, file: str) -> None:
        event_id = getattr(self, "laqta_event_id", None)
        if event_id is None:
            # Shouldn't happen -- validate_authentication always sets this
            # before any STOR is possible -- but fail closed (drop the
            # file, don't guess an event) rather than crash the handler.
            logger.error("on_file_received: no event_id on handler for %s, dropping upload", file)
            self._cleanup(file)
            return

        try:
            with open(file, "rb") as f:
                content = f.read()
            content_type = mimetypes.guess_type(file)[0] or "image/jpeg"

            db = SessionLocal()
            try:
                result = ingest_photo(db, event_id, content, content_type)
            finally:
                db.close()

            logger.info(
                "ftps upload event=%s user=%s file=%s status=%s photo_id=%s",
                event_id,
                self.username,
                os.path.basename(file),
                result.status,
                result.photo_id,
            )
        except Exception:
            # One bad/corrupt file must not take down the FTPS session --
            # matches app/api/routes/photos.py's per-file try/except in a
            # batch REST upload. The client already received "226 Transfer
            # complete" for the raw file transfer by the time this runs
            # (FTP has no protocol-level way to fail a STOR after the
            # fact); the failure instead surfaces the same way a REST
            # ingest failure would once the worker picks it up -- as
            # photo.status='failed', or here, as never having been
            # ingested at all if ingest_photo itself raised.
            logger.exception("ftps upload failed for %s (event=%s)", file, event_id)
        finally:
            self._cleanup(file)

    def on_incomplete_file_received(self, file: str) -> None:
        self._cleanup(file)

    @staticmethod
    def _cleanup(file: str) -> None:
        try:
            os.remove(file)
        except OSError:
            pass
