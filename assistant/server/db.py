"""The server's engine.

Its own rather than app.db's, for one reason: a chat session holds a Session
for as long as the conversation lasts, because AgentSession.interaction is an
ORM object bound to it. That is a pooled connection per open conversation, and
app.db's default pool of five would wedge on the sixth tab.
"""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from app.config import settings
from server.config import require_a_usable_database


def make_engine(*, max_sessions: int, url: str | None = None) -> Engine:
    target = url or settings.database_url
    require_a_usable_database(target)
    return create_engine(
        target,
        pool_pre_ping=True,
        pool_size=max_sessions + 5,
        max_overflow=10,
    )


def make_session_factory(engine: Engine) -> sessionmaker:
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)
