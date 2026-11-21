"""Operator override for the image repository link: service_entry.image_repo_url

Revision ID: e9b3d5f7a126
Revises: d7a3e9b2c418
Create Date: 2026-11-21 12:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'e9b3d5f7a126'
down_revision: Union[str, None] = 'd7a3e9b2c418'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Nullable free-text URL; not a foreign key or lookup column, so no index."""
    op.add_column('service_entry', sa.Column('image_repo_url', sa.String(length=512), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('service_entry') as batch_op:
        batch_op.drop_column('image_repo_url')
