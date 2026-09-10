from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.utils import client_ip
from app.config import settings
from app.db import get_db
from app.models.enums import MatchMode
from app.models.event import Event
from app.models.guest import Guest
from app.models.guest_face import GuestFace
from app.models.match import Match
from app.models.photo import Photo
from app.models.photo_code import PhotoCode
from app.services import image_ops
from app.services.face_model import DetectedFace, detect_and_embed
from app.services.face_search import search_faces

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/events/{event_id}/match", tags=["match"])


@dataclass(frozen=True)
class SelfieValidationError(Exception):
    """Distinct, actionable failure modes -- the guest needs to know
    whether to move into better light, take the photo alone, or hold the
    camera steady, not just "try again". `code` is the stable machine-
    readable identifier the frontend switches on; `message` is a
    ready-to-display (English) fallback.
    """

    code: str
    message: str


class PhotoMatchResult(BaseModel):
    photo_id: uuid.UUID
    score: float


class MatchResponse(BaseModel):
    guest_session_token: str
    matches: list[PhotoMatchResult]


def _validate_selfie(bgr) -> DetectedFace:  # noqa: ANN001 -- numpy array, see face_model.detect_and_embed
    """Every check here runs before any embedding is searched against the
    event's faces -- a selfie that fails validation is never compared
    against anything. Order matches the product spec: face count, then
    detection confidence, then crop size, then blur.
    """
    faces = detect_and_embed(bgr)

    if len(faces) == 0:
        raise SelfieValidationError(
            "no_face_detected",
            "We couldn't find a face in your photo. Make sure your face is clearly visible and try again.",
        )
    if len(faces) > 1:
        raise SelfieValidationError(
            "multiple_faces_detected",
            "We detected more than one face. Please take a selfie of yourself alone.",
        )

    face = faces[0]

    if face.det_score < settings.min_det_score:
        raise SelfieValidationError(
            "low_detection_confidence",
            "We couldn't get a clear reading of your face. Try better lighting, and remove "
            "sunglasses, a mask, or a hat if you're wearing one.",
        )

    if min(face.bbox_width, face.bbox_height) < settings.min_face_bbox_px:
        raise SelfieValidationError(
            "face_too_small",
            "Your face is too small in the frame. Move closer to the camera and try again.",
        )

    x1, y1, x2, y2 = (max(0, int(v)) for v in face.bbox)
    blur_variance = image_ops.laplacian_variance(bgr[y1:y2, x1:x2])
    if blur_variance < settings.min_blur_variance:
        raise SelfieValidationError(
            "selfie_too_blurry",
            "Your photo looks blurry. Hold the camera steady, or clean your camera lens, and try again.",
        )

    return face


