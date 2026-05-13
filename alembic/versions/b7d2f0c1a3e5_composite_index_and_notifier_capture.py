"""v0.5.0: composite index on service_entry, notifier-reported capture columns

Revision ID: b7d2f0c1a3e5
Revises: 4e9c2d3f8a17
Create Date: 2026-05-11 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7d2f0c1a3e5'
down_revision: Union[str, None] = '4e9c2d3f8a17'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add the composite index on the register upsert key and two
    notifier-reported capture columns.

    Index: non-unique. (host, container_name) is the logical key for
    every register upsert; v0.4.x runs this lookup unindexed on every
    /api/register call. Non-unique because a v0.6.0 cleanup migration
    is the right place to handle any duplicates that may have
    accumulated in operator databases — failing this migration on a
    dirty DB would block the v0.5.0 upgrade.

    Columns: notifier_reported_* fields record what the notifier
    most recently sent for fields the user can override (group,
    sort_priority). They're populated by the v0.5.0 register handler
    (Phase 5 work) and consumed by a planned overridden-labels
    export feature — nothing reads them in v0.5.0 itself.
    """
    op.add_column(
        'service_entry',
        sa.Column('notifier_reported_group_name', sa.String(length=100), nullable=True),
    )
    op.add_column(
        'service_entry',
        sa.Column('notifier_reported_sort_priority', sa.Integer(), nullable=True),
    )
    op.create_index(
        'ix_service_entry_host_container_name',
        'service_entry',
        ['host', 'container_name'],
        unique=False,
    )


def downgrade() -> None:
    """Drop the index and the two capture columns.

    SQLite drop_column is reached via batch_alter_table so the table
    is rewritten in place — same pattern the session_token drop used.
    """
    op.drop_index('ix_service_entry_host_container_name', table_name='service_entry')
    with op.batch_alter_table('service_entry') as batch_op:
        batch_op.drop_column('notifier_reported_sort_priority')
        batch_op.drop_column('notifier_reported_group_name')
