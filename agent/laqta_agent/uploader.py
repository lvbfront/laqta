from __future__ import annotations

import threading
import time
from collections.abc import Callable
from pathlib import Path

from laqta_agent.api_client import ApiClient, AuthError, NetworkError, ServerError
from laqta_agent.config import HEALTH_CHECK_INTERVAL_SECONDS
from laqta_agent.queue_db import UploadQueue, UploadRecord


class Uploader:
    """Drains UploadQueue.next_ready() one file at a time in a background
    thread. Deliberately one-at-a-time, not a thread pool -- the queue
    already gives us "survives a restart or an outage", and there's no
    latency win to serial vs. parallel for a booth uploading a few
    photos a minute; parallel would only add complexity (interleaved
    retry/backoff bookkeeping) for no real benefit here.

    self.online drives the GUI's offline banner (gui.py) and is kept
    accurate two ways: reactively, as a side effect of every real upload
    attempt (_upload_one), and proactively, via a periodic health check
    while the queue is idle (_maybe_check_connectivity) -- the second one
    matters because the most common real failure (a photographer
    accidentally joins the camera's own Wi-Fi access point instead of a
    shared hotspot, so the laptop has no internet route at all) can
    happen with an empty queue, before any upload has ever been
    attempted to reactively discover it.
    """

    def __init__(
        self,
        queue: UploadQueue,
        api_client: ApiClient,
        get_token: Callable[[], str | None],
        on_auth_error: Callable[[], None] | None = None,
    ) -> None:
        self.queue = queue
        self.api_client = api_client
        self.get_token = get_token
        self.on_auth_error = on_auth_error
        # True is the optimistic starting guess, corrected within about a
        # second of start() by the first idle-loop connectivity check
        # below -- not left to sit wrong until either a real upload is
        # attempted or HEALTH_CHECK_INTERVAL_SECONDS has fully elapsed.
        self.online = True
        self._last_connectivity_check = 0.0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._stop.clear()
        self._last_connectivity_check = 0.0
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _loop(self) -> None:
        while not self._stop.is_set():
            record = self.queue.next_ready()
            if record is None:
                self._maybe_check_connectivity()
                self._stop.wait(1.0)
                continue
            self._upload_one(record)

    def _maybe_check_connectivity(self) -> None:
        """Runs only when the queue is idle -- a real upload attempt
        (_upload_one below) is itself a perfectly good connectivity
        signal and doesn't need a redundant check layered on top; this
        exists specifically for the empty-queue case a reactive-only
        check can't cover (see the class docstring's AP-mode example).
        """
        now = time.monotonic()
        if now - self._last_connectivity_check < HEALTH_CHECK_INTERVAL_SECONDS:
            return
        self._last_connectivity_check = now
        self.online = self.api_client.check_connectivity()

    def _upload_one(self, record: UploadRecord) -> None:
        token = self.get_token()
        if token is None:
            self._stop.wait(2.0)
            return

        path = Path(record.path)
        if not path.exists():
            # Deleted/moved after being queued -- nothing to retry.
            self.queue.mark_failed(record.path, "file no longer exists")
            return

        self.queue.mark_uploading(record.path)
        try:
            outcome = self.api_client.upload_photo(token, path)
        except NetworkError as exc:
            self.online = False
            self.queue.mark_failed(record.path, str(exc))
            return
        except AuthError:
            self.online = True
            self.queue.mark_failed(record.path, "authentication failed -- this device may need to be re-paired")
            if self.on_auth_error:
                self.on_auth_error()
            return
        except ServerError as exc:
            self.online = True
            self.queue.mark_failed(record.path, str(exc))
            return

        self.online = True
        if outcome.status in ("queued", "duplicate"):
            self.queue.mark_done(record.path)
        else:
            self.queue.mark_failed(record.path, outcome.error or "upload rejected")
