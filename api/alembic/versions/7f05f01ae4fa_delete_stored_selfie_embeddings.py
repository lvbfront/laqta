"""delete stored selfie embeddings

Revision ID: 7f05f01ae4fa
Revises: bf991bc9a644
Create Date: 2026-10-06 06:30:00

app/api/routes/match.py no longer stores the selfie's embedding (nothing
ever read it back). This deletes the ones stored before that change, with
an audit_log entry recording how many, the same way the purge job records
its guest_faces deletions. Not reversible: the vectors are gone.
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '7f05f01ae4fa'
down_revision: Union[str, None] = 'bf991bc9a644'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "INSERT INTO audit_log (id, actor, action, subject, meta) "
        "SELECT gen_random_uuid(), 'system:migration', 'delete_stored_selfie_embeddings', 'guest_faces', "
        "jsonb_build_object('count', count(*)) FROM guest_faces HAVING count(*) > 0"
    )
    op.execute("DELETE FROM guest_faces")


def downgrade() -> None:
    pass
