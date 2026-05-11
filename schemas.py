"""pydantic schemas for the register API wire contract.

Source of truth for what /api/v1/register accepts. The legacy
/api/register compat shim does NOT route through these schemas —
it remaps legacy keys to canonical and calls upsert_service
directly, since legacy payloads may contain shapes the strict
schema would reject. See routes_api.py for the shared upsert path.

v0.6.0 removes /api/register and these schemas become the only
accepted shape.
"""

from typing import Optional

from pydantic import BaseModel, ConfigDict


class RegisterPayload(BaseModel):
    """Canonical /api/v1/register request body.

    Strict: unknown keys are rejected (extra="forbid"). `host` and
    `container_name` are required; everything else is optional.
    Optional bools accept JSON true/false directly; pydantic also
    coerces the common string variants ("true"/"false") if a
    producer sends them.
    """

    model_config = ConfigDict(extra="forbid")

    # Required
    host: str
    container_name: str

    # Optional — Docker / container identity
    container_id: Optional[str] = None
    stack_name: Optional[str] = None
    docker_status: Optional[str] = None
    started_at: Optional[str] = None
    timestamp: Optional[str] = None

    # Optional — URLs
    internalurl: Optional[str] = None
    externalurl: Optional[str] = None

    # Optional — health check toggles
    internal_health_check_enabled: Optional[bool] = None
    external_health_check_enabled: Optional[bool] = None

    # Optional — image metadata
    image_name: Optional[str] = None
    image_icon: Optional[str] = None

    # Optional — user-overridable fields (governed by
    # `register_field_ownership` setting at upsert time)
    group_name: Optional[str] = None
    sort_priority: Optional[int] = None
