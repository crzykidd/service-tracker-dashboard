"""Home Assistant opt-out flags: service_entry.ha_exclude / health_check.ha_exclude

Revision ID: d8e2a6f4b915
Revises: a2f4c6e8b031
Create Date: 2026-11-16 21:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'd8e2a6f4b915'
down_revision: Union[str, None] = 'a2f4c6e8b031'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Opt-out columns (NOT NULL, default false) so that publishing everything
    to Home Assistant picks up new rows automatically. Boolean flags, not FKs
    or lookup columns, so no index."""
    for table in ('service_entry', 'health_check'):
        op.add_column(
            table,
            sa.Column('ha_exclude', sa.Boolean(), nullable=False, server_default=sa.false()),
        )


def downgrade() -> None:
    """Drop both columns (batch mode: SQLite rewrites the table)."""
    for table in ('health_check', 'service_entry'):
        with op.batch_alter_table(table) as batch_op:
            batch_op.drop_column('ha_exclude')
