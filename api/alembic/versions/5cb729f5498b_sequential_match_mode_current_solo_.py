"""sequential match mode, current_solo_number

Revision ID: 5cb729f5498b
Revises: 119dbd3c59aa
Create Date: 2026-09-10 13:49:35.228595

Autogenerate proposed dropping ix_faces_embedding_hnsw_cosine again --
same recurring false positive as every prior migration here (pgvector's
HNSW index type isn't introspected by SQLAlchemy's reflection). Removed
below, same as always.

Also hand-added: ALTER TYPE match_mode ADD VALUE 'sequential'.
Autogenerate doesn't detect new Python enum members against an existing
Postgres native enum type on its own -- this has to be authored by hand.
Postgres requires ADD VALUE to run outside the migration's normal
transaction (can't be used in the same transaction that adds it), hence
op.get_context().autocommit_block() below.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5cb729f5498b'
down_revision: Union[str, None] = '119dbd3c59aa'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE match_mode ADD VALUE IF NOT EXISTS 'sequential'")
    op.add_column('events', sa.Column('current_solo_number', sa.Integer(), nullable=True))


def downgrade() -> None:
    # Postgres has no ALTER TYPE ... DROP VALUE -- removing an enum label
    # requires recreating the type (and rewriting every row/dependent
    # object referencing it), not attempted here. Any event actually using
    # match_mode='sequential' would need to be migrated off it by hand
    # first. This downgrade only reverses the column add.
    op.drop_column('events', 'current_solo_number')
