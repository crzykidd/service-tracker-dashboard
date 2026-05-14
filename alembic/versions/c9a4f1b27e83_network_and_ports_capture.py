"""v0.6.0: capture container networks, exposed ports, published ports

Revision ID: c9a4f1b27e83
Revises: b7d2f0c1a3e5
Create Date: 2026-05-13 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = 'c9a4f1b27e83'
down_revision: Union[str, None] = 'b7d2f0c1a3e5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add three nullable JSON columns to service_entry capturing
    container facts observed by the notifier:

    - networks: list of {"name": str, "aliases": [str]} dicts.
    - exposed_ports: list of "<port>/<proto>" strings (e.g. "80/tcp").
    - published_ports: list of {"container_port", "protocol",
      "host_ip", "host_port"} dicts.

    All three are pure observation — overwritten on every register
    call by the notifier. Existing rows have NULL until the next
    register from a v0.3.2+ notifier; that's the expected state, not
    a bug. Notifier v0.3.2 ships AFTER STD v0.6.0 deploys.

    Idempotent: skips columns that already exist so a partial run
    can be re-applied. Same defensive pattern the session_token drop
    used.
    """
    bind = op.get_bind()
    existing = {col["name"] for col in inspect(bind).get_columns("service_entry")}

    if "networks" not in existing:
        op.add_column(
            'service_entry',
            sa.Column('networks', sa.JSON(), nullable=True),
        )
    if "exposed_ports" not in existing:
        op.add_column(
            'service_entry',
            sa.Column('exposed_ports', sa.JSON(), nullable=True),
        )
    if "published_ports" not in existing:
        op.add_column(
            'service_entry',
            sa.Column('published_ports', sa.JSON(), nullable=True),
        )


def downgrade() -> None:
    """Drop the three v0.6.0 capture columns.

    SQLite reaches drop_column via batch_alter_table, which rewrites
    the table in place.
    """
    with op.batch_alter_table('service_entry') as batch_op:
        batch_op.drop_column('published_ports')
        batch_op.drop_column('exposed_ports')
        batch_op.drop_column('networks')
