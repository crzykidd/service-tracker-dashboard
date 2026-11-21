"""Link a container image to its repository page (PRD 13.7).

`image_ref_repo_url()` derives it from the canonical reference (`image_ref`, parsed by
`image_ref.parse`); `image_repo_url()` is the fallback over the stored split fields
(`image_registry`, `image_owner`, `image_name`) for entries without a reference yet. It returns a URL only for
registries whose page form is well known and None for everything else: an
unknown, private or self-hosted registry never gets a guessed link.
`effective_repo_url()` applies the operator override on top.
"""

from urllib.parse import quote

from image_ref import parse as parse_ref

DOCKER_HUB_HOSTS = frozenset({"", "docker.io", "index.docker.io", "registry-1.docker.io"})


def _q(value):
    # Keep "/" (nested image paths) but quote everything else.
    return quote(value, safe="/")


def _by_repository(registry, repository):
    """The page for `registry` + full repository path ("org/team/app"), or None."""
    registry = (registry or "").strip().lower()
    repository = (repository or "").strip().strip("/")
    if not repository:
        return None
    owner, sep, name = repository.rpartition("/")

    if registry in DOCKER_HUB_HOSTS:
        if not sep or owner == "library":
            return f"https://hub.docker.com/_/{_q(name)}"
        if "/" in owner:
            return None  # Docker Hub has no nested namespaces
        return f"https://hub.docker.com/r/{_q(owner)}/{_q(name)}"

    if not sep:
        return None
    if registry == "ghcr.io":
        # /users/<owner>/ also redirects correctly for organisations. A nested path
        # ("org/team/app") is the package "team/app" under "org".
        top, _, package = repository.partition("/")
        return f"https://github.com/users/{_q(top)}/packages/container/package/{quote(package, safe='')}"
    if registry == "quay.io":
        return f"https://quay.io/repository/{_q(repository)}"
    if registry == "lscr.io" and owner.lower() == "linuxserver":
        return f"https://github.com/linuxserver/docker-{_q(name)}"
    return None


def image_repo_url(registry, owner, name):
    """The image's repository page, or None when it can't be derived reliably.

    `owner` is everything before the last path component ("org/team"), `name` the last.
    """
    registry = (registry or "").strip().lower()
    owner = (owner or "").strip().strip("/")
    name = (name or "").strip().strip("/")
    if not name:
        return None
    if not registry and ("." in owner or ":" in owner):
        return None  # "ghcr.io/x" parsed as owner/name: a registry host, not a Hub user
    return _by_repository(registry, f"{owner}/{name}" if owner else name)


def image_ref_repo_url(image_ref):
    """The page for a canonical reference string (`service_entry.image_ref`), or None."""
    ref = parse_ref(image_ref)
    if ref is None:
        return None
    return _by_repository(ref.registry, ref.repository)


def effective_repo_url(entry):
    """The operator override when set, else the derived URL, else None."""
    override = (getattr(entry, "image_repo_url", None) or "").strip()
    if override:
        return override
    if getattr(entry, "image_ref", None):
        return image_ref_repo_url(entry.image_ref)
    return image_repo_url(entry.image_registry, entry.image_owner, entry.image_name)


def valid_repo_override(value):
    """True for an http(s) URL with a host (the override's only format rule)."""
    from urllib.parse import urlparse

    try:
        parsed = urlparse(value)
    except ValueError:
        return False
    return parsed.scheme in ("http", "https") and bool(parsed.netloc) and not any(c.isspace() for c in value)
