"""Image update check: image_reference table and the service_entry image update columns

Revision ID: b5d9a3f1c7e2
Revises: a2c6e8f1b345
Create Date: 2026-11-21 18:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'b5d9a3f1c7e2'
down_revision: Union[str, None] = 'a2c6e8f1b345'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """One table of remote facts keyed by reference, and the per-entry columns. No foreign
    keys (the join is `service_entry.image_ref = image_reference.ref`, both indexed), so no
    FK index is needed; `image_reference.ref` is unique and indexed."""
    op.create_table(
        'image_reference',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('ref', sa.String(length=512), nullable=False),
        sa.Column('registry', sa.String(length=255), nullable=False),
        sa.Column('repository', sa.String(length=255), nullable=False),
        sa.Column('tag', sa.String(length=128), nullable=False),
        sa.Column('remote_digest', sa.String(length=80), nullable=True),
        sa.Column('remote_digest_changed_at', sa.DateTime(), nullable=True),
        sa.Column('candidates', sa.JSON(), nullable=True),
        sa.Column('checked_at', sa.DateTime(), nullable=True),
        sa.Column('last_error', sa.String(length=300), nullable=True),
        sa.Column('last_error_at', sa.DateTime(), nullable=True),
        sa.Column('failures', sa.Integer(), server_default='0', nullable=False),
        sa.Column('next_check_at', sa.DateTime(), nullable=True),
        sa.Column('last_wanted_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_image_reference_ref', 'image_reference', ['ref'], unique=True)

    with op.batch_alter_table('service_entry') as batch_op:
        batch_op.add_column(sa.Column('image_running_digest', sa.String(length=80), nullable=True))
        batch_op.add_column(sa.Column('image_info', sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column('image_update_policy', sa.String(length=8),
                                      server_default='auto', nullable=False))
        batch_op.add_column(sa.Column('image_tag_pattern', sa.String(length=200), nullable=True))
        batch_op.add_column(sa.Column('image_update_scope', sa.String(length=8), nullable=True))
        batch_op.add_column(sa.Column('image_update_state', sa.String(length=10), nullable=True))
        batch_op.add_column(sa.Column('image_update_latest', sa.String(length=128), nullable=True))
        batch_op.add_column(sa.Column('image_update_kind', sa.String(length=8), nullable=True))
        batch_op.add_column(sa.Column('image_update_since', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('image_update_provider', sa.String(length=16), nullable=True))
        batch_op.add_column(sa.Column('image_update_detail', sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('service_entry') as batch_op:
        for name in ('image_update_detail', 'image_update_provider', 'image_update_since',
                     'image_update_kind', 'image_update_latest', 'image_update_state',
                     'image_update_scope', 'image_tag_pattern', 'image_update_policy',
                     'image_info', 'image_running_digest'):
            batch_op.drop_column(name)
    op.drop_index('ix_image_reference_ref', table_name='image_reference')
    op.drop_table('image_reference')
