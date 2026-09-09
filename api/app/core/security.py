from __future__ import annotations

import bcrypt

# bcrypt truncates/errors past 72 bytes of input -- long enough for any
# real password, but worth bounding explicitly rather than letting a
# pathological input hit that limit inside hashpw/checkpw.
_MAX_PASSWORD_BYTES = 72


def hash_password(password: str) -> str:
    encoded = password.encode("utf-8")[:_MAX_PASSWORD_BYTES]
    return bcrypt.hashpw(encoded, bcrypt.gensalt()).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    encoded = password.encode("utf-8")[:_MAX_PASSWORD_BYTES]
    try:
        return bcrypt.checkpw(encoded, password_hash.encode("ascii"))
    except ValueError:
        # malformed/foreign hash format -- never a match, not a crash
        return False
