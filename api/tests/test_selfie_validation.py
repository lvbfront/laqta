from __future__ import annotations

from unittest.mock import patch

import numpy as np
import pytest

from app.api.routes.match import SelfieValidationError, _validate_selfie
from app.config import settings
from app.services.face_model import DetectedFace

DUMMY_BGR = np.zeros((200, 200, 3), dtype=np.uint8)


def _face(width=100.0, height=100.0, det_score=0.9) -> DetectedFace:
    return DetectedFace(bbox=(0.0, 0.0, width, height), det_score=det_score, embedding=[0.0] * 512)


def test_no_face_detected():
    with patch("app.api.routes.match.detect_and_embed", return_value=[]):
        with pytest.raises(SelfieValidationError) as exc:
            _validate_selfie(DUMMY_BGR)
    assert exc.value.code == "no_face_detected"


def test_multiple_faces_detected():
    with patch("app.api.routes.match.detect_and_embed", return_value=[_face(), _face()]):
        with pytest.raises(SelfieValidationError) as exc:
            _validate_selfie(DUMMY_BGR)
    assert exc.value.code == "multiple_faces_detected"


def test_low_detection_confidence():
    low_score = settings.min_det_score - 0.01
    with patch("app.api.routes.match.detect_and_embed", return_value=[_face(det_score=low_score)]):
        with pytest.raises(SelfieValidationError) as exc:
            _validate_selfie(DUMMY_BGR)
    assert exc.value.code == "low_detection_confidence"


def test_face_too_small():
    small = settings.min_face_bbox_px - 1
    with patch("app.api.routes.match.detect_and_embed", return_value=[_face(width=small, height=200)]):
        with pytest.raises(SelfieValidationError) as exc:
            _validate_selfie(DUMMY_BGR)
    assert exc.value.code == "face_too_small"

    with patch("app.api.routes.match.detect_and_embed", return_value=[_face(width=200, height=small)]):
        with pytest.raises(SelfieValidationError) as exc:
            _validate_selfie(DUMMY_BGR)
    assert exc.value.code == "face_too_small"


def test_selfie_too_blurry():
    with patch("app.api.routes.match.detect_and_embed", return_value=[_face()]):
        with patch("app.services.image_ops.laplacian_variance", return_value=settings.min_blur_variance - 1):
            with pytest.raises(SelfieValidationError) as exc:
                _validate_selfie(DUMMY_BGR)
    assert exc.value.code == "selfie_too_blurry"


def test_valid_selfie_passes_and_returns_the_face():
    face = _face()
    with patch("app.api.routes.match.detect_and_embed", return_value=[face]):
        with patch("app.services.image_ops.laplacian_variance", return_value=settings.min_blur_variance + 1):
            result = _validate_selfie(DUMMY_BGR)
    assert result is face


def test_checks_run_in_spec_order_face_count_then_score_then_size_then_blur():
    # A face failing every check at once should report the *first*
    # failure in the spec's order, not whichever the implementation
    # happens to check last -- this pins that order against regressions.
    bad_score_and_size = _face(width=1.0, height=1.0, det_score=0.0)
    with patch("app.api.routes.match.detect_and_embed", return_value=[bad_score_and_size]):
        with pytest.raises(SelfieValidationError) as exc:
            _validate_selfie(DUMMY_BGR)
    assert exc.value.code == "low_detection_confidence"
