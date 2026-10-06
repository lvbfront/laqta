"""Camera-day folder scenarios, end to end through the real FolderWatcher
(real watchdog/FSEvents on a real directory), the real SQLite queue and
the real Uploader thread. Only the HTTP side is faked, by a stand-in that
dedupes on MD5 per event exactly like app.services.ingest.ingest_photo,
so "stored once" here means what it means on the real server.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import threading
import time

from laqta_agent.api_client import UploadOutcome
from laqta_agent.queue_db import UploadQueue
from laqta_agent.uploader import Uploader
from laqta_agent.watcher import FolderWatcher


class _Crash(BaseException):
    """Escapes Uploader's except clauses, killing its thread mid-upload --
    the closest in-process stand-in for the agent being killed after the
    server got the file but before the queue recorded it.
    """


class FakeServer:
    def __init__(self, delay: float = 0.0, crash_on_call: int | None = None) -> None:
        self.delay = delay
        self.crash_on_call = crash_on_call
        self.posts: list[bytes] = []
        self.stored: dict[str, bytes] = {}
        self._lock = threading.Lock()

    def check_connectivity(self) -> bool:
        return True

    def upload_photo(self, token: str, path) -> UploadOutcome:  # noqa: ANN001
        body = path.read_bytes()
        time.sleep(self.delay)
        md5 = hashlib.md5(body).hexdigest()
        with self._lock:
            self.posts.append(body)
            duplicate = md5 in self.stored
            self.stored.setdefault(md5, body)
            if self.crash_on_call is not None and len(self.posts) == self.crash_on_call:
                raise _Crash()
        return UploadOutcome(status="duplicate" if duplicate else "queued", photo_id=None, error=None)


class Agent:
    def __init__(self, folder, db_path, server: FakeServer) -> None:  # noqa: ANN001
        self.queue = UploadQueue(db_path)
        self.watcher = FolderWatcher(folder, self.queue)
        self.uploader = Uploader(self.queue, server, lambda: "token")
        self.watcher.start()
        self.uploader.start()

    def stop(self) -> None:
        self.watcher.stop()
        self.uploader.stop()
        self.queue.close()


def jpeg(seed: int, size: int = 200_000) -> bytes:
    body = hashlib.sha256(str(seed).encode()).digest() * (size // 32)
    return b"\xff\xd8\xff\xe0" + body + b"\xff\xd9"


def wait_until(predicate, timeout: float = 15.0) -> bool:  # noqa: ANN001
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.1)
    return predicate()


def settle(seconds: float = 3.0) -> None:
    """Long enough for any late stability/upload cycle to show up."""
    time.sleep(seconds)


def test_file_written_slowly_is_uploaded_once_and_complete(tmp_path):
    folder = tmp_path / "inbox"
    folder.mkdir()
    server = FakeServer()
    agent = Agent(folder, tmp_path / "q.sqlite3", server)
    try:
        data = jpeg(1, size=600_000)
        third = len(data) // 3
        with open(folder / "DSC00001.JPG", "wb") as f:
            for i in range(3):
                f.write(data[i * third : (i + 1) * third] if i < 2 else data[2 * third :])
                f.flush()
                os.fsync(f.fileno())
                if i < 2:
                    time.sleep(2.5)  # a stalled Wi-Fi transfer, longer than one stability window
        assert wait_until(lambda: len(server.stored) >= 1)
        settle()
        assert [len(b) for b in server.posts] == [len(data)]
        assert list(server.stored.values()) == [data]
    finally:
        agent.stop()


def test_empty_placeholder_file_is_not_uploaded(tmp_path):
    """Transfer software that creates the file first and fills it in
    later -- the 0-byte file mustn't look "finished" in the meantime.
    """
    folder = tmp_path / "inbox"
    folder.mkdir()
    server = FakeServer()
    agent = Agent(folder, tmp_path / "q.sqlite3", server)
    try:
        target = folder / "DSC00006.JPG"
        target.touch()
        time.sleep(5)  # stability window + uploader pickup, so an empty file would really go out
        target.write_bytes(jpeg(6))
        assert wait_until(lambda: len(server.stored) >= 1)
        settle()
        assert server.posts == [jpeg(6)]
    finally:
        agent.stop()


def test_files_in_new_subfolders_are_uploaded(tmp_path):
    folder = tmp_path / "inbox"
    folder.mkdir()
    server = FakeServer()
    agent = Agent(folder, tmp_path / "q.sqlite3", server)
    try:
        nested = folder / "2026-10-06" / "100MSDCF"
        nested.mkdir(parents=True)
        (nested / "DSC00002.JPG").write_bytes(jpeg(2))
        assert wait_until(lambda: len(server.stored) == 1)
    finally:
        agent.stop()


def test_raw_half_of_a_raw_plus_jpeg_pair_is_skipped(tmp_path):
    folder = tmp_path / "inbox"
    folder.mkdir()
    server = FakeServer()
    agent = Agent(folder, tmp_path / "q.sqlite3", server)
    try:
        (folder / "DSC00003.ARW").write_bytes(b"raw-bytes" * 10_000)
        (folder / "DSC00003.JPG").write_bytes(jpeg(3))
        assert wait_until(lambda: len(server.stored) == 1)
        settle()
        assert list(server.stored.values()) == [jpeg(3)]
    finally:
        agent.stop()


def test_same_file_again_or_renamed_is_stored_once(tmp_path):
    folder = tmp_path / "inbox"
    folder.mkdir()
    server = FakeServer()
    agent = Agent(folder, tmp_path / "q.sqlite3", server)
    try:
        (folder / "DSC00004.JPG").write_bytes(jpeg(4))
        assert wait_until(lambda: len(server.posts) == 1)
        shutil.copy(folder / "DSC00004.JPG", folder / "DSC00004 copy.JPG")
        (folder / "DSC00004.JPG").rename(folder / "renamed.JPG")
        # Two copies landing at the same moment, before either is done.
        (folder / "twin-a.JPG").write_bytes(jpeg(5))
        (folder / "twin-b.JPG").write_bytes(jpeg(5))
        assert wait_until(lambda: len(server.stored) == 2)
        settle()
        assert len(server.stored) == 2
        # Only the simultaneous twins may cost a second POST (answered "duplicate").
        assert len(server.posts) <= 3
    finally:
        agent.stop()


def test_burst_of_50_files_is_all_uploaded_once(tmp_path):
    folder = tmp_path / "inbox"
    folder.mkdir()
    server = FakeServer()
    agent = Agent(folder, tmp_path / "q.sqlite3", server)
    try:
        for i in range(50):
            (folder / f"DSC1{i:04d}.JPG").write_bytes(jpeg(100 + i))
        assert wait_until(lambda: len(server.stored) == 50, timeout=60)
        settle()
        assert len(server.posts) == 50
    finally:
        agent.stop()


def test_restart_mid_batch_loses_and_doubles_nothing(tmp_path):
    folder = tmp_path / "inbox"
    folder.mkdir()
    db_path = tmp_path / "q.sqlite3"
    expected = {hashlib.md5(jpeg(200 + i)).hexdigest() for i in range(20)}

    server = FakeServer(delay=0.05, crash_on_call=5)
    agent = Agent(folder, db_path, server)
    for i in range(20):
        (folder / f"DSC2{i:04d}.JPG").write_bytes(jpeg(200 + i))
    assert wait_until(lambda: len(server.posts) == 5)
    time.sleep(0.5)
    agent.stop()  # uploader thread is already dead; files may still be pending or untracked

    server.crash_on_call = None
    agent = Agent(folder, db_path, server)
    try:
        assert wait_until(lambda: set(server.stored) == expected, timeout=60)
        assert wait_until(lambda: agent.queue.counts()["done"] == 20)
        settle()
        assert agent.queue.counts() == {"pending": 0, "uploading": 0, "done": 20, "failed": 0}
    finally:
        agent.stop()
