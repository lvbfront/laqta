from __future__ import annotations

import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

API_DIR = Path(__file__).resolve().parent.parent

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://laqta:laqta_dev_password@localhost:5432/laqta_test",
)


def _ensure_database_exists(url: str) -> None:
    target = make_url(url)
    admin_url = target.set(database="postgres")
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        with admin_engine.connect() as conn:
            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": target.database},
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

    cfg = Config(str(API_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(API_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")


@pytest.fixture(scope="session")
def engine():
    _ensure_database_exists(TEST_DATABASE_URL)
    _reset_schema_and_migrate(TEST_DATABASE_URL)
    eng = create_engine(TEST_DATABASE_URL, future=True)
    yield eng
    eng.dispose()


@pytest.fixture()
def db_session(engine):
    """One test = one transaction, rolled back at the end. FK cascades and
    check constraints all fire normally within that transaction. Calling
    session.commit() is also safe here and does *not* leak data past the
    fixture: SQLAlchemy 2.0's default join_transaction_mode
    ('conditional_savepoint') makes an inner commit release a SAVEPOINT
    rather than the outer transaction this fixture controls, so route code
    under test (which must call real commit()s) works unmodified against
    this fixture -- verified empirically, not just assumed, before relying
    on it for tests/test_ingest_photos.py.
    """
    connection = engine.connect()
    trans = connection.begin()
    Session = sessionmaker(bind=connection, future=True)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        trans.rollback()
        connection.close()


@pytest.fixture()
def client(db_session):
    """TestClient wired to the same rollback-isolated session as
    db_session, via a get_db dependency override -- every request in a
    test, and any direct db_session assertions in that same test, share
    one transaction that's rolled back at the end.
    """
    from fastapi.testclient import TestClient

    from app.db import get_db
    from app.main import app

    def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()
