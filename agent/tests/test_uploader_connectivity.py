"""The GUI's offline banner (gui.py) is driven entirely by Uploader.online
-- these tests exercise the real background thread (not just the pure
logic) to prove that flag actually gets set correctly, both reactively
(a real upload attempt fails) and proactively (the queue is empty, so
there's nothing to trigger a reactive check -- this is exactly the
camera-Wi-Fi-access-point-mode failure: the laptop never gets a chance
to attempt an upload that would tell it it's offline, because nothing
before it noticed there's no internet route at all).
"""

from __future__ import annotations

import time

import laqta_agent.uploader as uploader_module
from laqta_agent.api_client import NetworkError, UploadOutcome
from laqta_agent.queue_db import UploadQueue
from laqta_agent.uploader import Uploader


class FakeApiClient:
    def __init__(self, connectivity: bool = True, upload_error: Exception | None = None) -> None:
        self.connectivity = connectivity
        self.upload_error = upload_error
        self.check_calls = 0
        self.upload_calls = 0

    def check_connectivity(self) -> bool:
        self.check_calls += 1
        return self.connectivity

    def upload_photo(self, token: str, path) -> UploadOutcome:  # noqa: ANN001
        self.upload_calls += 1
        if self.upload_error:
            raise self.upload_error
        return UploadOutcome(status="queued", photo_id="p1", error=None)


def _wait_until(predicate, timeout: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def test_empty_queue_proactively_detects_no_internet(tmp_path, monkeypatch):
    monkeypatch.setattr(uploader_module, "HEALTH_CHECK_INTERVAL_SECONDS", 0.05)

    queue = UploadQueue(tmp_path / "q.sqlite3")
    api_client = FakeApiClient(connectivity=False)
    uploader = Uploader(queue, api_client, get_token=lambda: "tok")

    assert uploader.online is True  # optimistic default before the first check runs
    uploader.start()
    try:
        assert _wait_until(lambda: uploader.online is False), "never detected offline with an empty queue"
        assert api_client.check_calls >= 1
        assert api_client.upload_calls == 0  # nothing was ever queued to upload
    finally:
        uploader.stop()
        queue.close()


def test_empty_queue_proactively_confirms_internet_is_fine(tmp_path, monkeypatch):
    monkeypatch.setattr(uploader_module, "HEALTH_CHECK_INTERVAL_SECONDS", 0.05)

    queue = UploadQueue(tmp_path / "q.sqlite3")
    api_client = FakeApiClient(connectivity=True)
    uploader = Uploader(queue, api_client, get_token=lambda: "tok")
    uploader.start()
    try:
        assert _wait_until(lambda: api_client.check_calls >= 1)
        assert uploader.online is True
    finally:
        uploader.stop()
        queue.close()


def test_connectivity_recovers_once_the_network_comes_back(tmp_path, monkeypatch):
    monkeypatch.setattr(uploader_module, "HEALTH_CHECK_INTERVAL_SECONDS", 0.05)

    queue = UploadQueue(tmp_path / "q.sqlite3")
    api_client = FakeApiClient(connectivity=False)
    uploader = Uploader(queue, api_client, get_token=lambda: "tok")
    uploader.start()
    try:
        assert _wait_until(lambda: uploader.online is False)
        api_client.connectivity = True
        assert _wait_until(lambda: uploader.online is True)
    finally:
        uploader.stop()
        queue.close()


def test_a_real_upload_failure_still_flips_online_reactively(tmp_path):
    """Regression coverage for the pre-existing reactive path -- a real
    upload attempt failing is itself a connectivity signal and must keep
    working exactly as before the proactive check was added.
    """
    queue = UploadQueue(tmp_path / "q.sqlite3")
    queue.enqueue(str(tmp_path / "photo.jpg"), "md5-a")
    (tmp_path / "photo.jpg").write_bytes(b"fake-jpeg")

    api_client = FakeApiClient(connectivity=True, upload_error=NetworkError("connection refused"))
    uploader = Uploader(queue, api_client, get_token=lambda: "tok")
    uploader.start()
    try:
        assert _wait_until(lambda: api_client.upload_calls >= 1)
        assert _wait_until(lambda: uploader.online is False)
    finally:
        uploader.stop()
        queue.close()
