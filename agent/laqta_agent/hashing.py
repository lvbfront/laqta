from __future__ import annotations

import hashlib
from pathlib import Path


def compute_md5(path: Path) -> str | None:
    """None means the file vanished between being confirmed stable and
    being hashed (deleted, moved) -- treated as "nothing to upload", not
    an error.
    """
    try:
        digest = hashlib.md5()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None
