"""Home Assistant opt-in per entry: service_entry.ha_publish replaces ha_exclude

Revision ID: e3b7c1d9a204
Revises: d8e2a6f4b915
Create Date: 2026-11-17 10:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'e3b7c1d9a204'
down_revision: Union[str, None] = 'd8e2a6f4b915'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Entries become opt-in. Every existing entry starts unpublished (a clean
    slate, whatever its old ha_exclude was). Boolean flag, not an FK, so no
    index. health_check.ha_exclude is unchanged."""
    with op.batch_alter_table('service_entry') as batch_op:
        batch_op.add_column(
            sa.Column('ha_publish', sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.drop_column('ha_exclude')


def downgrade() -> None:
    """Restore ha_exclude (false for every entry) and drop ha_publish."""
    with op.batch_alter_table('service_entry') as batch_op:
        batch_op.add_column(
            sa.Column('ha_exclude', sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.drop_column('ha_publish')
