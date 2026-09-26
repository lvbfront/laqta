"""contact stated gender

Revision ID: 3f1c9b7a2d40
Revises: e873048f0052
Create Date: 2026-09-13 10:00:00.000000

Hand-written: autogenerate would add the column but not create the enum type
first, and would not drop the type on downgrade.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '3f1c9b7a2d40'
down_revision: Union[str, None] = 'e873048f0052'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

contact_gender = postgresql.ENUM('male', 'female', name='contact_gender', create_type=False)


def upgrade() -> None:
    contact_gender.create(op.get_bind(), checkfirst=True)
    op.add_column('contacts', sa.Column('gender', contact_gender, nullable=True))


def downgrade() -> None:
    op.drop_column('contacts', 'gender')
    contact_gender.drop(op.get_bind(), checkfirst=True)
