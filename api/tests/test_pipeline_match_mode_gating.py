"""match_mode='code' events must never run face detection on ingested
photos, not merely discard the result -- see app/workers/pipeline.py's
process_photo_bytes(run_face_detection=...) and the docstring on
app/api/routes/match.py's match_by_code for why (CLAUDE.md: "All face
processing runs locally via InsightFace" is a promise that's only
meaningful if it's also a promise that non-face events skip it).
"""

from __future__ import annotations

import io

from PIL import Image

from app.workers.pipeline import process_photo_bytes


def _plain_jpeg_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (200, 150), color=(120, 130, 140)).save(buf, format="JPEG")
    return buf.getvalue()


def test_run_face_detection_false_never_imports_the_face_model(monkeypatch):
    """The strongest version of this guarantee: not just "returns no
    faces" but "never even touches face_model.detect_and_embed" -- so a
    code-mode event's worker never loads onnxruntime/insightface at all.
    """
    import app.workers.pipeline as pipeline

    def _fail_if_called(*args, **kwargs):
        raise AssertionError("detect_and_embed must not be called when run_face_detection=False")

    monkeypatch.setattr(pipeline, "detect_and_embed", _fail_if_called)

    result = process_photo_bytes(_plain_jpeg_bytes(), run_face_detection=False)
    assert result.faces == []
    # sanity: the rest of the pipeline (derivatives, dimensions) still ran
    assert result.width == 200
    assert result.height == 150
    assert result.thumbnail_jpeg
    assert result.preview_jpeg


def test_run_face_detection_true_is_still_the_default_and_finds_a_real_face():
    from tests.image_fixtures import single_face_selfie_jpeg

    result = process_photo_bytes(single_face_selfie_jpeg())
    assert len(result.faces) >= 1


def test_process_photo_job_skips_detection_for_a_code_mode_event(db_session, monkeypatch):
    """app.workers.jobs.process_photo (the actual RQ job, not just the
    pure pipeline function) must derive run_face_detection from the
    photo's own event.match_mode -- this is what makes the guarantee real
    for an actual upload, not just for a direct process_photo_bytes call.
    """
    import app.workers.pipeline as pipeline
    from app.models.enums import MatchMode, PhotoStatus
    from app.workers import jobs
    from tests.factories import make_event, make_organization, make_photo

    org = make_organization(db_session)
    event = make_event(db_session, org, match_mode=MatchMode.code)
    photo = make_photo(db_session, event, status=PhotoStatus.pending)
    db_session.commit()

    def _fail_if_called(*args, **kwargs):
        raise AssertionError("detect_and_embed must not run for a code-mode event's photo")

    monkeypatch.setattr(pipeline, "detect_and_embed", _fail_if_called)
    monkeypatch.setattr(jobs, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(jobs.minio_client, "download_bytes", lambda key: _plain_jpeg_bytes())
    monkeypatch.setattr(jobs.minio_client, "upload_bytes", lambda *a, **k: None)
    monkeypatch.setattr(db_session, "close", lambda: None)  # conftest's fixture owns the real close

    jobs.process_photo(str(photo.id))

    from app.models.face import Face
    from app.models.photo import Photo

    refreshed = db_session.get(Photo, photo.id)
    assert refreshed.status == PhotoStatus.ready
    assert db_session.query(Face).filter(Face.photo_id == photo.id).count() == 0
