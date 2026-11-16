"""Admin API keys for the management API (v0.8.0, PRD 14.2).

Key format: `std_<prefix>_<secret>`. The prefix is 8 hex characters (display
and lookup); the secret is `secrets.token_urlsafe(32)`. Only the SHA-256 hex
of the full key is stored: the key is high-entropy, so a slow KDF would add
latency and no security. The full key exists only in the creation response.
"""

import hashlib
import hmac
import secrets
from datetime import datetime

from extensions import db
from models import ApiKey

KEY_PREFIX = "std"
SCOPE_READ = "read"
SCOPE_WRITE = "write"
SCOPES = (SCOPE_READ, SCOPE_WRITE)
NAME_MAX = 64


def _hash(full_key):
    return hashlib.sha256(full_key.encode("utf-8")).hexdigest()


def generate_key():
    """Return `(full_key, prefix, key_hash)` for a fresh key."""
    prefix = secrets.token_hex(4)
    full_key = f"{KEY_PREFIX}_{prefix}_{secrets.token_urlsafe(32)}"
    return full_key, prefix, _hash(full_key)


def verify(presented):
    """Return the active ApiKey for a presented key, or None.

    Unknown prefix, wrong secret and revoked keys all return None.
    """
    if not presented or not isinstance(presented, str):
        return None
    parts = presented.split("_", 2)
    if len(parts) != 3 or parts[0] != KEY_PREFIX or not parts[1] or not parts[2]:
        return None
    presented_hash = _hash(presented)
    for key in ApiKey.query.filter_by(prefix=parts[1]).all():
        if hmac.compare_digest(key.key_hash, presented_hash) and key.revoked_at is None:
            return key
    return None


def scope_allows(key_scope, required):
    """`write` includes `read`."""
    if required == SCOPE_READ:
        return key_scope in (SCOPE_READ, SCOPE_WRITE)
    return key_scope == required


def validate_name(name):
    """Return an error string for an unusable key name, else None."""
    if not name:
        return "A key name is required."
    if len(name) > NAME_MAX:
        return f"Key names are at most {NAME_MAX} characters."
    if ApiKey.query.filter_by(name=name).first():
        return f"A key named '{name}' already exists (revoked keys keep their name)."
    return None


def create_key(name, scope, created_by=None):
    """Create and commit a key. Returns `(ApiKey, full_key)`. Caller validates."""
    full_key, prefix, key_hash = generate_key()
    key = ApiKey(name=name, prefix=prefix, key_hash=key_hash, scope=scope,
                 created_at=datetime.utcnow(), created_by=created_by)
    db.session.add(key)
    db.session.commit()
    return key, full_key


def revoke_key(key):
    if key.revoked_at is None:
        key.revoked_at = datetime.utcnow()
        db.session.commit()
