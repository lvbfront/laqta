from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.config import settings
from app.services import image_ops
from app.services.face_model import DetectedFace, detect_and_embed


@dataclass(frozen=True)
class ProcessedPhoto:
    width: int
    height: int
    captured_at: datetime | None
    original_jpeg: bytes
    thumbnail_jpeg: bytes
    preview_jpeg: bytes
    faces: list[DetectedFace]


def _passes_quality_gate(face: DetectedFace) -> bool:
    """Business quality gate, applied after detection: drop faces whose
    bounding box is under MIN_FACE_BBOX_PX on its shorter side, or whose
    detection score is under MIN_DET_SCORE. Distinct from the model's own
    det_thresh (set permissively in face_model._get_face_app) so this gate
    -- the one that actually decides what becomes a searchable `faces` row
    -- lives in one place and is easy to retune.
    """
    if min(face.bbox_width, face.bbox_height) < settings.min_face_bbox_px:
        return False
    if face.det_score < settings.min_det_score:
        return False
    return True


def process_photo_bytes(original_bytes: bytes) -> ProcessedPhoto:
    """Pure pipeline core: raw uploaded JPEG bytes in, a re-encoded
    (autorotated, GPS/EXIF-stripped) original + derivatives + gated face
    detections out. No DB, no object storage -- app.workers.jobs wires this
    to Postgres/MinIO (overwriting the raw upload with original_jpeg), and
    scripts/embed_folder.py uses the lower-level face_model.detect_and_embed
    directly (ungated) for threshold tuning.
    """
    image = image_ops.load_image(original_bytes)
    bgr = image_ops.to_bgr_ndarray(image)

    all_faces = detect_and_embed(bgr)
    gated_faces = [f for f in all_faces if _passes_quality_gate(f)]

    return ProcessedPhoto(
        width=image.width,
        height=image.height,
        captured_at=image_ops.read_captured_at(image),
        original_jpeg=image_ops.prepare_original_jpeg(image),
        thumbnail_jpeg=image_ops.make_thumbnail_jpeg(image),
        preview_jpeg=image_ops.make_watermarked_preview_jpeg(image),
        faces=gated_faces,
    )
