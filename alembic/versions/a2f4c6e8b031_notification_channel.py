"""notification_channel table (notifications: MQTT first)

Revision ID: a2f4c6e8b031
Revises: c2e8a5b3d917
Create Date: 2026-11-16 18:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'a2f4c6e8b031'
down_revision: Union[str, None] = 'c2e8a5b3d917'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create `notification_channel`. No foreign keys; `name` is unique (the
    UI and API look channels up by it) and `type` is indexed."""
    op.create_table(
        'notification_channel',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('type', sa.String(length=32), nullable=False),
        sa.Column('name', sa.String(length=64), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('config', sa.JSON(), nullable=False),
        sa.Column('secret', sa.String(length=512), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
    )
    op.create_index('ux_notification_channel_name', 'notification_channel', ['name'], unique=True)
    op.create_index('ix_notification_channel_type', 'notification_channel', ['type'])


def downgrade() -> None:
    op.drop_index('ix_notification_channel_type', table_name='notification_channel')
    op.drop_index('ux_notification_channel_name', table_name='notification_channel')
    op.drop_table('notification_channel')
