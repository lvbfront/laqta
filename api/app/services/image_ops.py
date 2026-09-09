from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
import pyvips

THUMBNAIL_WIDTH = 300
PREVIEW_WIDTH = 1200
JPEG_QUALITY = 85
# The stored "original" is re-encoded once (to physically apply rotation
# and strip EXIF -- see load_image/prepare_original_jpeg below), so it's
# not byte-identical to the camera's file. Near-lossless quality keeps
# that re-encode visually indistinguishable from the source.
ORIGINAL_JPEG_QUALITY = 95
WATERMARK_TEXT = "Laqta · لقطة"

# Cameras at KSA events are set to local time (see docs/plan.md); EXIF
# DateTimeOriginal has no timezone field, so we interpret it as this zone.
CAPTURE_TIMEZONE = ZoneInfo("Asia/Riyadh")


def load_image(original_bytes: bytes) -> pyvips.Image:
    """Load and normalize orientation immediately: `.autorot()` physically
    rotates pixels per the EXIF Orientation tag (a no-op if there isn't
    one, e.g. PNG) and drops the tag. Without this, a sideways phone/camera
    photo stays sideways in every derivative once EXIF is stripped later --
    the orientation *tag* is gone but the pixels were never rotated to
    match. This also means face detection always sees upright pixels,
    which matters for accuracy, not just display.
    """
    image = pyvips.Image.new_from_buffer(original_bytes, "")
    return image.autorot()


def to_bgr_ndarray(image: pyvips.Image) -> np.ndarray:
    """Convert to the HxWx3 uint8 BGR array InsightFace's onnxruntime
    models expect (OpenCV convention).
    """
    rgb = image.colourspace("srgb")
    if rgb.hasalpha():
        rgb = rgb.flatten(background=[255, 255, 255])
    mem = rgb.write_to_memory()
    arr = np.frombuffer(mem, dtype=np.uint8).reshape(rgb.height, rgb.width, rgb.bands)
    return arr[:, :, ::-1].copy()  # RGB -> BGR


def read_captured_at(image: pyvips.Image) -> datetime | None:
    for field in ("exif-ifd2-DateTimeOriginal", "exif-ifd0-DateTime"):
        if field not in image.get_fields():
            continue
        raw = str(image.get(field)).split(" (")[0].strip()  # vips appends "(type, ...)" sometimes
        try:
            naive = datetime.strptime(raw, "%Y:%m:%d %H:%M:%S")
        except ValueError:
            continue
        return naive.replace(tzinfo=CAPTURE_TIMEZONE)
    return None


def prepare_original_jpeg(image: pyvips.Image) -> bytes:
    """The bytes actually persisted as a photo's 'original' in MinIO -- and
    so, eventually, what a guest's delivery-API download of an original
    receives byte-for-byte. There is no separate un-stripped copy anywhere:
    the worker downloads the raw upload, calls this, and overwrites
    s3_key_original with the result before the photo can ever become
    'ready' (see app/workers/jobs.py). GPS EXIF must never reach anything a
    guest can download, not just the thumbnail/preview derivatives.

    No resize -- full original resolution is the point of "original".
    """
    if image.hasalpha():
        image = image.flatten(background=[255, 255, 255])
    return image.write_to_buffer(".jpg", Q=ORIGINAL_JPEG_QUALITY, strip=True)


def make_thumbnail_jpeg(image: pyvips.Image, width: int = THUMBNAIL_WIDTH) -> bytes:
    # size="down": never upscale a source smaller than the target width.
    # strip=True: drop *all* metadata on write, GPS included -- see
    # CLAUDE.md "Strip GPS EXIF from every derivative image."
    resized = image.thumbnail_image(width, size="down")
    if resized.hasalpha():
        resized = resized.flatten(background=[255, 255, 255])
    return resized.write_to_buffer(".jpg", Q=JPEG_QUALITY, strip=True)


def _watermark_tile(tile_width: int, text: str = WATERMARK_TEXT) -> pyvips.Image:
    text_img = pyvips.Image.text(text, width=tile_width, dpi=200, align="centre").rotate(-30)
    alpha = (text_img * 0.35).cast("uchar")
    white = (pyvips.Image.black(alpha.width, alpha.height, bands=3) + [255, 255, 255]).cast("uchar")
    return white.bandjoin(alpha).copy(interpretation="srgb")


def make_watermarked_preview_jpeg(image: pyvips.Image, width: int = PREVIEW_WIDTH) -> bytes:
    resized = image.thumbnail_image(width, size="down").colourspace("srgb")
    if not resized.hasalpha():
        resized = resized.bandjoin(255)

    tile = _watermark_tile(tile_width=max(200, resized.width // 3))
    step_x, step_y = tile.width + 40, tile.height + 60

    result = resized
    y = -step_y // 2
    while y < resized.height:
        x = -step_x // 2
        while x < resized.width:
            result = result.composite2(tile, "over", x=x, y=y)
            x += step_x
        y += step_y

    flattened = result.flatten(background=[255, 255, 255])
    return flattened.write_to_buffer(".jpg", Q=JPEG_QUALITY, strip=True)
