"""initial schema

Revision ID: f6f6681eb5d8
Revises: 
Create Date: 2025-06-01 17:50:21.053222

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f6f6681eb5d8'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    if 'service_entry' not in inspector.get_table_names():
        op.create_table(
            'service_entry',
            sa.Column('id', sa.Integer, primary_key=True),
            sa.Column('host', sa.String(length=100), nullable=False),
            sa.Column('container_name', sa.String(length=100), nullable=False),
            sa.Column('container_id', sa.String(length=100)),
            sa.Column('internalurl', sa.String(length=255)),
            sa.Column('externalurl', sa.String(length=255)),
            sa.Column('last_updated', sa.DateTime, nullable=False),
            sa.Column('last_api_update', sa.DateTime),
            sa.Column('stack_name', sa.String(length=100)),
            sa.Column('docker_status', sa.String(length=100)),
            sa.Column('internal_health_check_enabled', sa.Boolean),
            sa.Column('internal_health_check_status', sa.String(length=100)),
            sa.Column('internal_health_check_update', sa.String(length=100)),
            sa.Column('external_health_check_enabled', sa.Boolean),
            sa.Column('external_health_check_status', sa.String(length=100)),
            sa.Column('external_health_check_update', sa.String(length=100)),
            sa.Column('image_registry', sa.String(length=100)),
            sa.Column('image_owner', sa.String(length=100)),
            sa.Column('image_name', sa.String(length=100)),
            sa.Column('image_tag', sa.String(length=100)),
            sa.Column('image_icon', sa.String(length=100)),
            sa.Column('group_name', sa.String(length=20), server_default="zz_none"),
            sa.Column('is_static', sa.Boolean, nullable=False, server_default=sa.text("0")),
            sa.Column('started_at', sa.String(length=100))
        )
    else:
        print("✅ Table 'service_entry' already exists. Skipping creation.")



def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    if 'service_entry' in inspector.get_table_names():
        op.drop_table('service_entry')
    # ### end Alembic commands ###
