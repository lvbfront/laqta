"""initial assistant schema

Revision ID: 8bc87d72d528
Revises:
Create Date: 2026-09-12 00:51:52.451224

Hand-edited after autogenerate, three ways:
  * added the pgvector import and the CREATE EXTENSION (autogenerate renders
    the column type but neither);
  * enum types are created once, up front, with create_type=False on the
    columns -- `team` is used by two tables and `booking_status` by three
    columns, and letting create_table emit its own CREATE TYPE each time
    fails on the second one;
  * the extension is not dropped on downgrade (see the note there).
"""
from typing import Sequence, Union

import pgvector.sqlalchemy
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '8bc87d72d528'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _enum(name: str, *values: str) -> postgresql.ENUM:
    return postgresql.ENUM(*values, name=name, create_type=False)


contact_source = _enum('contact_source', 'chat', 'voice', 'staff')
team = _enum('team', 'sales', 'ops', 'support', 'privacy')
channel = _enum('channel', 'chat', 'voice')
identity_kind = _enum('identity_kind', 'anonymous', 'customer', 'staff')
ticket_priority = _enum('ticket_priority', 'normal', 'urgent', 'privacy')
ticket_reason = _enum(
    'ticket_reason', 'discount', 'premium_quote', 'long_event', 'late_change', 'complaint',
    'live_issue', 'legal', 'unknown_question', 'wants_human',
)
ticket_status = _enum('ticket_status', 'open', 'acknowledged', 'resolved')
booking_status = _enum('booking_status', 'tentative', 'confirmed', 'live', 'ended', 'cancelled')
match_mode = _enum('match_mode', 'face', 'code', 'sequential', 'both')
confirmation_action = _enum('confirmation_action', 'booking', 'reschedule', 'cancel')
kb_audience = _enum('kb_audience', 'public', 'internal')

ALL_ENUMS = (
    contact_source, team, channel, identity_kind, ticket_priority, ticket_reason,
    ticket_status, booking_status, match_mode, confirmation_action, kb_audience,
)


