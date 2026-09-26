"""The one database the eval may touch. No `app` imports on purpose: the CLI
needs this before `app.db` builds its engine, see eval/run.py."""

from __future__ import annotations

from typing import Any

from sqlalchemy.engine import make_url

EVAL_DATABASE = "assistant_eval"


class NotTheEvalDatabase(RuntimeError):
    pass


def eval_database_url(base_url: str) -> str:
    """The configured URL with its database swapped for `assistant_eval` —
    same host, port and credentials as the dev database."""
    return make_url(base_url).set(database=EVAL_DATABASE).render_as_string(hide_password=False)


def require_eval_database(target: Any) -> None:
    """`target` is a URL string, a SQLAlchemy URL, an Engine, a Connection
    or a Session."""
    if hasattr(target, "get_bind"):
        target = target.get_bind()
    if hasattr(target, "engine"):  # Connection (Engine.engine is itself)
        target = target.engine
    if hasattr(target, "url"):
        target = target.url
    name = make_url(target).database
    if name != EVAL_DATABASE:
        raise NotTheEvalDatabase(f"refusing to use database {name!r}: the eval only runs against {EVAL_DATABASE!r}")
