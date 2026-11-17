"""cert expiry check: health_check.cert_min_days / last_cert_expires_at

Revision ID: b7d3f1a94e26
Revises: a1c5e8d2f093
Create Date: 2026-11-16 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7d3f1a94e26'
down_revision: Union[str, None] = 'a1c5e8d2f093'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add the certificate-expiry condition (minimum days left; NULL = off)
    and the cached expiry the checker last saw. Both nullable; neither is an
    FK or lookup column, so no index."""
    op.add_column('health_check', sa.Column('cert_min_days', sa.Integer(), nullable=True))
    op.add_column('health_check', sa.Column('last_cert_expires_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    """Drop the columns (batch mode: SQLite rewrites the table)."""
    with op.batch_alter_table('health_check') as batch_op:
        batch_op.drop_column('last_cert_expires_at')
        batch_op.drop_column('cert_min_days')
