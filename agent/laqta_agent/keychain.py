from __future__ import annotations

import keyring
import keyring.errors

from laqta_agent.config import KEYCHAIN_EVENT_ID_KEY, KEYCHAIN_SERVICE, KEYCHAIN_TOKEN_KEY


def save_token(token: str, event_id: str) -> None:
    keyring.set_password(KEYCHAIN_SERVICE, KEYCHAIN_TOKEN_KEY, token)
    keyring.set_password(KEYCHAIN_SERVICE, KEYCHAIN_EVENT_ID_KEY, event_id)


def load_token() -> tuple[str, str] | None:
    try:
        token = keyring.get_password(KEYCHAIN_SERVICE, KEYCHAIN_TOKEN_KEY)
        event_id = keyring.get_password(KEYCHAIN_SERVICE, KEYCHAIN_EVENT_ID_KEY)
    except keyring.errors.KeyringError:
        # No keychain backend available (rare -- a stripped-down Linux
        # box with no secret service running) -- treated the same as "no
        # token yet" rather than crashing the app at startup.
        return None
    if token and event_id:
        return token, event_id
    return None


def clear_token() -> None:
    for key in (KEYCHAIN_TOKEN_KEY, KEYCHAIN_EVENT_ID_KEY):
        try:
            keyring.delete_password(KEYCHAIN_SERVICE, key)
        except keyring.errors.PasswordDeleteError:
            pass  # already absent
