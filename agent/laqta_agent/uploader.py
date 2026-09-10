from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path

from laqta_agent.api_client import ApiClient, AuthError, NetworkError, ServerError
from laqta_agent.queue_db import UploadQueue, UploadRecord


class Uploader:
    """Drains UploadQueue.next_ready() one file at a time in a background
    thread. Deliberately one-at-a-time, not a thread pool -- the queue
    already gives us "survives a restart or an outage", and there's no
    latency win to serial vs. parallel for a booth uploading a few
    photos a minute; parallel would only add complexity (interleaved
    retry/backoff bookkeeping) for no real benefit here.
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
        self.online = True
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._stop.clear()
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
                self._stop.wait(1.0)
                continue
            self._upload_one(record)

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
