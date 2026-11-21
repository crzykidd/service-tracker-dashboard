"""widen service_entry.container_name to 128 characters

Revision ID: d7a3e9b2c418
Revises: c6f2a8d4e157
Create Date: 2026-11-20 18:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'd7a3e9b2c418'
down_revision: Union[str, None] = 'c6f2a8d4e157'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """The stream ingest contract allows 128-character item names (PRD 18.5), the entry
    name column was String(100). No FK; the composite index
    `ix_service_entry_host_container_name` is carried through the batch rebuild."""
    with op.batch_alter_table('service_entry') as batch:
        batch.alter_column('container_name', existing_type=sa.String(length=100),
                           type_=sa.String(length=128), existing_nullable=False)


def downgrade() -> None:
    """Narrow back. SQLite does not enforce VARCHAR length, so longer names already
    stored stay intact (the model, not the database, enforces the limit)."""
    with op.batch_alter_table('service_entry') as batch:
        batch.alter_column('container_name', existing_type=sa.String(length=128),
                           type_=sa.String(length=100), existing_nullable=False)
