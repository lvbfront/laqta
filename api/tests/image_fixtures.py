from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from app.services.face_model import detect_and_embed


def _insightface_sample_path() -> Path:
    import insightface

    return Path(insightface.__file__).resolve().parent / "data" / "images" / "t1.jpg"


def load_group_photo_bgr() -> np.ndarray:
    """insightface ships this multi-face sample photo with the package --
    using it means tests get a genuinely detectable real face (or six)
    without checking a fixture image into this repo.
    """
    path = _insightface_sample_path()
    img = cv2.imread(str(path))
    if img is None:
        raise RuntimeError(f"could not read bundled insightface sample image at {path}")
    return img


def single_face_selfie_jpeg(*, scale: int = 1, quality: int = 92, add_noise: bool = False) -> bytes:
    """A real, single-face JPEG cropped out of the bundled sample photo.
    scale/quality/add_noise dial the byte size up (e.g. to exercise a
    realistic ~1-2MB phone-selfie upload) or keep it small and fast for
    tests that only care about correctness, not size.
    """
    img = load_group_photo_bgr()
    faces = detect_and_embed(img)
    best = max(faces, key=lambda f: f.bbox_width * f.bbox_height)
    x1, y1, x2, y2 = best.bbox
    w, h = x2 - x1, y2 - y1
    margin_x, margin_y = w * 0.8, h * 0.8
    cx1, cy1 = max(0, int(x1 - margin_x)), max(0, int(y1 - margin_y))
    cx2, cy2 = min(img.shape[1], int(x2 + margin_x)), min(img.shape[0], int(y2 + margin_y))
    crop = img[cy1:cy2, cx1:cx2]

    if scale > 1:
        crop = cv2.resize(crop, (crop.shape[1] * scale, crop.shape[0] * scale), interpolation=cv2.INTER_CUBIC)

    if add_noise:
        # JPEG compresses a plain upscale very well (it's still smooth),
        # so a pure resize doesn't reach realistic phone-photo byte sizes.
        # Mild per-pixel noise (real sensors have this anyway) defeats
        # that and gets us into the ~1-2MB range that actually exercises
        # the multipart spool-threshold fix in app/main.py.
        rng = np.random.default_rng(0)
        noise = rng.normal(0, 6, crop.shape).astype(np.int16)
        crop = np.clip(crop.astype(np.int16) + noise, 0, 255).astype(np.uint8)

    ok, buf = cv2.imencode(".jpg", crop, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        raise RuntimeError("failed to encode selfie fixture")
    return buf.tobytes()


def multi_face_photo_jpeg(quality: int = 90) -> bytes:
    img = load_group_photo_bgr()
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        raise RuntimeError("failed to encode multi-face fixture")
    return buf.tobytes()


def no_face_photo_jpeg(width: int = 300, height: int = 200) -> bytes:
    img = np.zeros((height, width, 3), dtype=np.uint8)
    ok, buf = cv2.imencode(".jpg", img)
    if not ok:
        raise RuntimeError("failed to encode blank fixture")
    return buf.tobytes()
