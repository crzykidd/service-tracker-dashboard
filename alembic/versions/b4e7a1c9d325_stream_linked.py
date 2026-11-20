"""service_entry.stream_linked and pre_link_host

Revision ID: b4e7a1c9d325
Revises: a9d3c5e7f102
Create Date: 2026-11-19 16:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'b4e7a1c9d325'
down_revision: Union[str, None] = 'a9d3c5e7f102'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """PRD 5.10: a manual entry that joined an inventory stream (Convert / accept /
    link) is marked `stream_linked`, and its old host kept in `pre_link_host`, so
    stream cleanup unlinks it instead of deleting it. Plain columns, no FK, no index.

    Backfill heuristic for entries linked before this migration (there is no
    created timestamp): within each stream, an entry with `name_source = 'ui_edit'`
    (the operator's name; a link sets it) whose `id` is lower than the smallest id
    of that stream's `name_source = 'stream'` entries is marked linked, since a
    stream creates its own entries with higher ids than a manual entry that
    pre-existed. Its host is unknown, so `pre_link_host` stays NULL. A stream with
    no stream-named entry has no reference point, so none of its entries is marked.
    """
    with op.batch_alter_table('service_entry') as batch:
        batch.add_column(sa.Column('stream_linked', sa.Boolean(), nullable=False,
                                   server_default=sa.false()))
        batch.add_column(sa.Column('pre_link_host', sa.String(length=100), nullable=True))
    op.execute(
        "UPDATE service_entry SET stream_linked = 1 "
        "WHERE stream_id IS NOT NULL AND name_source = 'ui_edit' "
        "AND id < (SELECT MIN(s.id) FROM service_entry s "
        "          WHERE s.stream_id = service_entry.stream_id AND s.name_source = 'stream')"
    )


def downgrade() -> None:
    with op.batch_alter_table('service_entry') as batch:
        batch.drop_column('pre_link_host')
        batch.drop_column('stream_linked')
