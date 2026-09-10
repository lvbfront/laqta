from __future__ import annotations

from laqta_agent.queue_db import UploadQueue, backoff_seconds


def test_enqueue_and_next_ready(tmp_path):
    queue = UploadQueue(tmp_path / "q.sqlite3")
    queue.enqueue("/photos/a.jpg", "md5-a")

    record = queue.next_ready()
    assert record is not None
    assert record.path == "/photos/a.jpg"
    assert record.status == "pending"


def test_enqueue_is_idempotent_by_path(tmp_path):
    queue = UploadQueue(tmp_path / "q.sqlite3")
    queue.enqueue("/photos/a.jpg", "md5-a")
    queue.mark_done("/photos/a.jpg")

    # Re-enqueuing the same path (e.g. a second filesystem event for it)
    # must not reset it back to pending.
    queue.enqueue("/photos/a.jpg", "md5-a")
    assert queue.counts()["done"] == 1
    assert queue.counts()["pending"] == 0


def test_mark_done_removes_it_from_next_ready(tmp_path):
    queue = UploadQueue(tmp_path / "q.sqlite3")
    queue.enqueue("/photos/a.jpg", "md5-a")
    queue.mark_uploading("/photos/a.jpg")
    queue.mark_done("/photos/a.jpg")

    assert queue.next_ready() is None
    assert queue.counts() == {"pending": 0, "uploading": 0, "done": 1, "failed": 0}


def test_mark_failed_sets_a_future_retry_time_not_immediately_ready(tmp_path):
    queue = UploadQueue(tmp_path / "q.sqlite3")
    queue.enqueue("/photos/a.jpg", "md5-a")
    queue.mark_uploading("/photos/a.jpg")
    queue.mark_failed("/photos/a.jpg", "network error")

    # backoff_seconds(1) is >= RETRY_BASE_DELAY_SECONDS (2s) -- not due yet.
    assert queue.next_ready() is None
    assert queue.counts()["failed"] == 1

    errors = queue.recent_errors()
    assert len(errors) == 1
    assert errors[0].last_error == "network error"
    assert errors[0].attempts == 1


def test_backoff_doubles_and_caps():
    assert backoff_seconds(1) == 2.0
    assert backoff_seconds(2) == 4.0
    assert backoff_seconds(3) == 8.0
    assert backoff_seconds(20) == 300.0  # capped at RETRY_MAX_DELAY_SECONDS


def test_queue_survives_a_restart(tmp_path):
    """The whole point of SQLite over in-memory state -- closing and
    reopening the connection (simulating an app restart) must not lose
    anything.
    """
    db_path = tmp_path / "q.sqlite3"

    queue = UploadQueue(db_path)
    queue.enqueue("/photos/a.jpg", "md5-a")
    queue.enqueue("/photos/b.jpg", "md5-b")
    queue.mark_uploading("/photos/a.jpg")
    queue.mark_done("/photos/a.jpg")
    queue.close()

    reopened = UploadQueue(db_path)
    assert reopened.counts() == {"pending": 1, "uploading": 0, "done": 1, "failed": 0}
    assert reopened.is_already_done("md5-a")
    record = reopened.next_ready()
    assert record is not None
    assert record.path == "/photos/b.jpg"


def test_a_restart_never_re_uploads_an_already_done_file(tmp_path):
    """Direct coverage of the stated requirement: MD5 client-side so a
    restart never re-uploads. Simulates the agent's own startup catch-up
    scan finding the same file again after a restart.
    """
    db_path = tmp_path / "q.sqlite3"

    queue = UploadQueue(db_path)
    queue.enqueue("/photos/a.jpg", "md5-a")
    queue.mark_uploading("/photos/a.jpg")
    queue.mark_done("/photos/a.jpg")
    queue.close()

    # Agent restarts; catch-up scan finds /photos/a.jpg still sitting in
    # the folder and computes its MD5 again before deciding what to do.
    reopened = UploadQueue(db_path)
    assert reopened.is_already_done("md5-a") is True
    # The real watcher would call mark_done_without_uploading() here
    # instead of enqueue() -- confirm that path leaves it done, not reset.
    reopened.mark_done_without_uploading("/photos/a.jpg", "md5-a")
    assert reopened.counts() == {"pending": 0, "uploading": 0, "done": 1, "failed": 0}
