from __future__ import annotations

from app.services.face_model import DetectedFace
from app.workers.pipeline import _passes_quality_gate


def _face(width: float, height: float, det_score: float) -> DetectedFace:
    return DetectedFace(bbox=(0.0, 0.0, width, height), det_score=det_score, embedding=[0.0])


def test_passes_when_above_both_thresholds():
    assert _passes_quality_gate(_face(width=100, height=100, det_score=0.9))


def test_fails_when_bbox_too_small_on_either_side():
    assert not _passes_quality_gate(_face(width=39, height=100, det_score=0.9))
    assert not _passes_quality_gate(_face(width=100, height=39, det_score=0.9))


def test_fails_when_det_score_too_low():
    assert not _passes_quality_gate(_face(width=100, height=100, det_score=0.49))


def test_boundary_values_pass():
    from app.config import settings

    assert _passes_quality_gate(
        _face(width=settings.min_face_bbox_px, height=settings.min_face_bbox_px, det_score=settings.min_det_score)
    )
