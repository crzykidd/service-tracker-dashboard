"""Canonical image reference: service_entry.image_ref (observed by register)

Revision ID: a2c6e8f1b345
Revises: e9b3d5f7a126
Create Date: 2026-11-21 15:00:00.000000

"""
import re
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'a2c6e8f1b345'
down_revision: Union[str, None] = 'e9b3d5f7a126'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_HUB = {"docker.io", "index.docker.io", "registry-1.docker.io"}
_NAME_RE = re.compile(r"^[a-z0-9]+(?:(?:[._]|__|-+)[a-z0-9]+)*$")
_TAG_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$")


def _canonical(registry, owner, name, tag):
    """Rebuild `registry/repository:tag` from the legacy split columns, or None when
    they are not sound (the old parser mangled ports, nested paths and digests; the
    next register of such an entry writes the right value)."""
    if not name or not _NAME_RE.match(name):
        return None
    registry = (registry or "").strip().lower()
    owner = (owner or "").strip()
    if registry:
        if registry in _HUB:
            registry = "docker.io"
        elif not ("." in registry or ":" in registry or registry == "localhost"):
            return None
        if not owner:
            return None
    else:
        registry = "docker.io"
        if "." in owner or ":" in owner or "@" in owner:
            return None  # a registry host that was split off as the owner
    if owner and not all(_NAME_RE.match(p) for p in owner.split("/")):
        return None
    if registry == "docker.io" and not owner:
        owner = "library"
    tag = (tag or "").strip() or "latest"
    if not _TAG_RE.match(tag):
        return None
    repository = f"{owner}/{name}" if owner else name
    return f"{registry}/{repository}:{tag}"


def upgrade() -> None:
    """Nullable observed string. Indexed: the update check (design §6.2) groups entries by
    reference. Not an FK, so the index is a lookup aid only."""
    with op.batch_alter_table('service_entry') as batch_op:
        batch_op.add_column(sa.Column('image_ref', sa.String(length=512), nullable=True))
        batch_op.create_index('ix_service_entry_image_ref', ['image_ref'], unique=False)

    bind = op.get_bind()
    rows = bind.execute(sa.text(
        "SELECT id, image_registry, image_owner, image_name, image_tag "
        "FROM service_entry WHERE image_name IS NOT NULL")).fetchall()
    for row in rows:
        ref = _canonical(row[1], row[2], row[3], row[4])
        if ref and len(ref) <= 512:
            bind.execute(sa.text("UPDATE service_entry SET image_ref = :r WHERE id = :i"),
                         {"r": ref, "i": row[0]})


def downgrade() -> None:
    with op.batch_alter_table('service_entry') as batch_op:
        batch_op.drop_index('ix_service_entry_image_ref')
        batch_op.drop_column('image_ref')