def upgrade() -> None:
    bind = op.get_bind()
    # Extensions are per-database: having it in the laqta database is not
    # enough for this one.
    op.execute('CREATE EXTENSION IF NOT EXISTS vector')
    for enum_type in ALL_ENUMS:
        enum_type.create(bind, checkfirst=True)

    op.create_table('contacts',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('laqta_user_id', sa.UUID(), nullable=True),
    sa.Column('laqta_org_id', sa.UUID(), nullable=True),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('phone', sa.String(length=32), nullable=True),
    sa.Column('email', sa.String(length=320), nullable=True),
    sa.Column('org_name', sa.String(length=255), nullable=True),
    sa.Column('source', contact_source, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('laqta_user_id')
    )
    op.create_table('kb_chunks',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('section_title', sa.String(length=255), nullable=False),
    sa.Column('audience', kb_audience, nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('content_hash', sa.String(length=64), nullable=False),
    sa.Column('embedding', pgvector.sqlalchemy.vector.VECTOR(dim=1024), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('content_hash')
    )
    op.create_table('scheduled_actions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('kind', sa.String(length=64), nullable=False),
    sa.Column('subject_type', sa.String(length=32), nullable=False),
    sa.Column('subject_id', sa.String(length=64), nullable=False),
    sa.Column('run_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('idempotency_key', sa.String(length=255), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('attempts', sa.Integer(), server_default='0', nullable=False),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.Column('executed_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('idempotency_key')
    )
    op.create_index('ix_scheduled_actions_status_run_at', 'scheduled_actions', ['status', 'run_at'], unique=False)
    op.create_table('staff',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('laqta_user_id', sa.UUID(), nullable=True),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('email', sa.String(length=320), nullable=False),
    sa.Column('team', team, nullable=False),
    sa.Column('manager_id', sa.Integer(), nullable=True),
    sa.Column('active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.ForeignKeyConstraint(['manager_id'], ['staff.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('laqta_user_id')
    )
    op.create_table('bookings',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('contact_id', sa.Integer(), nullable=False),
    sa.Column('laqta_org_id', sa.UUID(), nullable=False),
    sa.Column('laqta_event_id', sa.UUID(), nullable=True),
    sa.Column('status', booking_status, nullable=False),
    sa.Column('event_name', sa.String(length=255), nullable=False),
    sa.Column('city', sa.String(length=64), nullable=False),
    sa.Column('venue', sa.String(length=255), nullable=False),
    sa.Column('starts_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('ends_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('expected_guests', sa.Integer(), nullable=False),
    sa.Column('photographers', sa.Integer(), nullable=False),
    sa.Column('match_mode', match_mode, nullable=False),
    sa.Column('strict_mode', sa.Boolean(), nullable=False),
    sa.Column('package', sa.String(length=32), nullable=False),
    sa.Column('addons', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.Column('onsite_support', sa.Boolean(), nullable=False),
    sa.Column('payment_due_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('ends_at > starts_at', name='ck_bookings_ends_after_starts'),
    sa.CheckConstraint('expected_guests > 0', name='ck_bookings_guests_positive'),
    sa.CheckConstraint('photographers > 0', name='ck_bookings_photographers_positive'),
    sa.ForeignKeyConstraint(['contact_id'], ['contacts.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_bookings_city_starts_at', 'bookings', ['city', 'starts_at'], unique=False)
    op.create_index(op.f('ix_bookings_contact_id'), 'bookings', ['contact_id'], unique=False)
    op.create_table('interactions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('contact_id', sa.Integer(), nullable=True),
    sa.Column('staff_id', sa.Integer(), nullable=True),
    sa.Column('channel', channel, nullable=False),
    sa.Column('identity_kind', identity_kind, nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('transcript', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.Column('summary', sa.Text(), nullable=True),
    sa.Column('outcome', sa.String(length=32), nullable=True),
    sa.ForeignKeyConstraint(['contact_id'], ['contacts.id'], ),
    sa.ForeignKeyConstraint(['staff_id'], ['staff.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_interactions_contact_id'), 'interactions', ['contact_id'], unique=False)
    op.create_table('booking_events',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('booking_id', sa.UUID(), nullable=False),
    sa.Column('from_status', booking_status, nullable=True),
    sa.Column('to_status', booking_status, nullable=False),
    sa.Column('trigger', sa.String(length=32), nullable=False),
    sa.Column('actor', sa.String(length=64), nullable=False),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.Column('at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['booking_id'], ['bookings.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_booking_events_booking_id'), 'booking_events', ['booking_id'], unique=False)
    op.create_table('confirmations',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('interaction_id', sa.Integer(), nullable=False),
    sa.Column('action', confirmation_action, nullable=False),
    sa.Column('params', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('params_hash', sa.String(length=64), nullable=False),
    sa.Column('prepared_at_user_turn', sa.Integer(), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['interaction_id'], ['interactions.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_confirmations_interaction_id'), 'confirmations', ['interaction_id'], unique=False)
    op.create_table('tickets',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('contact_id', sa.Integer(), nullable=True),
    sa.Column('interaction_id', sa.Integer(), nullable=False),
    sa.Column('team', team, nullable=False),
    sa.Column('assignee_staff_id', sa.Integer(), nullable=True),
    sa.Column('priority', ticket_priority, nullable=False),
    sa.Column('reason_code', ticket_reason, nullable=False),
    sa.Column('summary', sa.Text(), nullable=False),
    sa.Column('status', ticket_status, nullable=False),
    sa.Column('due_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('acknowledged_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['assignee_staff_id'], ['staff.id'], ),
    sa.ForeignKeyConstraint(['contact_id'], ['contacts.id'], ),
    sa.ForeignKeyConstraint(['interaction_id'], ['interactions.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_tickets_assignee_status', 'tickets', ['assignee_staff_id', 'status'], unique=False)
    op.create_index(op.f('ix_tickets_contact_id'), 'tickets', ['contact_id'], unique=False)
    op.create_table('tool_calls',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('interaction_id', sa.Integer(), nullable=False),
    sa.Column('user_turn', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=64), nullable=False),
    sa.Column('args', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('result', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('ok', sa.Boolean(), nullable=False),
    sa.Column('latency_ms', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['interaction_id'], ['interactions.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_tool_calls_interaction_id'), 'tool_calls', ['interaction_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_tool_calls_interaction_id'), table_name='tool_calls')
    op.drop_table('tool_calls')
    op.drop_index(op.f('ix_tickets_contact_id'), table_name='tickets')
    op.drop_index('ix_tickets_assignee_status', table_name='tickets')
    op.drop_table('tickets')
    op.drop_index(op.f('ix_confirmations_interaction_id'), table_name='confirmations')
    op.drop_table('confirmations')
    op.drop_index(op.f('ix_booking_events_booking_id'), table_name='booking_events')
    op.drop_table('booking_events')
    op.drop_index(op.f('ix_interactions_contact_id'), table_name='interactions')
    op.drop_table('interactions')
    op.drop_index(op.f('ix_bookings_contact_id'), table_name='bookings')
    op.drop_index('ix_bookings_city_starts_at', table_name='bookings')
    op.drop_table('bookings')
    op.drop_table('staff')
    op.drop_index('ix_scheduled_actions_status_run_at', table_name='scheduled_actions')
    op.drop_table('scheduled_actions')
    op.drop_table('kb_chunks')
    op.drop_table('contacts')

    bind = op.get_bind()
    for enum_type in ALL_ENUMS:
        enum_type.drop(bind, checkfirst=True)
    # The vector extension is deliberately left in place: dropping it would
    # take any other vector column in this database with it.
