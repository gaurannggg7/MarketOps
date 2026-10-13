"""initial schema

Creates all V1 tables. Notable database-enforced invariants:
- uq_alert_rules_one_enabled: one enabled rule per instrument/type (partial unique index).
- uq_incidents_one_unresolved_per_rule: one unresolved incident per rule (partial unique index).
- ck_incidents_resolution_requirements: RESOLVED requires ack, a non-blank note, and recovery.
- Audit/comment rows never cascade-delete; only watchlist items cascade with their watchlist.

Revision ID: 0001
Revises: 
Create Date: 2026-10-13 14:20:33.220197
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0001'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SEQUENCE incident_number_seq START 1001")
    op.create_table('instruments',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('symbol', sa.String(length=16), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('asset_label', sa.String(length=40), nullable=False),
    sa.Column('base_price', sa.Numeric(precision=18, scale=6), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.CheckConstraint('base_price > 0', name='ck_instruments_base_price_pos'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('symbol')
    )
    op.create_table('users',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('email', sa.String(length=254), nullable=False),
    sa.Column('display_name', sa.String(length=100), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=False),
    sa.Column('role', sa.Enum('VIEWER', 'OPERATOR', name='user_role'), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('email')
    )
    op.create_table('alert_rules',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('instrument_id', sa.UUID(), nullable=False),
    sa.Column('rule_type', sa.Enum('STALE', 'WIDE_SPREAD', name='rule_type'), nullable=False),
    sa.Column('threshold', sa.Numeric(precision=12, scale=4), nullable=False),
    sa.Column('unit', sa.Enum('SECONDS', 'BPS', name='threshold_unit'), nullable=False),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("(rule_type = 'STALE' AND unit = 'SECONDS') OR (rule_type = 'WIDE_SPREAD' AND unit = 'BPS')", name='ck_alert_rules_unit_matches_type'),
    sa.CheckConstraint('threshold > 0', name='ck_alert_rules_threshold_pos'),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['instrument_id'], ['instruments.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('uq_alert_rules_one_enabled', 'alert_rules', ['instrument_id', 'rule_type'], unique=True, postgresql_where=sa.text('enabled'))
    op.create_table('audit_events',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('actor_id', sa.UUID(), nullable=True),
    sa.Column('actor_kind', sa.String(length=10), nullable=False),
    sa.Column('action', sa.String(length=60), nullable=False),
    sa.Column('entity_type', sa.String(length=40), nullable=False),
    sa.Column('entity_id', sa.String(length=64), nullable=False),
    sa.Column('before', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('after', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('correlation_id', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("(actor_kind = 'USER') = (actor_id IS NOT NULL)", name='ck_audit_events_actor_id'),
    sa.CheckConstraint("actor_kind IN ('USER', 'SYSTEM')", name='ck_audit_events_actor_kind'),
    sa.ForeignKeyConstraint(['actor_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_audit_events_entity', 'audit_events', ['entity_type', 'entity_id', 'created_at', 'id'], unique=False)
    op.create_table('market_events',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('instrument_id', sa.UUID(), nullable=True),
    sa.Column('event_type', sa.String(length=40), nullable=False),
    sa.Column('observed_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('evidence', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.ForeignKeyConstraint(['instrument_id'], ['instruments.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_market_events_instrument_observed', 'market_events', ['instrument_id', 'observed_at', 'id'], unique=False)
    op.create_index('ix_market_events_observed_id', 'market_events', ['observed_at', 'id'], unique=False)
    op.create_index('ix_market_events_type_observed', 'market_events', ['event_type', 'observed_at', 'id'], unique=False)
    op.create_table('quote_samples',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('instrument_id', sa.UUID(), nullable=False),
    sa.Column('bid', sa.Numeric(precision=18, scale=6), nullable=False),
    sa.Column('ask', sa.Numeric(precision=18, scale=6), nullable=False),
    sa.Column('volume', sa.BigInteger(), nullable=False),
    sa.Column('source_time', sa.DateTime(timezone=True), nullable=False),
    sa.Column('received_time', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint('bid > 0 AND ask > 0', name='ck_quote_samples_positive'),
    sa.CheckConstraint('volume >= 0', name='ck_quote_samples_volume'),
    sa.ForeignKeyConstraint(['instrument_id'], ['instruments.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_quote_samples_instrument_time_id', 'quote_samples', ['instrument_id', 'received_time', 'id'], unique=False)
    op.create_index('ix_quote_samples_received_time', 'quote_samples', ['received_time'], unique=False)
    op.create_table('sessions',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('user_id', sa.UUID(), nullable=False),
    sa.Column('csrf_token_hash', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('token_hash')
    )
    op.create_index(op.f('ix_sessions_user_id'), 'sessions', ['user_id'], unique=False)
    op.create_table('watchlists',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('owner_id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(length=80), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('owner_id', 'name', name='uq_watchlists_owner_name')
    )
    op.create_index(op.f('ix_watchlists_owner_id'), 'watchlists', ['owner_id'], unique=False)
    op.create_table('alert_episodes',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('rule_id', sa.UUID(), nullable=False),
    sa.Column('rule_version', sa.Integer(), nullable=False),
    sa.Column('breached_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('recovered_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('trigger_evidence', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('recovery_evidence', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('incident_id', sa.UUID(), nullable=True),
    sa.ForeignKeyConstraint(['rule_id'], ['alert_rules.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_alert_episodes_rule_breached', 'alert_episodes', ['rule_id', 'breached_at'], unique=False)
    op.create_table('watchlist_items',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('watchlist_id', sa.UUID(), nullable=False),
    sa.Column('instrument_id', sa.UUID(), nullable=False),
    sa.Column('added_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['instrument_id'], ['instruments.id'], ),
    sa.ForeignKeyConstraint(['watchlist_id'], ['watchlists.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('watchlist_id', 'instrument_id', name='uq_watchlist_items_pair')
    )
    op.create_table('incidents',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('number', sa.BigInteger(), server_default=sa.text("nextval('incident_number_seq')"), nullable=False),
    sa.Column('rule_id', sa.UUID(), nullable=False),
    sa.Column('rule_version', sa.Integer(), nullable=False),
    sa.Column('instrument_id', sa.UUID(), nullable=False),
    sa.Column('episode_id', sa.UUID(), nullable=False),
    sa.Column('incident_type', sa.Enum('STALE', 'WIDE_SPREAD', name='rule_type'), nullable=False),
    sa.Column('status', sa.Enum('OPEN', 'ACKNOWLEDGED', 'RESOLVED', name='incident_status'), nullable=False),
    sa.Column('severity', sa.Enum('HIGH', 'MEDIUM', 'LOW', name='incident_severity'), nullable=False),
    sa.Column('trigger_reason', sa.Text(), nullable=False),
    sa.Column('trigger_evidence', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('latest_evidence', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('condition_active', sa.Boolean(), nullable=False),
    sa.Column('condition_changed_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('breach_count', sa.Integer(), nullable=False),
    sa.Column('assignee_id', sa.UUID(), nullable=True),
    sa.Column('opened_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('acknowledged_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('acknowledged_by', sa.UUID(), nullable=True),
    sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('resolved_by', sa.UUID(), nullable=True),
    sa.Column('resolution_note', sa.Text(), nullable=True),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("status <> 'RESOLVED' OR (resolution_note IS NOT NULL AND length(btrim(resolution_note)) > 0 AND acknowledged_at IS NOT NULL AND resolved_at IS NOT NULL AND NOT condition_active)", name='ck_incidents_resolution_requirements'),
    sa.CheckConstraint("status = 'OPEN' OR acknowledged_at IS NOT NULL", name='ck_incidents_ack_before_progress'),
    sa.ForeignKeyConstraint(['acknowledged_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['assignee_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['episode_id'], ['alert_episodes.id'], ),
    sa.ForeignKeyConstraint(['instrument_id'], ['instruments.id'], ),
    sa.ForeignKeyConstraint(['resolved_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['rule_id'], ['alert_rules.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('number')
    )
    op.create_index('ix_incidents_instrument', 'incidents', ['instrument_id'], unique=False)
    op.create_index('ix_incidents_status_opened', 'incidents', ['status', 'opened_at'], unique=False)
    op.create_index('uq_incidents_one_unresolved_per_rule', 'incidents', ['rule_id'], unique=True, postgresql_where=sa.text("status <> 'RESOLVED'"))
    op.create_table('incident_comments',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('incident_id', sa.UUID(), nullable=False),
    sa.Column('author_id', sa.UUID(), nullable=False),
    sa.Column('body', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint('length(btrim(body)) > 0', name='ck_incident_comments_body'),
    sa.ForeignKeyConstraint(['author_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['incident_id'], ['incidents.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_incident_comments_incident_created', 'incident_comments', ['incident_id', 'created_at'], unique=False)
    op.create_foreign_key('fk_alert_episodes_incident', 'alert_episodes', 'incidents', ['incident_id'], ['id'])


def downgrade() -> None:
    # Destructive: drops every MarketOps table. Never run automatically in production (runbook).
    op.drop_constraint('fk_alert_episodes_incident', 'alert_episodes', type_='foreignkey')
    op.drop_index('ix_incident_comments_incident_created', table_name='incident_comments')
    op.drop_table('incident_comments')
    op.drop_index('uq_incidents_one_unresolved_per_rule', table_name='incidents', postgresql_where=sa.text("status <> 'RESOLVED'"))
    op.drop_index('ix_incidents_status_opened', table_name='incidents')
    op.drop_index('ix_incidents_instrument', table_name='incidents')
    op.drop_table('incidents')
    op.drop_table('watchlist_items')
    op.drop_index('ix_alert_episodes_rule_breached', table_name='alert_episodes')
    op.drop_table('alert_episodes')
    op.drop_index(op.f('ix_watchlists_owner_id'), table_name='watchlists')
    op.drop_table('watchlists')
    op.drop_index(op.f('ix_sessions_user_id'), table_name='sessions')
    op.drop_table('sessions')
    op.drop_index('ix_quote_samples_received_time', table_name='quote_samples')
    op.drop_index('ix_quote_samples_instrument_time_id', table_name='quote_samples')
    op.drop_table('quote_samples')
    op.drop_index('ix_market_events_type_observed', table_name='market_events')
    op.drop_index('ix_market_events_observed_id', table_name='market_events')
    op.drop_index('ix_market_events_instrument_observed', table_name='market_events')
    op.drop_table('market_events')
    op.drop_index('ix_audit_events_entity', table_name='audit_events')
    op.drop_table('audit_events')
    op.drop_index('uq_alert_rules_one_enabled', table_name='alert_rules', postgresql_where=sa.text('enabled'))
    op.drop_table('alert_rules')
    op.drop_table('users')
    op.drop_table('instruments')
    op.execute("DROP SEQUENCE incident_number_seq")
    for enum_name in ('incident_severity', 'incident_status', 'threshold_unit', 'rule_type', 'user_role'):
        op.execute(f"DROP TYPE IF EXISTS {enum_name}")
