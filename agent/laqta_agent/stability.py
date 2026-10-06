from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class FileSnapshot:
    size: int
    mtime: float


def snapshot(path: Path) -> FileSnapshot | None:
    """None means "can't be read right now" -- mid-write on some
    filesystems, or it's been deleted/moved since the caller last looked.
    Either way: not stable, and definitely not safe to upload.
    """
    try:
        st = path.stat()
    except OSError:
        return None
    return FileSnapshot(size=st.st_size, mtime=st.st_mtime)


def looks_complete(path: Path) -> bool:
    """A file that starts like a JPEG (SOI, FF D8) only counts as complete
    once it also ends like one (EOI, FF D9, ignoring zero padding). Size+
    mtime alone isn't enough: a Wi-Fi transfer that stalls for longer
    than one stability window looks "unchanged" halfway through, and the
    half file would be uploaded (tests/test_watcher_scenarios.py).
    An empty file is never complete: transfer software can create the
    file first and fill it in later. Anything else (RAW, non-JPEG)
    passes -- size+mtime still applies.
    """
    # ponytail: a JPEG with no EOI at all is never uploaded; add a long
    # unchanged-for-N-seconds escape hatch if a real camera produces one.
    try:
        with open(path, "rb") as f:
            head = f.read(2)
            if head != b"\xff\xd8":
                return head != b""
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 4096))
            return f.read().rstrip(b"\x00").endswith(b"\xff\xd9")
    except OSError:
        return False


class StabilityTracker:
    """The number one source of corrupt partial uploads in watch-folder
    tools is uploading a file mid-write -- a camera/tethering app can
    take a full second or more to finish writing a large JPEG, and a
    filesystem "created" event fires the moment the file is *opened*, not
    when writing finishes. This tracks candidate paths and only reports a
    path as stable once its size and mtime are identical across two
    separate observe() calls -- the caller is responsible for spacing
    those calls roughly STABILITY_CHECK_INTERVAL_SECONDS apart (this
    class holds no timers itself, which is what makes it trivial to unit
    test without real sleeps).

    Thread-safe: the watchdog callback thread and the polling loop thread
    both touch this.
    """

    def __init__(self) -> None:
        self._last_seen: dict[Path, FileSnapshot] = {}
        self._lock = threading.Lock()

    def track(self, path: Path) -> None:
        """Start (or continue) watching this path -- safe to call
        repeatedly for the same path (e.g. once per filesystem event).
        """
        with self._lock:
            self._last_seen.setdefault(path, None)  # type: ignore[arg-type]

    def forget(self, path: Path) -> None:
        with self._lock:
            self._last_seen.pop(path, None)

    def poll(self) -> list[Path]:
        """Call roughly once per STABILITY_CHECK_INTERVAL_SECONDS.
        Returns every tracked path that has just become stable (and stops
        tracking it -- the caller owns what happens next: MD5 + enqueue).
        A path whose file has disappeared is silently dropped, not
        reported stable.
        """
        newly_stable: list[Path] = []
        with self._lock:
            for path in list(self._last_seen.keys()):
                current = snapshot(path)
                if current is None:
                    del self._last_seen[path]
                    continue
                previous = self._last_seen[path]
                if previous is not None and previous == current and looks_complete(path):
                    newly_stable.append(path)
                    del self._last_seen[path]
                else:
                    self._last_seen[path] = current
        return newly_stable

    def tracked_count(self) -> int:
        with self._lock:
            return len(self._last_seen)
