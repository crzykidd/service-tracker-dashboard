"""Container image reference parser (distribution reference grammar).

`parse(ref)` is pure and stdlib-only. It never raises: anything that is not a
valid reference returns None. The result is normalised the way a Docker client
resolves a name:

- the first path component is a registry when it contains "." or ":" or is
  "localhost" (and there is more than one component); otherwise the registry is
  Docker Hub, `docker.io`;
- a one-component Docker Hub name lives under `library/`;
- `index.docker.io` and `registry-1.docker.io` normalise to `docker.io`;
- the tag follows the last ":" of the last path component, and defaults to
  `latest` when there is neither a tag nor a digest;
- `@algo:hex` is a digest.
"""

import re
from dataclasses import dataclass

DOCKER_HUB = "docker.io"
_HUB_ALIASES = frozenset({"docker.io", "index.docker.io", "registry-1.docker.io"})

_COMPONENT_RE = re.compile(r"^[a-z0-9]+(?:(?:[._]|__|-+)[a-z0-9]+)*$")
_TAG_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$")
_DIGEST_RE = re.compile(
    r"^[A-Za-z][A-Za-z0-9]*(?:[-_+.][A-Za-z][A-Za-z0-9]*)*:[0-9a-fA-F]{32,}$")
_HOST_RE = re.compile(r"^[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?(?::[0-9]{1,5})?$")
_MAX_LEN = 512


@dataclass(frozen=True)
class ImageRef:
    registry: str            # lowercase host[:port]; "docker.io" for Docker Hub
    repository: str          # full path, e.g. "library/nginx" or "org/team/app"
    tag: str | None          # None for a digest-only reference
    digest: str | None

    @property
    def is_docker_hub(self) -> bool:
        return self.registry == DOCKER_HUB

    @property
    def owner(self) -> str | None:
        """Everything before the last path component (None for a bare name)."""
        head, sep, _ = self.repository.rpartition("/")
        return head if sep else None

    @property
    def name(self) -> str:
        """The last path component."""
        return self.repository.rpartition("/")[2]

    @property
    def canonical(self) -> str:
        """`registry/repository:tag`, or `registry/repository@digest` with no tag."""
        base = f"{self.registry}/{self.repository}"
        if self.tag:
            return f"{base}:{self.tag}"
        return f"{base}@{self.digest}"


def parse(ref) -> ImageRef | None:
    """Parse an image reference string; None when it is empty or malformed."""
    try:
        return _parse(ref)
    except Exception:  # defensive: the parser must never break a register call
        return None


def _parse(ref) -> ImageRef | None:
    if not isinstance(ref, str):
        return None
    ref = ref.strip()
    if not ref or len(ref) > _MAX_LEN or any(c.isspace() for c in ref):
        return None

    name, at, digest = ref.partition("@")
    if at:
        if not _DIGEST_RE.match(digest):
            return None
    else:
        digest = None
    if not name:
        return None

    parts = name.split("/")
    first = parts[0]
    registry = None
    if len(parts) > 1 and ("." in first or ":" in first or first == "localhost"):
        registry = first.lower()
        parts = parts[1:]
        if not _HOST_RE.match(registry):
            return None
        if registry.partition(":")[0] in _HUB_ALIASES:
            registry = DOCKER_HUB if ":" not in registry else registry
    else:
        registry = DOCKER_HUB

    last, colon, tag = parts[-1].rpartition(":")
    if colon:
        parts[-1] = last
        if not _TAG_RE.match(tag):
            return None
    else:
        tag = None
    if not parts[-1] or not all(_COMPONENT_RE.match(p) for p in parts):
        return None

    if registry == DOCKER_HUB and len(parts) == 1:
        parts = ["library", parts[0]]
    if not tag and not digest:
        tag = "latest"
    return ImageRef(registry=registry, repository="/".join(parts), tag=tag, digest=digest)
