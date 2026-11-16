"""entry source: service_entry.source, nullable host, description

Revision ID: a7c3e9f15d28
Revises: f6b2d8e41c03
Create Date: 2026-11-15 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a7c3e9f15d28'
down_revision: Union[str, None] = 'f6b2d8e41c03'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add `source` ('notifier' | 'manual') and `description`, and let `host`
    be NULL (manual entries may omit it).

    Backfill: a row the notifier never registered (last_api_update IS NULL)
    is a manual entry; everything else stays 'notifier'. No new FK, and
    the (host, container_name) index is unchanged (batch mode keeps it).
    """
    op.add_column(
        'service_entry',
        sa.Column('source', sa.String(length=16), nullable=False, server_default='notifier'),
    )
    op.add_column(
        'service_entry',
        sa.Column('description', sa.String(length=255), nullable=True),
    )
    op.execute("UPDATE service_entry SET source = 'manual' WHERE last_api_update IS NULL")
    with op.batch_alter_table('service_entry') as batch_op:
        batch_op.alter_column('host', existing_type=sa.String(length=100), nullable=True)


def downgrade() -> None:
    """Drop the new columns and make `host` NOT NULL again (batch mode).

    Manual entries without a host get an empty string so the NOT NULL
    constraint can be restored.
    """
    op.execute("UPDATE service_entry SET host = '' WHERE host IS NULL")
    with op.batch_alter_table('service_entry') as batch_op:
        batch_op.alter_column('host', existing_type=sa.String(length=100), nullable=False)
        batch_op.drop_column('description')
        batch_op.drop_column('source')
