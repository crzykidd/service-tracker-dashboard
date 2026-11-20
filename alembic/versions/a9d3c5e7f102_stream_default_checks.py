"""inventory_stream.default_checks

Revision ID: a9d3c5e7f102
Revises: f4c8a2e6d173
Create Date: 2026-11-19 12:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'a9d3c5e7f102'
down_revision: Union[str, None] = 'f4c8a2e6d173'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """PRD 18.4: per-stream default checks, `{"ping": bool, "tcp_port": int | null}`.
    A plain nullable JSON column; no FK, so no index."""
    with op.batch_alter_table('inventory_stream') as batch:
        batch.add_column(sa.Column('default_checks', sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('inventory_stream') as batch:
        batch.drop_column('default_checks')
