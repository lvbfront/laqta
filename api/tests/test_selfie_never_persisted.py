from __future__ import annotations

import builtins
import logging
import tempfile
from unittest.mock import patch

import numpy as np

from tests import image_fixtures
from tests.factories import make_event, make_organization


def test_selfie_bytes_never_touch_disk_minio_or_logs(client, db_session, caplog):
    """CLAUDE.md: the selfie is never persisted -- not to disk, object
    storage, temp files, or logs. In-memory only, embed, then discard.
    This patches the exact mechanisms that could violate that and fails
    the request if any of them fire:

      - tempfile.SpooledTemporaryFile.rollover: what Starlette's own
        multipart parser calls if an upload exceeds its in-memory spool
        threshold and spills to a real temp file -- confirmed during
        development that this fires for a 2MB upload under Starlette's
        1MB default, which is smaller than a typical phone selfie. Fixed
        in app/main.py by raising the threshold; this test is what proves
        that fix actually holds for a realistic upload, not a token one.
      - builtins.open in any write-capable mode, anywhere in the process
        during the request.
      - app.storage.minio_client's upload/download/get_client -- the match
        endpoint should never touch object storage at all, not just avoid
        writing the selfie there.
      - every captured log record, for a fragment of the raw selfie bytes.
    """
    # Warm the model singleton *before* patching -- loading it legitimately
    # touches disk (reading cached ONNX weights), which has nothing to do
    # with whether a *selfie* does.
    from app.services import face_model

    face_model.detect_and_embed(np.zeros((64, 64, 3), dtype=np.uint8))

    org = make_organization(db_session)
    event = make_event(db_session, org)
    db_session.flush()

    selfie_bytes = image_fixtures.single_face_selfie_jpeg(scale=5, quality=97, add_noise=True)
    assert len(selfie_bytes) > 1_000_000, "fixture isn't realistically sized -- would pass trivially"

    disk_writes: list[bool] = []
    orig_rollover = tempfile.SpooledTemporaryFile.rollover

    def spy_rollover(self, *a, **kw):
        disk_writes.append(True)
        return orig_rollover(self, *a, **kw)

    orig_open = builtins.open

    def guarded_open(file, mode="r", *args, **kwargs):
        if any(c in mode for c in "wax+"):
            raise AssertionError(f"file opened in write-capable mode {mode!r} during selfie request: {file!r}")
        return orig_open(file, mode, *args, **kwargs)

    with (
        patch("tempfile.SpooledTemporaryFile.rollover", spy_rollover),
        patch("builtins.open", guarded_open),
        patch("app.storage.minio_client.upload_bytes") as mock_upload,
        patch("app.storage.minio_client.download_bytes") as mock_download,
        patch("app.storage.minio_client.get_client") as mock_get_client,
        # Scoped to our own app logger, not the root logger: pyvips logs
        # every operation at DEBUG level, *including the raw image buffer
        # bytes themselves* -- capturing at root level floods this with
        # multiple megabytes of pyvips internals and, worse, was observed
        # to trigger an unrelated SpooledTemporaryFile.rollover elsewhere
        # in the process (most likely pytest's own log-capture buffering
        # under that volume), producing a false positive on the exact
        # assertion below. app/main.py separately pins pyvips's logger
        # above WARNING unconditionally for the same underlying reason;
        # this scoping is what makes the log-content check below a
        # meaningful test of *our* code rather than noise from pyvips's.
        caplog.at_level(logging.DEBUG, logger="app"),
    ):
        resp = client.post(
            f"/api/events/{event.id}/match",
            files={"selfie": ("selfie.jpg", selfie_bytes, "image/jpeg")},
            data={"consent": "true"},
        )

    assert resp.status_code == 200, resp.text
    assert disk_writes == [], "selfie upload spilled to a real temp file on disk"
    mock_upload.assert_not_called()
    mock_download.assert_not_called()
    mock_get_client.assert_not_called()

    needle = repr(selfie_bytes[:64])
    for record in caplog.records:
        assert needle not in record.getMessage(), "selfie bytes leaked into a log message"
        assert not any(v is selfie_bytes for v in record.__dict__.values()), "selfie bytes referenced by a log record"
