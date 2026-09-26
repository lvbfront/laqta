"""Server settings and the guard on which database it may touch.

Same `ASSISTANT_` prefix as app.config, for the same reason: a shell already
configured for Laqta must not be able to point this at Laqta's database. The
app's own Settings ignores extra environment variables, so these live beside
it without either having to know about the other.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

from app.config import ASSISTANT_DIR

# Dropped and re-migrated by the test run; truncated and re-seeded between
# eval episodes. Either would destroy a conversation mid-sentence, and the
# damage is done before anyone notices the wrong URL was set.
REFUSED_DATABASES = frozenset({"assistant_test", "assistant_eval"})


class WrongDatabase(RuntimeError):
    pass


class ServerSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ASSISTANT_", env_file=ASSISTANT_DIR / ".env", extra="ignore"
    )

    # ASSISTANT_DEV=1. Off, the client cannot choose an identity, cannot set
    # the clock, and gets no events back. There is no half-on.
    dev: bool = False

    # The Laqta site will be another origin later; the widget's dev server
    # already is. Comma-separated, never "*".
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173"

    max_message_chars: int = 2000
    max_sessions: int = 100
    session_idle_seconds: int = 1800

    # Loading BGE-M3 takes seconds and 2GB, and the first search_kb of the
    # process pays it while a customer watches a typing indicator.
    warm_kb: bool = False

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache(maxsize=1)
def get_server_settings() -> ServerSettings:
    return ServerSettings()


def require_a_usable_database(target: object) -> str:
    """`target` is a URL string, a SQLAlchemy URL, an Engine or a Session.

    A denylist, not an allowlist: someone running two assistants side by side
    has a legitimate reason to name a third database, and refusing everything
    unfamiliar would only teach them to edit this file. The two names here
    are the ones that get destroyed on a schedule.
    """
    if hasattr(target, "get_bind"):
        target = target.get_bind()
    if hasattr(target, "engine"):
        target = target.engine
    if hasattr(target, "url"):
        target = target.url
    url = make_url(target)
    if url.database in REFUSED_DATABASES:
        raise WrongDatabase(
            f"refusing to start against {url.database!r}: "
            f"{', '.join(sorted(REFUSED_DATABASES))} are wiped by the test run and the "
            "eval, which would take a live conversation with them. "
            "Set ASSISTANT_DATABASE_URL to the `assistant` database."
        )
    return url.database or ""
