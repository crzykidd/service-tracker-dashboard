"""drop unused User.session_token column

Revision ID: 4e9c2d3f8a17
Revises: 84ff7d556864
Create Date: 2026-05-10 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = '4e9c2d3f8a17'
down_revision: Union[str, None] = '84ff7d556864'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Drop the unused User.session_token column.

    Defensive against installs that already dropped the column manually:
    if the column isn't present, we no-op rather than erroring.
    SQLite reaches the column drop via batch_alter_table, which rewrites
    the table in place and naturally discards the column-scoped unique
    constraint.
    """
    bind = op.get_bind()
    existing_columns = {col["name"] for col in inspect(bind).get_columns("user")}
    if "session_token" not in existing_columns:
        return

    with op.batch_alter_table("user") as batch_op:
        batch_op.drop_column("session_token")


def downgrade() -> None:
    """Restore the User.session_token column (nullable, no unique constraint).

    The original create-table migration added a UNIQUE constraint on this
    column, but downgrade restores it as a plain nullable column only —
    nothing in the codebase reads or writes it, and a unique constraint
    on a column that's always NULL is meaningless.
    """
    with op.batch_alter_table("user") as batch_op:
        batch_op.add_column(
            sa.Column("session_token", sa.String(length=128), nullable=True)
        )
