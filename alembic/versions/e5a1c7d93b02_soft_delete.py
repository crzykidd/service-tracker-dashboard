"""soft delete: service_entry.deleted_at

Revision ID: e5a1c7d93b02
Revises: d3f8b25e91ac
Create Date: 2026-11-15 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e5a1c7d93b02'
down_revision: Union[str, None] = 'd3f8b25e91ac'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add the nullable deleted_at timestamp and its index.

    NULL means active; existing rows stay active. The index backs the
    `deleted_at IS NULL` filter on every dashboard/health/widget query
    and the purge job's age scan.
    """
    op.add_column(
        'service_entry',
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
    )
    op.create_index(
        'ix_service_entry_deleted_at',
        'service_entry',
        ['deleted_at'],
        unique=False,
    )


def downgrade() -> None:
    """Drop the index and column (batch mode: SQLite rewrites the table)."""
    op.drop_index('ix_service_entry_deleted_at', table_name='service_entry')
    with op.batch_alter_table('service_entry') as batch_op:
        batch_op.drop_column('deleted_at')
