from __future__ import annotations

import pyvips

from app.services import image_ops


def _jpeg_with_gps_and_orientation() -> bytes:
    """A synthetic photo with GPS EXIF and a sideways orientation tag --
    stands in for a real camera JPEG (GPS-tagged phones/cameras are the
    norm, not the exception) without needing a real photo fixture.
    """
    img = (pyvips.Image.black(200, 150, bands=3) + [120, 80, 40]).copy()
    img.set_type(pyvips.GValue.gint_type, "orientation", 6)
    img.set_type(pyvips.GValue.gstr_type, "exif-ifd3-GPSLatitudeRef", "N")
    img.set_type(pyvips.GValue.gstr_type, "exif-ifd3-GPSLatitude", "24/1 42/1 0/1")
    img.set_type(pyvips.GValue.gstr_type, "exif-ifd3-GPSLongitudeRef", "E")
    img.set_type(pyvips.GValue.gstr_type, "exif-ifd3-GPSLongitude", "46/1 40/1 0/1")
    img.set_type(pyvips.GValue.gstr_type, "exif-ifd2-DateTimeOriginal", "2026:09:09 10:00:00")
    return img.write_to_buffer(".jpg", Q=90)


def _has_gps_fields(image: pyvips.Image) -> bool:
    return any("GPS" in field for field in image.get_fields())


def test_source_fixture_really_has_gps():
    # Sanity check on the fixture itself, so the assertions below mean
    # something -- if this ever fails, the other tests in this file are
    # vacuous.
    loaded = image_ops.load_image(_jpeg_with_gps_and_orientation())
    assert _has_gps_fields(loaded)


def test_prepare_original_jpeg_strips_gps():
    """app.workers.jobs.process_photo overwrites s3_key_original with
    exactly these bytes before a photo can ever reach status='ready' --
    this is what a guest's delivery-API download of an original actually
    receives, byte for byte. No GPS may survive into it.
    """
    loaded = image_ops.load_image(_jpeg_with_gps_and_orientation())
    stored = image_ops.prepare_original_jpeg(loaded)

    reloaded = pyvips.Image.new_from_buffer(stored, "")
    assert not _has_gps_fields(reloaded)


def test_prepare_original_jpeg_preserves_orientation_as_pixels_not_a_tag():
    # The whole reason load_image() calls .autorot() before anything else:
    # once EXIF is stripped, there's no tag left to correct a sideways
    # image -- rotation has to already be baked into the pixels.
    loaded = image_ops.load_image(_jpeg_with_gps_and_orientation())
    assert (loaded.width, loaded.height) == (150, 200)  # rotated 200x150 -> 150x200

    stored = image_ops.prepare_original_jpeg(loaded)
    reloaded = pyvips.Image.new_from_buffer(stored, "")
    assert (reloaded.width, reloaded.height) == (150, 200)
    assert "orientation" not in reloaded.get_fields()


def test_thumbnail_and_preview_also_have_no_gps():
    # Not new coverage on its own (CLAUDE.md's derivative-stripping
    # requirement), but pinned here alongside the original so all three
    # guest-reachable artifacts are checked in one place.
    loaded = image_ops.load_image(_jpeg_with_gps_and_orientation())
    thumb = pyvips.Image.new_from_buffer(image_ops.make_thumbnail_jpeg(loaded), "")
    preview = pyvips.Image.new_from_buffer(image_ops.make_watermarked_preview_jpeg(loaded), "")
    assert not _has_gps_fields(thumb)
    assert not _has_gps_fields(preview)