@router.post("", response_model=MatchResponse)
async def match_selfie(
    event_id: uuid.UUID,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    selfie: Annotated[UploadFile, File(...)],
    consent: Annotated[bool, Form(...)],
) -> MatchResponse:
    """Selfie in, matched photos out. The selfie is never written to disk,
    MinIO, a temp file, or a log line -- it's decoded in memory, embedded,
    and every reference to its bytes goes out of scope when this function
    returns. See tests/test_selfie_never_persisted.py, which patches the
    storage client and the filesystem's own spill-to-disk path and fails
    if either is touched.
    """
    event = db.get(Event, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail={"code": "event_not_found", "message": "Event not found."})
    if event.match_mode in (MatchMode.code, MatchMode.sequential):
        # A code/sequential event's whole point is that no biometric data
        # is ever processed for it (docs/plan.md) -- refusing here is what
        # actually makes that a guarantee rather than a UI convention a
        # guest (or a frontend bug) could bypass by hitting this endpoint
        # directly.
        raise HTTPException(
            status_code=409,
            detail={
                "code": "wrong_match_mode",
                "message": "This event uses code-based matching, not selfies.",
            },
        )

    if not consent:
        raise HTTPException(
            status_code=400,
            detail={"code": "consent_required", "message": "Consent is required to search for your photos."},
        )

    selfie_bytes = await selfie.read()
    if not selfie_bytes:
        raise HTTPException(status_code=422, detail={"code": "empty_selfie", "message": "No image data received."})
    if len(selfie_bytes) > settings.max_selfie_upload_bytes:
        raise HTTPException(
            status_code=413,
            detail={"code": "selfie_too_large", "message": "That image is larger than we accept for a selfie."},
        )

    image = image_ops.load_image(selfie_bytes)
    bgr = image_ops.to_bgr_ndarray(image)

    try:
        face = _validate_selfie(bgr)
    except SelfieValidationError as exc:
        raise HTTPException(status_code=422, detail={"code": exc.code, "message": exc.message}) from exc

    guest = Guest(
        event_id=event_id,
        consent_at=datetime.now(timezone.utc),
        consent_ip=client_ip(request),
        selfie_deleted_at=datetime.now(timezone.utc),
    )
    db.add(guest)
    db.flush()

    db.add(
        GuestFace(
            guest_id=guest.id,
            embedding=face.embedding,
            expires_at=datetime.now(timezone.utc) + timedelta(days=settings.guest_face_retention_days),
        )
    )

    raw_results = search_faces(
        db,
        event_id=event_id,
        query_embedding=face.embedding,
        threshold=settings.match_threshold,
    )

    logger.debug(
        "match scores event=%s guest=%s threshold=%.3f n=%d scores=%s",
        event_id,
        guest.id,
        settings.match_threshold,
        len(raw_results),
        sorted((round(r.score, 4) for r in raw_results), reverse=True),
    )

    best_score_by_photo: dict[uuid.UUID, float] = {}
    for r in raw_results:
        if r.score > best_score_by_photo.get(r.photo_id, -1.0):
            best_score_by_photo[r.photo_id] = r.score

    # Only ever surface published photos -- a strict-mode event's
    # unmoderated photos must never appear in a guest's results, not even
    # as "you have N matches" metadata. DB layer enforces auto_publish via
    # ck_events_strict_requires_no_autopublish; this is the API-layer half
    # of that same guarantee (CLAUDE.md). Applied as a plain post-filter,
    # not folded into search_faces' query, so it can't reintroduce the
    # filtered-ANN recall issue that faces.event_id was denormalized to
    # avoid -- see app/services/face_search.py.
    published_photo_ids: set[uuid.UUID] = set()
    if best_score_by_photo:
        published_photo_ids = {
            row.id
            for row in db.query(Photo.id).filter(
                Photo.id.in_(best_score_by_photo.keys()), Photo.published.is_(True)
            )
        }

    matches = sorted(
        (
            PhotoMatchResult(photo_id=pid, score=score)
            for pid, score in best_score_by_photo.items()
            if pid in published_photo_ids
        ),
        key=lambda m: m.score,
        reverse=True,
    )

    for m in matches:
        db.add(Match(guest_id=guest.id, photo_id=m.photo_id, score=m.score))

    db.commit()

    return MatchResponse(guest_session_token=guest.session_token, matches=matches)


class CodeMatchRequest(BaseModel):
    code: str


@router.post("/code", response_model=MatchResponse)
def match_by_code(
    event_id: uuid.UUID,
    request: Request,
    body: CodeMatchRequest,
    db: Annotated[Session, Depends(get_db)],
) -> MatchResponse:
    """No selfie, no embedding, no face pipeline touched at all -- a plain
    DB lookup against codes staff tagged onto photos
    (app.api.routes.photos.add_photo_code). This is what match_mode='code'
    is for: conservative clients who won't accept biometric processing at
    all (docs/plan.md's §7.2 women's-events wedge and the marathons/
    schools use case both lean on this). Nothing here imports/calls
    anything from app.services.face_model or app.workers.pipeline --
    face_model's own insightface/onnxruntime imports are already lazy
    (deferred to first call, not module import -- see face_model.py), so
    a code-match request never pays any face-pipeline cost, not even a
    model load, regardless of what else this file imports for the selfie
    endpoint above.
    """
    event = db.get(Event, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail={"code": "event_not_found", "message": "Event not found."})
    if event.match_mode == MatchMode.face:
        raise HTTPException(
            status_code=409,
            detail={"code": "wrong_match_mode", "message": "This event uses selfie matching, not codes."},
        )

    code = body.code.strip()
    if not code:
        raise HTTPException(status_code=422, detail={"code": "empty_code", "message": "Enter your code."})

    # No consent flag, no guest_faces row -- there is no biometric
    # collection happening here to consent to. A Guest row still gets
    # created (session/audit trail, and matches needs a guest_id to hang
    # off of), just without anything selfie-shaped attached to it.
    guest = Guest(
        event_id=event_id,
        consent_at=datetime.now(timezone.utc),
        consent_ip=client_ip(request),
    )
    db.add(guest)
    db.flush()

    photo_ids = {
        row.photo_id
        for row in db.query(PhotoCode.photo_id)
        .join(Photo, Photo.id == PhotoCode.photo_id)
        .filter(Photo.event_id == event_id, PhotoCode.code == code, Photo.published.is_(True))
    }

    matches = [PhotoMatchResult(photo_id=pid, score=1.0) for pid in photo_ids]

    for m in matches:
        db.add(Match(guest_id=guest.id, photo_id=m.photo_id, score=m.score))

    db.commit()

    logger.debug("code match event=%s guest=%s code=%r found=%d", event_id, guest.id, code, len(matches))

    return MatchResponse(guest_session_token=guest.session_token, matches=matches)
