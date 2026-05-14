"""pydantic schemas for the register API wire contract.

Source of truth for what /api/v1/register accepts. From v0.6.0 onward
this is the only register surface — the legacy /api/register compat
shim has been removed.
"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict


class NetworkMembership(BaseModel):
    """One Docker network the container is attached to.

    Names only — IPs and gateway info are SSH/debugger territory, not
    dashboard territory. Aliases are captured because they reveal
    compose service names, which future logical-service-identity work
    will want.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    aliases: List[str] = []


class PublishedPort(BaseModel):
    """One host-to-container port mapping (compose `ports:`)."""

    model_config = ConfigDict(extra="forbid")

    container_port: int
    protocol: str
    host_ip: str
    host_port: int


class ExposureObservation(BaseModel):
    """One interpreter's read of how a container is exposed.

    Produced by the notifier's YAML interpreters (v0.4.0+). Each
    interpreter that recognizes a container emits one observation
    here; the same container can be seen by multiple interpreters
    (e.g. Traefik + Dockflare on the same hostname).

    `layer` is the interpreter identifier — lowercase, underscore-
    separated by convention. STD's synthesizer maps layer to
    direction (internal/external/neither) per operator settings.
    """

    model_config = ConfigDict(extra="forbid")

    layer: str
    hostname: Optional[str] = None
    tls: Optional[bool] = None
    path_prefix: Optional[str] = None
    auth: Optional[str] = None
    details: Optional[Dict[str, Any]] = None


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

    # Optional — observed container facts (v0.6.0+). Pure observation,
    # overwritten on every register. Notifier v0.3.2+ populates these.
    networks: Optional[List[NetworkMembership]] = None
    exposed_ports: Optional[List[str]] = None
    published_ports: Optional[List[PublishedPort]] = None

    # Optional — interpreter outputs (v0.6.0 — exposure synthesis).
    # Notifier v0.4.0+ runs YAML interpreters and emits one entry per
    # interpreter that recognizes the container. None means "no
    # update — leave existing rows alone" (used by pre-v0.4.0
    # notifiers and operators who turn interpreters off). [] means
    # "this container has no interpreter matches — clear all
    # existing rows."
    exposure_observations: Optional[List[ExposureObservation]] = None
