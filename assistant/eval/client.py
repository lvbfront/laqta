"""The Anthropic client for eval runs and scoring.

The SDK reads ANTHROPIC_API_KEY from the process environment only; it does
not read assistant/.env. That file is loaded explicitly here, and an
exported key is used only when the file has none.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"

# The SDK retries 408/409/429/5xx and connection errors itself. A run is
# hundreds of calls, so give it more patience than the default 2.
API_MAX_RETRIES = 6


def anthropic_client() -> Any:
    import anthropic
    from dotenv import dotenv_values

    key = dotenv_values(ENV_FILE).get("ANTHROPIC_API_KEY") if ENV_FILE.exists() else None
    key = key or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise SystemExit(f"no ANTHROPIC_API_KEY in {ENV_FILE} or the environment")
    return anthropic.Anthropic(api_key=key, max_retries=API_MAX_RETRIES)
