from __future__ import annotations

import mimetypes
from dataclasses import dataclass
from pathlib import Path

import requests

from laqta_agent.config import (
    API_BASE_URL,
    HEALTH_CHECK_TIMEOUT_SECONDS,
    PAIR_HTTP_TIMEOUT_SECONDS,
    UPLOAD_HTTP_TIMEOUT_SECONDS,
)


class PairingError(Exception):
    """Code was invalid, expired, or already used -- not a network
    problem, so the caller should show the pairing screen again rather
    than retry silently.
    """


class AuthError(Exception):
    """The stored token was rejected (revoked, or the event doesn't
    exist any more) -- the caller should clear the keychain and show the
    pairing screen again, not just retry the upload.
    """


class NetworkError(Exception):
    """No connection, DNS failure, timeout -- retryable, and what the
    status window's "offline" state is based on.
    """


class ServerError(Exception):
    """A 5xx from the API -- retryable, distinct from AuthError/a 4xx
    that retrying won't fix.
    """


@dataclass(frozen=True)
class UploadOutcome:
    status: str  # "queued" | "duplicate" | "error"
    photo_id: str | None
    error: str | None


class ApiClient:
    def __init__(self, base_url: str = API_BASE_URL) -> None:
        self.base_url = base_url.rstrip("/")

    def pair(self, code: str, device_label: str) -> tuple[str, str]:
        """Returns (token, event_id). Raises PairingError for a rejected
        code, NetworkError/ServerError for anything else that went wrong
        on the way.
        """
        try:
            resp = requests.post(
                f"{self.base_url}/api/agent/pair",
                json={"code": code, "device_label": device_label},
                timeout=PAIR_HTTP_TIMEOUT_SECONDS,
            )
        except requests.exceptions.RequestException as exc:
            raise NetworkError(str(exc)) from exc

        if resp.status_code == 401:
            raise PairingError("invalid or expired code")
        if resp.status_code >= 500:
            raise ServerError(f"server error {resp.status_code}")
        if not resp.ok:
            raise PairingError(f"unexpected response {resp.status_code}")

        body = resp.json()
        return body["token"], body["event_id"]

    def check_connectivity(self) -> bool:
        """Hits the API's plain /health endpoint -- deliberately not an
        authenticated call, since the point is to answer "does this
        machine have a working route to the internet at all", not
        anything about the stored token. Used by Uploader to detect the
        no-internet case (the camera's own Wi-Fi access-point mode is the
        single most common cause -- the laptop joins the camera's
        isolated network and loses its real internet route entirely)
        *proactively*, not only after a real upload attempt happens to
        fail -- with an empty queue there may be no upload attempt for a
        long time, and the wrong state would otherwise sit on screen
        silently. Returns False for literally any failure -- DNS, refused,
        timeout, a non-2xx status -- the caller only needs yes/no.
        """
        try:
            resp = requests.get(f"{self.base_url}/health", timeout=HEALTH_CHECK_TIMEOUT_SECONDS)
        except requests.exceptions.RequestException:
            return False
        return resp.ok

    def upload_photo(self, token: str, path: Path) -> UploadOutcome:
        content_type = mimetypes.guess_type(path.name)[0] or "image/jpeg"
        try:
            with open(path, "rb") as f:
                resp = requests.post(
                    f"{self.base_url}/api/agent/photos",
                    headers={"Authorization": f"Bearer {token}"},
                    files={"file": (path.name, f, content_type)},
                    timeout=UPLOAD_HTTP_TIMEOUT_SECONDS,
                )
        except requests.exceptions.RequestException as exc:
            raise NetworkError(str(exc)) from exc

        if resp.status_code == 401:
            raise AuthError("agent token rejected")
        if resp.status_code >= 500:
            raise ServerError(f"server error {resp.status_code}")
        if not resp.ok:
            raise ServerError(f"unexpected response {resp.status_code}: {resp.text[:200]}")

        body = resp.json()
        return UploadOutcome(status=body["status"], photo_id=body.get("photo_id"), error=body.get("error"))
