from __future__ import annotations

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect, text

from alembic import command
from app.config import EMBEDDING_DIM
from app.db import Base
from tests.conftest import TEST_DATABASE_URL, alembic_config

EXPECTED_TABLES = {
    "contacts",
    "staff",
    "interactions",
    "tool_calls",
    "tickets",
    "bookings",
    "booking_events",
    "confirmations",
    "kb_chunks",
    "scheduled_actions",
}


def test_all_spec_tables_exist(engine):
    assert EXPECTED_TABLES <= set(inspect(engine).get_table_names())


def test_pgvector_extension_enabled(engine):
    with engine.connect() as conn:
        assert conn.execute(text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")).first()


def test_kb_embedding_dimension_matches_config(engine):
    with engine.connect() as conn:
        typ = conn.execute(
            text("SELECT format_type(atttypid, atttypmod) FROM pg_attribute "
                 "WHERE attrelid = 'kb_chunks'::regclass AND attname = 'embedding'")
        ).scalar_one()
    assert typ == f"vector({EMBEDDING_DIM})"


def test_models_and_migrations_agree(engine):
    """No schema drift: autogenerate against head must find nothing to do."""
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == []


def test_downgrade_to_base_and_back(engine):
    cfg = alembic_config(TEST_DATABASE_URL)
    command.downgrade(cfg, "base")
    assert not EXPECTED_TABLES & set(inspect(engine).get_table_names())
    command.upgrade(cfg, "head")
    assert EXPECTED_TABLES <= set(inspect(engine).get_table_names())
