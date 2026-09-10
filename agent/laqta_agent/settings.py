from __future__ import annotations

import json
from dataclasses import asdict, dataclass

from laqta_agent.config import data_dir
from laqta_agent.i18n import DEFAULT_LOCALE


@dataclass
class Settings:
    """Non-secret local preferences -- the watched folder, locale,
    whether RAW is included. Deliberately separate from laqta_agent.
    keychain: the token is a credential and belongs in the OS keychain,
    this is just UI state and belongs in a plain file.
    """

    folder: str | None = None
    locale: str = DEFAULT_LOCALE
    include_raw: bool = False


def _settings_path():
    return data_dir() / "settings.json"


def load_settings() -> Settings:
    path = _settings_path()
    if not path.exists():
        return Settings()
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return Settings()
    return Settings(
        folder=data.get("folder"),
        locale=data.get("locale", DEFAULT_LOCALE),
        include_raw=data.get("include_raw", False),
    )


def save_settings(settings: Settings) -> None:
    _settings_path().write_text(json.dumps(asdict(settings), ensure_ascii=False, indent=2))
