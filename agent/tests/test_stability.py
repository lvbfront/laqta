from __future__ import annotations

import os
import time

from laqta_agent.stability import StabilityTracker, snapshot


def test_snapshot_returns_none_for_missing_file(tmp_path):
    assert snapshot(tmp_path / "nope.jpg") is None


def test_unchanged_file_becomes_stable_after_two_polls(tmp_path):
    f = tmp_path / "a.jpg"
    f.write_bytes(b"hello")

    tracker = StabilityTracker()
    tracker.track(f)

    first = tracker.poll()
    assert first == []  # only one observation so far -- nothing to compare against yet

    second = tracker.poll()
    assert second == [f]  # size+mtime identical to the first observation


def test_growing_file_is_not_reported_stable_until_writes_stop(tmp_path):
    f = tmp_path / "a.jpg"
    f.write_bytes(b"a")

    tracker = StabilityTracker()
    tracker.track(f)
    assert tracker.poll() == []  # baseline

    # Still "being written" -- size changes between polls.
    f.write_bytes(b"aa")
    assert tracker.poll() == []  # changed since baseline, new baseline recorded

    f.write_bytes(b"aaa")
    assert tracker.poll() == []  # changed again

    # Writing has stopped -- two consecutive identical observations now.
    assert tracker.poll() == [f]


def test_disappearing_file_is_dropped_not_reported_stable(tmp_path):
    f = tmp_path / "a.jpg"
    f.write_bytes(b"hello")

    tracker = StabilityTracker()
    tracker.track(f)
    tracker.poll()  # baseline recorded

    f.unlink()
    assert tracker.poll() == []
    # and it's no longer tracked -- recreating it starts a fresh baseline,
    # not treated as "already seen once"
    assert tracker.tracked_count() == 0


def test_mtime_only_change_with_same_size_is_still_detected(tmp_path):
    """A file can be rewritten with identical content length but a new
    mtime (e.g. metadata touch mid-transfer) -- must not be mistaken for
    "unchanged".
    """
    f = tmp_path / "a.jpg"
    f.write_bytes(b"hello")

    tracker = StabilityTracker()
    tracker.track(f)
    tracker.poll()

    # Force a different mtime without changing size.
    future = time.time() + 5
    os.utime(f, (future, future))

    assert tracker.poll() == []  # mtime changed -- not stable yet
    assert tracker.poll() == [f]  # unchanged since the last poll now


def test_track_is_idempotent_for_an_already_tracked_path(tmp_path):
    f = tmp_path / "a.jpg"
    f.write_bytes(b"hello")

    tracker = StabilityTracker()
    tracker.track(f)
    tracker.poll()  # baseline

    tracker.track(f)  # re-tracking mid-flight must not reset the baseline
    assert tracker.poll() == [f]


def test_forget_stops_tracking_a_path(tmp_path):
    f = tmp_path / "a.jpg"
    f.write_bytes(b"hello")

    tracker = StabilityTracker()
    tracker.track(f)
    tracker.poll()
    tracker.forget(f)

    assert tracker.poll() == []
    assert tracker.tracked_count() == 0


def test_multiple_files_tracked_independently(tmp_path):
    a = tmp_path / "a.jpg"
    b = tmp_path / "b.jpg"
    a.write_bytes(b"a")
    b.write_bytes(b"b")

    tracker = StabilityTracker()
    tracker.track(a)
    tracker.track(b)
    tracker.poll()  # baseline for both

    b.write_bytes(b"bb")  # b is still changing
    result = tracker.poll()
    assert result == [a]  # only a is stable
