"""health checks as their own tables: health_check, health_result

Revision ID: b8e4d6a2c1f9
Revises: a7c3e9f15d28
Create Date: 2026-11-15 17:00:00.000000

"""
from datetime import datetime, timezone
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b8e4d6a2c1f9'
down_revision: Union[str, None] = 'a7c3e9f15d28'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _parse_update(value):
    """Legacy `*_update` strings are server-local 'YYYY-MM-DD HH:MM:SS'.
    Return naive UTC, or None when empty/unparsable."""
    if not value:
        return None
    try:
        local = datetime.strptime(str(value).strip(), '%Y-%m-%d %H:%M:%S')
        return local.astimezone(timezone.utc).replace(tzinfo=None)
    except (ValueError, OverflowError, OSError):
        return None


def _seed_state(status, update):
    """(last_ok, last_status_code, last_message, last_checked_at, failures)
    from a legacy status string + update string."""
    status = (status or '').strip()
    checked_at = _parse_update(update)
    if not status:
        return None, None, None, checked_at, 0
    if status.isdigit():
        code = int(status)
        if code < 400:
            return True, code, None, checked_at, 0
        return False, code, status[:255], checked_at, 1
    return False, None, status[:255], checked_at, 1


def upgrade() -> None:
    """Create health_check / health_result and give every existing entry an
    internal_url and an external_url check row copied from the legacy
    service_entry columns. The legacy columns stay (deprecated, kept for
    rollback)."""
    op.create_table(
        'health_check',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('service_entry_id', sa.Integer(), nullable=False),
        sa.Column('kind', sa.String(length=16), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=True),
        sa.Column('check_type', sa.String(length=8), server_default='http', nullable=False),
        sa.Column('target', sa.String(length=255), nullable=True),
        sa.Column('mode', sa.String(length=8), server_default='status', nullable=False),
        sa.Column('interval_seconds', sa.Integer(), nullable=True),
        sa.Column('timeout_seconds', sa.Integer(), nullable=True),
        sa.Column('verify_tls', sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column('enabled', sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column('last_ok', sa.Boolean(), nullable=True),
        sa.Column('last_checked_at', sa.DateTime(), nullable=True),
        sa.Column('last_status_code', sa.Integer(), nullable=True),
        sa.Column('last_latency_ms', sa.Integer(), nullable=True),
        sa.Column('last_message', sa.String(length=255), nullable=True),
        sa.Column('consecutive_failures', sa.Integer(), server_default='0', nullable=False),
        sa.ForeignKeyConstraint(['service_entry_id'], ['service_entry.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_health_check_service_entry_id', 'health_check', ['service_entry_id'])

    op.create_table(
        'health_result',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('check_id', sa.Integer(), nullable=False),
        sa.Column('ts', sa.DateTime(), nullable=False),
        sa.Column('ts_end', sa.DateTime(), nullable=True),
        sa.Column('samples', sa.Integer(), server_default='1', nullable=False),
        sa.Column('ok', sa.Boolean(), nullable=False),
        sa.Column('latency_ms', sa.Float(), nullable=True),
        sa.Column('latency_max_ms', sa.Integer(), nullable=True),
        sa.Column('status_code', sa.Integer(), nullable=True),
        sa.Column('message', sa.String(length=255), nullable=True),
        sa.ForeignKeyConstraint(['check_id'], ['health_check.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    # Composite index; its leading column also serves the check_id FK.
    op.create_index('ix_health_result_check_id_ts', 'health_result', ['check_id', 'ts'])

    bind = op.get_bind()
    meta = sa.MetaData()
    entry = sa.Table('service_entry', meta, autoload_with=bind)
    check = sa.Table('health_check', meta, autoload_with=bind)

    rows = bind.execute(sa.select(
        entry.c.id,
        entry.c.internal_health_check_enabled,
        entry.c.internal_health_check_status,
        entry.c.internal_health_check_update,
        entry.c.external_health_check_enabled,
        entry.c.external_health_check_status,
        entry.c.external_health_check_update,
        entry.c.health_check_timeout,
        entry.c.health_check_verify_tls,
    )).fetchall()

    inserts = []
    for r in rows:
        for kind, name, enabled, status, update in (
            ('internal_url', 'Internal URL', r.internal_health_check_enabled,
             r.internal_health_check_status, r.internal_health_check_update),
            ('external_url', 'External URL', r.external_health_check_enabled,
             r.external_health_check_status, r.external_health_check_update),
        ):
            ok, code, message, checked_at, failures = _seed_state(status, update)
            inserts.append({
                'service_entry_id': r.id,
                'kind': kind,
                'name': name,
                'check_type': 'http',
                'mode': 'status',
                'timeout_seconds': r.health_check_timeout,
                'verify_tls': r.health_check_verify_tls is not False,
                'enabled': bool(enabled),
                'last_ok': ok,
                'last_checked_at': checked_at,
                'last_status_code': code,
                'last_message': message,
                'consecutive_failures': failures,
            })
    if inserts:
        op.bulk_insert(check, inserts)


def downgrade() -> None:
    """Drop both tables. The legacy `*_enabled` columns are no longer written
    by this version, so copy the current enabled flags back first."""
    bind = op.get_bind()
    for kind, column in (
        ('internal_url', 'internal_health_check_enabled'),
        ('external_url', 'external_health_check_enabled'),
    ):
        bind.execute(sa.text(
            f"UPDATE service_entry SET {column} = ("
            "SELECT hc.enabled FROM health_check hc "
            "WHERE hc.service_entry_id = service_entry.id AND hc.kind = :kind LIMIT 1) "
            "WHERE EXISTS (SELECT 1 FROM health_check hc "
            "WHERE hc.service_entry_id = service_entry.id AND hc.kind = :kind)"
        ), {'kind': kind})
    # Timeout / verify-TLS: the two URL checks share them; take the internal row.
    bind.execute(sa.text(
        "UPDATE service_entry SET "
        "health_check_timeout = (SELECT hc.timeout_seconds FROM health_check hc "
        "WHERE hc.service_entry_id = service_entry.id AND hc.kind = 'internal_url' LIMIT 1), "
        "health_check_verify_tls = COALESCE((SELECT hc.verify_tls FROM health_check hc "
        "WHERE hc.service_entry_id = service_entry.id AND hc.kind = 'internal_url' LIMIT 1), "
        "health_check_verify_tls) "
        "WHERE EXISTS (SELECT 1 FROM health_check hc "
        "WHERE hc.service_entry_id = service_entry.id AND hc.kind = 'internal_url')"
    ))
    op.drop_index('ix_health_result_check_id_ts', table_name='health_result')
    op.drop_table('health_result')
    op.drop_index('ix_health_check_service_entry_id', table_name='health_check')
    op.drop_table('health_check')
