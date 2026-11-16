"""container health check: one 'container' check row per notifier entry

Revision ID: c1d7a3e5f2b8
Revises: b8e4d6a2c1f9
Create Date: 2026-11-15 19:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'c1d7a3e5f2b8'
down_revision: Union[str, None] = 'b8e4d6a2c1f9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Data-only: give every notifier entry (soft-deleted included) its
    enabled Container check. No new columns, so no new index. Idempotent."""
    op.execute(
        "INSERT INTO health_check "
        "(service_entry_id, kind, name, check_type, mode, verify_tls, enabled, consecutive_failures) "
        "SELECT s.id, 'container', 'Container', 'docker', 'status', 1, 1, 0 "
        "FROM service_entry s "
        "WHERE s.source = 'notifier' "
        "AND NOT EXISTS (SELECT 1 FROM health_check h "
        "WHERE h.service_entry_id = s.id AND h.kind = 'container')"
    )


def downgrade() -> None:
    """Remove the container checks and their history. Results are deleted
    explicitly: SQLite foreign-key enforcement is off inside migrations, so
    the ON DELETE CASCADE would not fire."""
    op.execute(
        "DELETE FROM health_result WHERE check_id IN "
        "(SELECT id FROM health_check WHERE kind = 'container')"
    )
    op.execute("DELETE FROM health_check WHERE kind = 'container'")
