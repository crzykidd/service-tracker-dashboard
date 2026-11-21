"""Link a container image to its repository page (PRD 13.7).

`image_repo_url()` is a pure function over the stored image fields
(`image_registry`, `image_owner`, `image_name`). It returns a URL only for
registries whose page form is well known and None for everything else: an
unknown, private or self-hosted registry never gets a guessed link.
`effective_repo_url()` applies the operator override on top.
"""

from urllib.parse import quote

DOCKER_HUB_HOSTS = frozenset({"", "docker.io", "index.docker.io", "registry-1.docker.io"})


def _q(value):
    # Keep "/" (nested image paths) but quote everything else.
    return quote(value, safe="/")


def image_repo_url(registry, owner, name):
    """The image's repository page, or None when it can't be derived reliably."""
    registry = (registry or "").strip().lower()
    owner = (owner or "").strip().strip("/")
    name = (name or "").strip().strip("/")
    if not name:
        return None

    if registry in DOCKER_HUB_HOSTS:
        if not registry and ("." in owner or ":" in owner):
            return None  # "ghcr.io/x" parsed as owner/name: a registry host, not a Hub user
        if owner in ("", "library"):
            return f"https://hub.docker.com/_/{_q(name)}"
        return f"https://hub.docker.com/r/{_q(owner)}/{_q(name)}"

    if not owner:
        return None
    if registry == "ghcr.io":
        # /users/<owner>/ also redirects correctly for organisations.
        return f"https://github.com/users/{_q(owner)}/packages/container/package/{_q(name)}"
    if registry == "quay.io":
        return f"https://quay.io/repository/{_q(owner)}/{_q(name)}"
    if registry == "lscr.io" and owner.lower() == "linuxserver":
        return f"https://github.com/linuxserver/docker-{_q(name)}"
    return None


def effective_repo_url(entry):
    """The operator override when set, else the derived URL, else None."""
    override = (getattr(entry, "image_repo_url", None) or "").strip()
    if override:
        return override
    return image_repo_url(entry.image_registry, entry.image_owner, entry.image_name)


def valid_repo_override(value):
    """True for an http(s) URL with a host (the override's only format rule)."""
    from urllib.parse import urlparse

    try:
        parsed = urlparse(value)
    except ValueError:
        return False
    return parsed.scheme in ("http", "https") and bool(parsed.netloc) and not any(c.isspace() for c in value)
