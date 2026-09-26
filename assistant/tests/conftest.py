from __future__ import annotations

from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from alembic import command
from app.config import Policy, load_policy, settings

ASSISTANT_DIR = Path(__file__).resolve().parent.parent
TEST_DATABASE_URL = settings.test_database_url


def alembic_config(url: str) -> Config:
    cfg = Config(str(ASSISTANT_DIR / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


def _ensure_database_exists(url: str) -> None:
    target = make_url(url)
    admin_engine = create_engine(target.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        with admin_engine.connect() as conn:
            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": target.database}
            ).first()
            if not exists:
                conn.execute(text(f'CREATE DATABASE "{target.database}"'))
    finally:
        admin_engine.dispose()


def _reset_schema_and_migrate(url: str) -> None:
    engine = create_engine(url, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as conn:
            conn.execute(text("DROP SCHEMA public CASCADE"))
            conn.execute(text("CREATE SCHEMA public"))
    finally:
        engine.dispose()
    command.upgrade(alembic_config(url), "head")


@pytest.fixture(scope="session")
def engine():
    # This fixture drops the whole schema. Never let it near a dev database.
    if not (make_url(TEST_DATABASE_URL).database or "").endswith("_test"):
        raise RuntimeError(f"refusing to wipe non-test database: {TEST_DATABASE_URL}")
    _ensure_database_exists(TEST_DATABASE_URL)
    _reset_schema_and_migrate(TEST_DATABASE_URL)
    eng = create_engine(TEST_DATABASE_URL)
    yield eng
    eng.dispose()


@pytest.fixture()
def db_session(engine):
    """One test = one transaction, rolled back at the end. session.commit()
    inside code under test releases a SAVEPOINT instead of committing
    (SQLAlchemy 2.0 join_transaction_mode='conditional_savepoint'), same as
    Laqta's api/tests/conftest.py."""
    connection = engine.connect()
    trans = connection.begin()
    session = sessionmaker(bind=connection)()
    try:
        yield session
    finally:
        session.close()
        # Conditional: a test that deliberately provokes a failed flush (see
        # test_state_machine's stale-writer test) leaves this transaction
        # already rolled back and deassociated, and rolling it back again
        # only produces a warning.
        if trans.is_active:
            trans.rollback()
        connection.close()


@pytest.fixture(scope="session")
def policy() -> Policy:
    return load_policy()
