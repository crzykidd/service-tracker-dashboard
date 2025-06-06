"""update widget db structure

Revision ID: 1c4b532947e1
Revises: 6a223fe75fd6
Create Date: 2025-06-05 21:16:55.823559

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1c4b532947e1'
down_revision: Union[str, None] = '6a223fe75fd6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema with SQLite-safe batch operations."""
    op.create_table(
        'widget',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('widget_name', sa.String(length=255), nullable=False),
        sa.Column('widget_url', sa.String(length=255), nullable=False),
        sa.Column('widget_fields', sa.JSON(), nullable=False),
        sa.Column('widget_api_key', sa.String(length=255), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )

    op.create_table(
        'widget_value',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('widget_id', sa.Integer(), nullable=False),
        sa.Column('widget_value_key', sa.String(length=255), nullable=False),
        sa.Column('widget_value', sa.String(length=255), nullable=True),
        sa.Column('last_updated', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['widget_id'], ['widget.id']),
        sa.PrimaryKeyConstraint('id')
    )

    # Batch alter the 'service_entry' table
    with op.batch_alter_table('service_entry', schema=None) as batch_op:
        batch_op.add_column(sa.Column('widget_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key('fk_service_widget', 'widget', ['widget_id'], ['id'])
        batch_op.drop_column('widget_key')

    # ### end Alembic commands ###


def downgrade() -> None:
    """Downgrade schema with SQLite-safe batch operations."""
    # Reverse batch changes
    with op.batch_alter_table('service_entry', schema=None) as batch_op:
        batch_op.add_column(sa.Column('widget_key', sa.String(length=255), nullable=True))
        batch_op.drop_constraint('fk_service_widget', type_='foreignkey')
        batch_op.drop_column('widget_id')

    op.drop_table('widget_value')
    op.drop_table('widget')

    # ### end Alembic commands ###
