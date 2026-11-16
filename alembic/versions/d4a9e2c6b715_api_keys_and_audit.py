"""admin API keys and the management-API write audit log (v0.8.0)

Revision ID: d4a9e2c6b715
Revises: c1d7a3e5f2b8
Create Date: 2026-11-15 21:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'd4a9e2c6b715'
down_revision: Union[str, None] = 'c1d7a3e5f2b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'api_key',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(length=64), nullable=False),
        sa.Column('prefix', sa.String(length=8), nullable=False),
        sa.Column('key_hash', sa.String(length=64), nullable=False),
        sa.Column('scope', sa.String(length=8), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('created_by', sa.Integer(), sa.ForeignKey('user.id'), nullable=True),
        sa.Column('last_used_at', sa.DateTime(), nullable=True),
        sa.Column('last_used_ip', sa.String(length=64), nullable=True),
        sa.Column('revoked_at', sa.DateTime(), nullable=True),
        sa.UniqueConstraint('name', name='uq_api_key_name'),
    )
    op.create_index('ix_api_key_prefix', 'api_key', ['prefix'])
    op.create_index('ix_api_key_created_by', 'api_key', ['created_by'])

    op.create_table(
        'api_audit',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('ts', sa.DateTime(), nullable=False),
        sa.Column('api_key_id', sa.Integer(),
                  sa.ForeignKey('api_key.id', ondelete='SET NULL'), nullable=True),
        sa.Column('key_name', sa.String(length=64), nullable=True),
        sa.Column('method', sa.String(length=8), nullable=False),
        sa.Column('path', sa.String(length=255), nullable=False),
        sa.Column('object_type', sa.String(length=32), nullable=True),
        sa.Column('object_id', sa.String(length=64), nullable=True),
        sa.Column('status_code', sa.Integer(), nullable=False),
        sa.Column('changes', sa.JSON(), nullable=True),
    )
    op.create_index('ix_api_audit_ts', 'api_audit', ['ts'])
    op.create_index('ix_api_audit_api_key_id', 'api_audit', ['api_key_id'])


def downgrade() -> None:
    op.drop_index('ix_api_audit_api_key_id', table_name='api_audit')
    op.drop_index('ix_api_audit_ts', table_name='api_audit')
    op.drop_table('api_audit')
    op.drop_index('ix_api_key_created_by', table_name='api_key')
    op.drop_index('ix_api_key_prefix', table_name='api_key')
    op.drop_table('api_key')
