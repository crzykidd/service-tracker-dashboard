"""health check options: service_entry.health_check_timeout / health_check_verify_tls

Revision ID: f6b2d8e41c03
Revises: e5a1c7d93b02
Create Date: 2026-11-15 13:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f6b2d8e41c03'
down_revision: Union[str, None] = 'e5a1c7d93b02'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add per-service health-check timeout (NULL = global default) and
    verify-TLS flag (NOT NULL, existing rows keep verifying). Neither is an
    FK or lookup column, so no index."""
    op.add_column(
        'service_entry',
        sa.Column('health_check_timeout', sa.Integer(), nullable=True),
    )
    op.add_column(
        'service_entry',
        sa.Column(
            'health_check_verify_tls',
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )


def downgrade() -> None:
    """Drop both columns (batch mode: SQLite rewrites the table)."""
    with op.batch_alter_table('service_entry') as batch_op:
        batch_op.drop_column('health_check_verify_tls')
        batch_op.drop_column('health_check_timeout')
