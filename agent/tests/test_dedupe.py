from __future__ import annotations

from laqta_agent.hashing import compute_md5
from laqta_agent.queue_db import UploadQueue


def test_compute_md5_is_deterministic_for_identical_content(tmp_path):
    a = tmp_path / "a.jpg"
    b = tmp_path / "b.jpg"
    a.write_bytes(b"identical bytes")
    b.write_bytes(b"identical bytes")

    assert compute_md5(a) == compute_md5(b)


def test_compute_md5_differs_for_different_content(tmp_path):
    a = tmp_path / "a.jpg"
    b = tmp_path / "b.jpg"
    a.write_bytes(b"one")
    b.write_bytes(b"two")

    assert compute_md5(a) != compute_md5(b)


def test_compute_md5_returns_none_for_a_missing_file(tmp_path):
    assert compute_md5(tmp_path / "nope.jpg") is None


def test_same_content_under_a_different_path_is_recognized_as_a_duplicate(tmp_path):
    """The real scenario: a burst-mode camera (or a re-imported card)
    produces the identical file content under two different filenames/
    paths. The second one must be recognized without ever being
    uploaded, not just deduped by path.
    """
    queue = UploadQueue(tmp_path / "q.sqlite3")

    queue.enqueue("/photos/DSC_0001.jpg", "same-md5")
    queue.mark_uploading("/photos/DSC_0001.jpg")
    queue.mark_done("/photos/DSC_0001.jpg")

    # A second file, different name, identical content.
    assert queue.is_already_done("same-md5") is True
    queue.mark_done_without_uploading("/photos/DSC_0001_copy.jpg", "same-md5")

    counts = queue.counts()
    assert counts["done"] == 2
    assert counts["pending"] == 0
    # And it never went through 'uploading' for the duplicate.
    assert queue.next_ready() is None


def test_different_content_is_not_flagged_as_duplicate(tmp_path):
    queue = UploadQueue(tmp_path / "q.sqlite3")
    queue.enqueue("/photos/a.jpg", "md5-a")
    queue.mark_uploading("/photos/a.jpg")
    queue.mark_done("/photos/a.jpg")

    assert queue.is_already_done("md5-b") is False


def test_duplicate_check_ignores_files_still_pending_or_failed(tmp_path):
    """Only a confirmed 'done' upload counts as a real duplicate -- a
    file that's merely queued or still failing shouldn't suppress a
    second copy from being tried (it might be the one that actually
    succeeds).
    """
    queue = UploadQueue(tmp_path / "q.sqlite3")
    queue.enqueue("/photos/a.jpg", "md5-a")

    assert queue.is_already_done("md5-a") is False

    queue.mark_uploading("/photos/a.jpg")
    queue.mark_failed("/photos/a.jpg", "network error")
    assert queue.is_already_done("md5-a") is False
