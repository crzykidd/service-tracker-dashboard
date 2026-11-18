"""inventory streams: inventory_stream, inventory_block, stream_link_offer, service_entry stream columns

Revision ID: f4c8a2e6d173
Revises: e3b7c1d9a204
Create Date: 2026-11-17 14:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'f4c8a2e6d173'
down_revision: Union[str, None] = 'e3b7c1d9a204'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """PRD 18.4. Every FK column gets its index here. The (stream_id,
    stream_key) unique index is partial: only rows that belong to a stream."""
    op.create_table(
        'inventory_stream',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('stream_id', sa.String(length=63), nullable=False),
        sa.Column('display_name', sa.String(length=32), nullable=False),
        sa.Column('producer', sa.String(length=64), nullable=False),
        sa.Column('producer_version', sa.String(length=32), nullable=False),
        sa.Column('key_type', sa.String(length=16), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False, server_default='pending'),
        sa.Column('api_key_id', sa.Integer(), sa.ForeignKey('api_key.id', ondelete='SET NULL'),
                  nullable=True),
        sa.Column('network_include', sa.JSON(), nullable=True),
        sa.Column('network_exclude', sa.JSON(), nullable=True),
        sa.Column('snapshot', sa.JSON(), nullable=True),
        sa.Column('first_seen_at', sa.DateTime(), nullable=False),
        sa.Column('last_snapshot_at', sa.DateTime(), nullable=True),
        sa.Column('last_applied_at', sa.DateTime(), nullable=True),
        sa.Column('last_item_count', sa.Integer(), nullable=True),
        sa.Column('last_counts', sa.JSON(), nullable=True),
        sa.Column('last_error', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('stream_id', name='uq_inventory_stream_stream_id'),
    )
    op.create_index('ix_inventory_stream_api_key_id', 'inventory_stream', ['api_key_id'])

    op.create_table(
        'inventory_block',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('stream_id', sa.Integer(), sa.ForeignKey('inventory_stream.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('key', sa.String(length=128), nullable=False),
        sa.Column('name', sa.String(length=128), nullable=True),
        sa.Column('ip', sa.String(length=64), nullable=True),
        sa.Column('blocked_at', sa.DateTime(), nullable=False),
        sa.Column('blocked_by', sa.String(length=80), nullable=True),
    )
    op.create_index('ix_inventory_block_stream_id', 'inventory_block', ['stream_id'])
    op.create_index('ux_inventory_block_stream_key', 'inventory_block', ['stream_id', 'key'], unique=True)

    with op.batch_alter_table('service_entry') as batch_op:
        batch_op.add_column(sa.Column('stream_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('stream_key', sa.String(length=128), nullable=True))
        batch_op.add_column(sa.Column('mac', sa.String(length=17), nullable=True))
        batch_op.add_column(sa.Column('ip', sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column('network', sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column('attributes', sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column('inventory_missing', sa.Boolean(), nullable=False,
                                      server_default=sa.false()))
        batch_op.add_column(sa.Column('name_source', sa.String(length=16), nullable=True))
        batch_op.create_foreign_key('fk_service_entry_stream_id', 'inventory_stream',
                                    ['stream_id'], ['id'])
        batch_op.create_index('ix_service_entry_stream_id', ['stream_id'])
    op.create_index(
        'ux_service_entry_stream_key', 'service_entry', ['stream_id', 'stream_key'],
        unique=True, sqlite_where=sa.text('stream_id IS NOT NULL'),
    )

    op.create_table(
        'stream_link_offer',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('stream_id', sa.Integer(), sa.ForeignKey('inventory_stream.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('key', sa.String(length=128), nullable=False),
        sa.Column('entry_id', sa.Integer(), sa.ForeignKey('service_entry.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('item', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
    )
    op.create_index('ix_stream_link_offer_stream_id', 'stream_link_offer', ['stream_id'])
    op.create_index('ix_stream_link_offer_entry_id', 'stream_link_offer', ['entry_id'])
    op.create_index('ux_stream_link_offer_stream_key', 'stream_link_offer', ['stream_id', 'key'],
                    unique=True)


def downgrade() -> None:
    """Drop everything the upgrade added. Stream entries (source 'stream') become
    manual entries first, so an older STD sees only values it knows."""
    op.drop_table('stream_link_offer')
    op.execute("UPDATE service_entry SET source = 'manual' WHERE source = 'stream'")
    op.drop_index('ux_service_entry_stream_key', table_name='service_entry')
    with op.batch_alter_table('service_entry') as batch_op:
        batch_op.drop_index('ix_service_entry_stream_id')
        batch_op.drop_constraint('fk_service_entry_stream_id', type_='foreignkey')
        batch_op.drop_column('name_source')
        batch_op.drop_column('inventory_missing')
        batch_op.drop_column('attributes')
        batch_op.drop_column('network')
        batch_op.drop_column('ip')
        batch_op.drop_column('mac')
        batch_op.drop_column('stream_key')
        batch_op.drop_column('stream_id')
    op.drop_table('inventory_block')
    op.drop_table('inventory_stream')
