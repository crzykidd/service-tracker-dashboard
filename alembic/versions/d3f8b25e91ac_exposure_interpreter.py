"""v0.6.0: exposure interpreter (service_exposure, url source columns, setting)

Revision ID: d3f8b25e91ac
Revises: c9a4f1b27e83
Create Date: 2026-05-13 10:00:00.000000

Three additions for the exposure interpreter feature:

1. `service_exposure` table — one row per (service, interpreter
   layer) observation. The synthesizer reads from this table and the
   register handler writes to it (wholesale replace per service when
   the payload carries `exposure_observations`). FK to
   `service_entry.id` with ON DELETE CASCADE so removing a service
   removes its exposure history. Indexed on `service_entry_id` per
   the database rule that FK columns get their index in the same
   migration.

2. `service_entry.internalurl_source` / `externalurl_source` —
   provenance for each URL. Values: "ui_edit", "explicit_label",
   "synthesized", NULL. The synthesizer respects ordering
   (ui_edit > explicit_label > synthesized > NULL) so a label or
   interpreter coming online later doesn't clobber an operator's UI
   edit.

3. `setting` table — KV-style runtime settings. First operator-
   editable settings in STD; backs the per-interpreter direction
   mapping used by the synthesizer. JSON values so we can store the
   nested dicts the exposure settings need without inventing a
   schema for one feature.

Idempotent where it costs nothing: column additions check existing
columns first so a partial run can be re-applied. Table creates rely
on Alembic's normal behavior — they'll fail loudly if the table
already exists, which is what we want on a clean run.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = 'd3f8b25e91ac'
down_revision: Union[str, None] = 'c9a4f1b27e83'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)

    existing_tables = set(insp.get_table_names())
    if 'service_exposure' not in existing_tables:
        op.create_table(
            'service_exposure',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column(
                'service_entry_id',
                sa.Integer(),
                sa.ForeignKey('service_entry.id', ondelete='CASCADE'),
                nullable=False,
            ),
            sa.Column('layer', sa.String(length=64), nullable=False),
            sa.Column('hostname', sa.String(length=255), nullable=True),
            sa.Column('tls', sa.Boolean(), nullable=True),
            sa.Column('path_prefix', sa.String(length=255), nullable=True),
            sa.Column('auth', sa.String(length=128), nullable=True),
            sa.Column('details', sa.JSON(), nullable=True),
            sa.Column('last_updated', sa.DateTime(), nullable=False),
        )
        op.create_index(
            'ix_service_exposure_service_entry_id',
            'service_exposure',
            ['service_entry_id'],
        )

    existing_service_entry_cols = {
        col["name"] for col in insp.get_columns("service_entry")
    }
    if "internalurl_source" not in existing_service_entry_cols:
        op.add_column(
            'service_entry',
            sa.Column('internalurl_source', sa.String(length=20), nullable=True),
        )
    if "externalurl_source" not in existing_service_entry_cols:
        op.add_column(
            'service_entry',
            sa.Column('externalurl_source', sa.String(length=20), nullable=True),
        )

    if 'setting' not in existing_tables:
        op.create_table(
            'setting',
            sa.Column('key', sa.String(length=64), primary_key=True),
            sa.Column('value', sa.JSON(), nullable=True),
            sa.Column('updated_at', sa.DateTime(), nullable=False),
        )


def downgrade() -> None:
    """Reverse the upgrade. SQLite drop_column requires batch mode."""
    bind = op.get_bind()
    insp = inspect(bind)

    if 'setting' in insp.get_table_names():
        op.drop_table('setting')

    existing_service_entry_cols = {
        col["name"] for col in insp.get_columns("service_entry")
    }
    with op.batch_alter_table('service_entry') as batch_op:
        if 'externalurl_source' in existing_service_entry_cols:
            batch_op.drop_column('externalurl_source')
        if 'internalurl_source' in existing_service_entry_cols:
            batch_op.drop_column('internalurl_source')

    if 'service_exposure' in insp.get_table_names():
        op.drop_index('ix_service_exposure_service_entry_id', table_name='service_exposure')
        op.drop_table('service_exposure')
