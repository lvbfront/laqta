from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "Laqta Agent"

# Baked in so the photographer never types a URL -- an env var override
# exists purely for development/testing (this repo has no fixed
# production domain yet); a real release build should hardcode the
# production URL as the default below instead of relying on the env var
# being set on every machine it's installed on.
API_BASE_URL = os.environ.get("LAQTA_API_URL", "http://localhost:8000")

KEYCHAIN_SERVICE = "laqta-agent"
KEYCHAIN_TOKEN_KEY = "agent_token"
KEYCHAIN_EVENT_ID_KEY = "agent_event_id"
KEYCHAIN_WATCH_FOLDER_KEY = "watch_folder"

# File-stability check (CLAUDE.md-equivalent hard rule for this agent:
# never upload a file that's still being written). Two checks this far
# apart, size+mtime both unchanged, before a file is considered done.
STABILITY_CHECK_INTERVAL_SECONDS = 1.0

# Extensions uploaded by default -- RAW is deliberately excluded (large,
# slow, and a guest-facing gallery only ever needs the JPEG anyway).
# Configurable per docs -- see Settings.include_raw.
DEFAULT_UPLOAD_EXTENSIONS = {".jpg", ".jpeg"}
RAW_EXTENSIONS = {".cr2", ".cr3", ".nef", ".nrw", ".arw", ".raf", ".dng", ".orf", ".rw2", ".pef", ".srw"}

# Never treated as a photo, regardless of extension filters above.
IGNORED_FILENAMES = {".ds_store", "thumbs.db", "desktop.ini"}
IGNORED_SUFFIXES = {".tmp", ".xmp", ".part", ".crdownload"}

RETRY_BASE_DELAY_SECONDS = 2.0
RETRY_MAX_DELAY_SECONDS = 300.0

UPLOAD_HTTP_TIMEOUT_SECONDS = 60
PAIR_HTTP_TIMEOUT_SECONDS = 15


def data_dir() -> Path:
    """Per-OS user-data directory for the SQLite queue and any local
    settings -- never inside the watched photo folder itself, and
    survives the agent being moved/reinstalled since it's OS-standard,
    not relative to the app bundle.
    """
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / APP_NAME
    elif sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home())) / APP_NAME
    else:
        base = Path.home() / f".{APP_NAME.lower().replace(' ', '-')}"
    base.mkdir(parents=True, exist_ok=True)
    return base


def queue_db_path() -> Path:
    return data_dir() / "queue.sqlite3"
