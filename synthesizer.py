"""Exposure URL synthesizer (v0.6.0).

Interpreters describe facts ("Traefik sees hostname X on this
container"). The dashboard's `internalurl` and `externalurl` are
conclusions ("this is the URL we'll link from the tile"). The
synthesizer is the translation step.

Inputs per service:
- `ServiceExposure` rows attached to the service.
- The service's `host` (for per-host direction overrides).
- The operator's per-interpreter direction settings (see
  `settings_store.py`).
- The service's existing `internalurl` / `externalurl` and the
  `_source` columns that record who last wrote them.

Outputs (mutated onto the `ServiceEntry`):
- `internalurl` / `internalurl_source`
- `externalurl` / `externalurl_source`

Provenance rules. `_source` is one of "ui_edit", "explicit_label",
"synthesized", or NULL. Ordering (later beats earlier):
  NULL < synthesized < explicit_label < ui_edit

The synthesizer only ever writes "synthesized". It never overwrites
"ui_edit" or "explicit_label" values. It clears synthesized values
when no candidate remains (so removing Traefik labels makes the URL
disappear).

The register handler — not the synthesizer — is responsible for
setting "explicit_label" when the payload carries an
`internalurl` / `externalurl` field. The UI edit handler in
routes_dashboard.py sets "ui_edit". The synthesizer is downstream of
both.

Algorithm (per direction, internal vs. external):
1. Map each `ServiceExposure` row to a direction using
   `settings_store.direction_for(layer, host)`.
2. Build candidate URLs for the relevant direction:
   `{scheme}://{hostname}{path_prefix}/` where scheme = "https" if
   tls else "http". Rows without a hostname are skipped.
3. Pick a winner via tiebreaker: TLS > non-TLS, no path prefix > path
   prefix, lower layer-name alphabetically last as a stable
   tiebreaker.
4. If the existing `_source` is "ui_edit" or "explicit_label", do
   nothing. Otherwise write the winner (or clear if no candidates and
   the previous source was "synthesized" or NULL).
"""

from typing import Iterable, List, Optional, Tuple

from extensions import db
from models import ServiceEntry, ServiceExposure
import settings_store

SOURCE_UI_EDIT = "ui_edit"
SOURCE_EXPLICIT_LABEL = "explicit_label"
SOURCE_SYNTHESIZED = "synthesized"

# Order: higher index = stronger. The synthesizer only ever writes
# SOURCE_SYNTHESIZED, so it must not overwrite anything at this index
# or higher: (explicit_label, ui_edit).
_SOURCE_RANK = {
    None: 0,
    SOURCE_SYNTHESIZED: 1,
    SOURCE_EXPLICIT_LABEL: 2,
    SOURCE_UI_EDIT: 3,
}


def _build_url(exposure: ServiceExposure) -> Optional[str]:
    """Construct a clickable URL from one exposure row.

    Returns None when the row is unusable (no hostname). Path prefix
    is appended verbatim with a single trailing slash so the result
    is a directory-ish URL; if the operator wants something else they
    can edit it in the UI.
    """
    if not exposure.hostname:
        return None
    scheme = "https" if exposure.tls else "http"
    path = (exposure.path_prefix or "").strip()
    if path and not path.startswith("/"):
        path = "/" + path
    path = path.rstrip("/")
    return f"{scheme}://{exposure.hostname}{path}/"


def _tiebreak_key(exposure: ServiceExposure) -> Tuple[int, int, str]:
    """Order candidates so the first one is the winner.

    Sort key (ascending):
      - tls=False before tls=True flipped: we want TLS first, so use
        `0 if tls else 1`.
      - empty path_prefix before non-empty: `0 if not path else 1`.
      - layer name ascending (stable, deterministic across runs).
    """
    tls_rank = 0 if exposure.tls else 1
    path_rank = 0 if not (exposure.path_prefix or "").strip() else 1
    return (tls_rank, path_rank, (exposure.layer or "").lower())


def _winner_for_direction(
    rows: Iterable[ServiceExposure],
    direction: str,
    host: str,
) -> Optional[ServiceExposure]:
    """Return the highest-priority exposure row whose layer maps to
    `direction` for this host, or None if no candidate exists or no
    row has a usable hostname."""
    candidates: List[ServiceExposure] = []
    for row in rows:
        if settings_store.direction_for(row.layer, host) != direction:
            continue
        if not row.hostname:
            continue
        candidates.append(row)
    if not candidates:
        return None
    candidates.sort(key=_tiebreak_key)
    return candidates[0]


def _apply_direction(entry: ServiceEntry, direction: str, winner: Optional[ServiceExposure]) -> None:
    """Mutate the `internalurl` / `externalurl` + `_source` columns
    for one direction, respecting provenance ordering.

    - If existing `_source` is ui_edit / explicit_label, do nothing.
    - Otherwise write the synthesized URL or clear it.
    """
    if direction == "internal":
        current_source = entry.internalurl_source
    else:
        current_source = entry.externalurl_source

    if _SOURCE_RANK.get(current_source, 0) > _SOURCE_RANK[SOURCE_SYNTHESIZED]:
        return

    new_url = _build_url(winner) if winner is not None else None

    if direction == "internal":
        entry.internalurl = new_url
        entry.internalurl_source = SOURCE_SYNTHESIZED if new_url else None
    else:
        entry.externalurl = new_url
        entry.externalurl_source = SOURCE_SYNTHESIZED if new_url else None


def synthesize_for_entry(entry: ServiceEntry) -> None:
    """Recompute `internalurl` / `externalurl` for one service.

    Caller is responsible for committing. Idempotent: running it
    repeatedly with the same inputs produces the same output. Cheap
    enough to call on every register.
    """
    rows = list(entry.exposures or [])
    host = entry.host or ""
    _apply_direction(entry, "internal", _winner_for_direction(rows, "internal", host))
    _apply_direction(entry, "external", _winner_for_direction(rows, "external", host))


def recompute_all() -> int:
    """Recompute synthesized URLs for every service.

    Triggered when the operator changes per-interpreter direction
    settings (a layer flipping from "neither" to "internal" needs
    every Traefik-tagged row's URL recomputed). Iterates all services
    — at homelab scale (~50 services) this runs in milliseconds.

    Caller is responsible for committing. Returns the number of
    services touched (i.e. queried — not necessarily mutated).
    """
    entries = ServiceEntry.query.all()
    for entry in entries:
        synthesize_for_entry(entry)
    return len(entries)


def replace_exposures(entry: ServiceEntry, observations) -> None:
    """Wholesale-replace this service's `ServiceExposure` rows from a
    list of pydantic ExposureObservation instances or dicts.

    Pass `None` and the function does nothing (the register handler
    is expected to distinguish "no update" from "empty list" before
    calling — None means the producer didn't say, so we leave the
    previous state alone). Pass `[]` to clear all rows for this
    service.

    Caller is responsible for committing.
    """
    if observations is None:
        return

    from datetime import datetime

    ServiceExposure.query.filter_by(service_entry_id=entry.id).delete(synchronize_session=False)

    now = datetime.utcnow()
    for obs in observations:
        if hasattr(obs, "model_dump"):
            data = obs.model_dump()
        else:
            data = dict(obs)
        layer = data.get("layer")
        if not layer:
            continue
        db.session.add(
            ServiceExposure(
                service_entry_id=entry.id,
                layer=layer,
                hostname=data.get("hostname"),
                tls=data.get("tls"),
                path_prefix=data.get("path_prefix"),
                auth=data.get("auth"),
                details=data.get("details"),
                last_updated=now,
            )
        )
