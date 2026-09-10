from __future__ import annotations

import threading
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from laqta_agent.config import (
    DEFAULT_UPLOAD_EXTENSIONS,
    IGNORED_FILENAMES,
    IGNORED_SUFFIXES,
    RAW_EXTENSIONS,
    STABILITY_CHECK_INTERVAL_SECONDS,
)
from laqta_agent.hashing import compute_md5
from laqta_agent.queue_db import UploadQueue
from laqta_agent.stability import StabilityTracker


def is_candidate_file(path: Path, *, include_raw: bool) -> bool:
    name = path.name
    if name.lower() in IGNORED_FILENAMES:
        return False
    if name.startswith("."):
        return False  # hidden files -- also catches macOS AppleDouble ._foo.jpg siblings
    if path.suffix.lower() in IGNORED_SUFFIXES:
        return False
    allowed = DEFAULT_UPLOAD_EXTENSIONS | (RAW_EXTENSIONS if include_raw else set())
    return path.suffix.lower() in allowed


class _Handler(FileSystemEventHandler):
    def __init__(self, watcher: "FolderWatcher") -> None:
        self._watcher = watcher

    def on_created(self, event) -> None:  # noqa: ANN001 -- watchdog's own event type
        if not event.is_directory:
            self._watcher.observe_path(Path(event.src_path))

    def on_modified(self, event) -> None:  # noqa: ANN001
        if not event.is_directory:
            self._watcher.observe_path(Path(event.src_path))

    def on_moved(self, event) -> None:  # noqa: ANN001
        if not event.is_directory:
            self._watcher.observe_path(Path(event.dest_path))


class FolderWatcher:
    """Recursively watches `folder` for new/changed candidate files,
    waits for each to pass the file-stability check
    (laqta_agent.stability), then hands it to the queue. Two separate
    concerns kept apart on purpose: watchdog tells us a path exists and
    might be changing *right now*; the stability tracker decides when
    it's actually safe to touch.
    """

    def __init__(self, folder: Path, queue: UploadQueue, include_raw: bool = False) -> None:
        self.folder = folder
        self.queue = queue
        self.include_raw = include_raw
        self.tracker = StabilityTracker()
        self._observer = Observer()
        self._poll_stop = threading.Event()
        self._poll_thread: threading.Thread | None = None

    def start(self) -> None:
        self._observer.schedule(_Handler(self), str(self.folder), recursive=True)
        self._observer.start()
        self._poll_stop.clear()
        self._poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._poll_thread.start()
        # Startup catch-up -- also the "end of event, make sure nothing
        # was missed" recovery path when triggered again from the GUI.
        self.catch_up_scan()

    def stop(self) -> None:
        self._poll_stop.set()
        self._observer.stop()
        self._observer.join(timeout=5)
        if self._poll_thread:
            self._poll_thread.join(timeout=5)

    def observe_path(self, path: Path) -> None:
        if is_candidate_file(path, include_raw=self.include_raw):
            self.tracker.track(path)

    def catch_up_scan(self) -> int:
        """Walks the folder right now and starts tracking every candidate
        file the queue doesn't already know about. Returns how many were
        newly picked up. Safe to call repeatedly -- already-known paths
        (any status, including 'done') are skipped.
        """
        known = self.queue.all_paths()
        found = 0
        for path in self.folder.rglob("*"):
            if not path.is_file():
                continue
            if str(path) in known:
                continue
            if is_candidate_file(path, include_raw=self.include_raw):
                self.tracker.track(path)
                found += 1
        return found

    def _poll_loop(self) -> None:
        while not self._poll_stop.is_set():
            for path in self.tracker.poll():
                self._on_stable(path)
            self._poll_stop.wait(STABILITY_CHECK_INTERVAL_SECONDS)

    def _on_stable(self, path: Path) -> None:
        md5 = compute_md5(path)
        if md5 is None:
            return
        if self.queue.is_already_done(md5):
            self.queue.mark_done_without_uploading(str(path), md5)
            return
        self.queue.enqueue(str(path), md5)
