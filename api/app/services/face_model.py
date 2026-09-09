from __future__ import annotations

import threading
from dataclasses import dataclass

import numpy as np

from app.config import settings

ALIGNED_CROP_SIZE = 112

_lock = threading.Lock()
_face_app = None  # type: ignore[var-annotated]


def _get_face_app():
    """Lazily load the buffalo_l detection + recognition models on first
    use, once per process. Loading is slow (~1-2s) and the models are
    reused across every photo/selfie a worker or API process handles, so
    this must not run per-request/per-job.
    """
    global _face_app
    if _face_app is None:
        with _lock:
            if _face_app is None:
                # Imported lazily -- insightface pulls in onnxruntime and
                # triggers a model-pack download on first construction, so
                # keep that off the import path of anything that doesn't
                # actually need it (e.g. the API's non-ML routes).
                from insightface.app import FaceAnalysis

                app = FaceAnalysis(
                    name=settings.face_model_pack,
                    allowed_modules=["detection", "recognition"],
                    # Pinned explicitly, not left to onnxruntime's default
                    # provider auto-selection -- on Apple Silicon dev
                    # machines onnxruntime also reports CoreMLExecutionProvider
                    # as available, and CoreML is unreliable with InsightFace's
                    # graphs (see docs/plan.md, CLAUDE.md). CPU only, always.
                    providers=[settings.onnxruntime_provider],
                )
                # ctx_id=-1 additionally forces the recognition model's own
                # provider selection to CPU (see ArcFaceONNX.prepare) --
                # belt and suspenders alongside the providers= pin above.
                app.prepare(ctx_id=-1, det_thresh=0.3, det_size=(640, 640))
                _face_app = app
    return _face_app


@dataclass(frozen=True)
class DetectedFace:
    bbox: tuple[float, float, float, float]  # x1, y1, x2, y2, original image pixels
    det_score: float
    embedding: list[float]  # L2-normalized 512-d ArcFace embedding, from the aligned crop

    @property
    def bbox_width(self) -> float:
        return self.bbox[2] - self.bbox[0]

    @property
    def bbox_height(self) -> float:
        return self.bbox[3] - self.bbox[1]


def detect_and_embed(image_bgr: np.ndarray) -> list[DetectedFace]:
    """Run buffalo_l detection over `image_bgr`, align each detected face to
    a 112x112 crop using its five landmarks (similarity transform), and
    embed the aligned crop -- never the raw detection crop.

    Detection here uses a permissive det_thresh (0.3, set in
    `_get_face_app`) so borderline faces still come back with their real
    score; the actual business quality gate (min bbox px, min det score)
    is applied by the caller (app.workers.pipeline), not here, so this
    function stays a pure "what did the model see" primitive that
    scripts/embed_folder.py can also use for threshold tuning.
    """
    from insightface.utils import face_align

    face_app = _get_face_app()
    detector = face_app.models["detection"]
    recognizer = face_app.models["recognition"]

    bboxes, kpss = detector.detect(image_bgr, max_num=0, metric="default")

    results: list[DetectedFace] = []
    if bboxes is None:
        return results

    for i in range(bboxes.shape[0]):
        x1, y1, x2, y2, det_score = bboxes[i]
        landmarks = kpss[i]

        aligned = face_align.norm_crop(image_bgr, landmark=landmarks, image_size=ALIGNED_CROP_SIZE)

        raw_embedding = recognizer.get_feat(aligned).flatten()
        norm = np.linalg.norm(raw_embedding)
        embedding = raw_embedding / norm if norm > 0 else raw_embedding

        results.append(
            DetectedFace(
                bbox=(float(x1), float(y1), float(x2), float(y2)),
                det_score=float(det_score),
                embedding=embedding.astype(float).tolist(),
            )
        )
    return results
