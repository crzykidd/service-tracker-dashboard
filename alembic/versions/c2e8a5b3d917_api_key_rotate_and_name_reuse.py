"""api_key.rotated_at, and key names unique among active keys only

Revision ID: c2e8a5b3d917
Revises: b7d3f1a94e26
Create Date: 2026-11-16 15:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'c2e8a5b3d917'
down_revision: Union[str, None] = 'b7d3f1a94e26'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add `rotated_at`; replace the column-level unique name (constraint
    `uq_api_key_name`, from d4a9e2c6b715) with a partial unique index over
    active keys, so a revoked key's name can be reused. SQLite cannot drop a
    constraint in place, hence batch mode."""
    with op.batch_alter_table('api_key') as batch_op:
        batch_op.add_column(sa.Column('rotated_at', sa.DateTime(), nullable=True))
        batch_op.drop_constraint('uq_api_key_name', type_='unique')
    op.create_index('ux_api_key_name_active', 'api_key', ['name'], unique=True,
                    sqlite_where=sa.text('revoked_at IS NULL'))


def downgrade() -> None:
    """Restore the all-rows unique name. Fails with a clear message if a
    revoked key shares a name with another key (rename or delete one first)."""
    bind = op.get_bind()
    dupes = bind.execute(sa.text(
        "SELECT name FROM api_key GROUP BY name HAVING count(*) > 1")).fetchall()
    if dupes:
        names = ", ".join(sorted(r[0] for r in dupes))
        raise RuntimeError(
            "Cannot downgrade: these API key names are used by more than one key "
            f"(a revoked key reused a name): {names}. Rename or delete the older "
            "key rows, then downgrade again.")
    op.drop_index('ux_api_key_name_active', table_name='api_key')
    with op.batch_alter_table('api_key') as batch_op:
        batch_op.drop_column('rotated_at')
        batch_op.create_unique_constraint('uq_api_key_name', ['name'])
