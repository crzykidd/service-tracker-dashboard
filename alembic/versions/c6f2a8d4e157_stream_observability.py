"""inventory stream observability: interval, staleness, rejections, missing expiry

Revision ID: c6f2a8d4e157
Revises: b4e7a1c9d325
Create Date: 2026-11-20 12:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'c6f2a8d4e157'
down_revision: Union[str, None] = 'b4e7a1c9d325'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """PRD 18.9 (inv-08). Plain nullable columns; no FK, so no index.

    `inventory_stream`: the operator's expected snapshot interval, the interval the
    producer advertises (`snapshot_interval_seconds` on the PUT), the per-stream
    auto soft-delete of missing entries (days, NULL = off) and the last rejected
    snapshot (time + "<status>: <first error>").

    `service_entry.inventory_missing_since` (naive UTC): when the entry was flagged
    missing. Entries already flagged get the upgrade time: later than the real
    moment, which only delays an auto soft-delete, never brings one forward.
    """
    with op.batch_alter_table('inventory_stream') as batch:
        batch.add_column(sa.Column('expected_interval_seconds', sa.Integer(), nullable=True))
        batch.add_column(sa.Column('producer_interval_seconds', sa.Integer(), nullable=True))
        batch.add_column(sa.Column('missing_expiry_days', sa.Integer(), nullable=True))
        batch.add_column(sa.Column('last_rejected_at', sa.DateTime(), nullable=True))
        batch.add_column(sa.Column('last_rejection', sa.String(length=255), nullable=True))
    with op.batch_alter_table('service_entry') as batch:
        batch.add_column(sa.Column('inventory_missing_since', sa.DateTime(), nullable=True))
    op.execute("UPDATE service_entry SET inventory_missing_since = CURRENT_TIMESTAMP "
               "WHERE inventory_missing = 1")


def downgrade() -> None:
    with op.batch_alter_table('service_entry') as batch:
        batch.drop_column('inventory_missing_since')
    with op.batch_alter_table('inventory_stream') as batch:
        batch.drop_column('last_rejection')
        batch.drop_column('last_rejected_at')
        batch.drop_column('missing_expiry_days')
        batch.drop_column('producer_interval_seconds')
        batch.drop_column('expected_interval_seconds')
