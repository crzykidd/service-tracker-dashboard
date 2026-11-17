"""dns check: health_check.dns_name / dns_record_type / dns_expected_rcode / dns_expected_answer

Revision ID: a1c5e8d2f093
Revises: d4a9e2c6b715
Create Date: 2026-11-16 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1c5e8d2f093'
down_revision: Union[str, None] = 'd4a9e2c6b715'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add the DNS check's query settings. All nullable (only DNS checks use
    them); none is an FK or lookup column, so no index."""
    op.add_column('health_check', sa.Column('dns_name', sa.String(length=255), nullable=True))
    op.add_column('health_check', sa.Column('dns_record_type', sa.String(length=8), nullable=True))
    op.add_column('health_check', sa.Column('dns_expected_rcode', sa.String(length=16), nullable=True))
    op.add_column('health_check', sa.Column('dns_expected_answer', sa.String(length=255), nullable=True))


def downgrade() -> None:
    """Drop the columns (batch mode: SQLite rewrites the table). DNS checks
    left behind keep `check_type='dns'` but cannot be probed; remove them
    first if you downgrade for real."""
    with op.batch_alter_table('health_check') as batch_op:
        batch_op.drop_column('dns_expected_answer')
        batch_op.drop_column('dns_expected_rcode')
        batch_op.drop_column('dns_record_type')
        batch_op.drop_column('dns_name')
