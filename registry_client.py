"""A small OCI distribution v2 client for the image update check (design 4.1, 4.4).

Every registry STD cares about (Docker Hub, GHCR, quay.io, lscr.io, gcr.io, GitLab, Harbor,
Gitea, plain `registry:2`) speaks the same API, so there is one client. The only special
cases are the Docker Hub API host and the Hub rule that a manifest GET counts as a pull
while a HEAD does not.

What it does:

* `head_manifest(registry, repository, reference)` -> the content digest the registry
  advertises for a tag. HEAD only, with all four manifest media types (a multi-arch tag
  answers with its index digest, which is what `docker pull` records in `RepoDigests`).
* `list_tags(registry, repository)` -> every tag, following `Link` pagination, at most
  `MAX_TAG_PAGES` pages.

Authentication is the anonymous Bearer challenge flow, read from `WWW-Authenticate` (no
realm is hardcoded). There are no credentials and no plain HTTP: this is HTTPS only.

Errors are `RegistryError` with a short, fixed message. Raw exception text is never put in
an error (it ends up stored and shown). A `429` raises `RateLimited` and pauses that
registry for the rest of this client's life, which is one check run.

No database, no Flask: the caller supplies the transport (`http`) in tests.
"""

import hashlib
import logging
import re
import threading
import time
from urllib.parse import parse_qsl, urljoin, urlparse

import requests

logger = logging.getLogger(__name__)

DOCKER_HUB = "docker.io"
DOCKER_HUB_API_HOST = "registry-1.docker.io"

# The four manifest media types. A test pins this header: with fewer, Docker Hub answers a
# multi-arch tag with a platform manifest (or 404 for an OCI index) and every multi-arch
# image would look "changed" forever.
MANIFEST_ACCEPT = ", ".join((
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
    "application/vnd.oci.image.manifest.v1+json",
    "application/vnd.docker.distribution.manifest.v2+json",
))

CONNECT_TIMEOUT = 5
READ_TIMEOUT = 10
TAG_PAGE_SIZE = 1000
MAX_TAG_PAGES = 10
MAX_REDIRECTS = 3
MAX_PER_HOST = 2                    # requests in flight per registry host
TOKEN_MARGIN_SECONDS = 10
DEFAULT_TOKEN_SECONDS = 60
DEFAULT_RETRY_AFTER = 300           # a 429 without a usable Retry-After
MAX_RETRY_AFTER = 24 * 3600
MAX_MANIFEST_BYTES = 4 * 1024 * 1024

_DIGEST_RE = re.compile(r"^[a-z0-9]+(?:[+._-][a-z0-9]+)*:[0-9a-f]{32,}$")
_CHALLENGE_RE = re.compile(r'(\w+)\s*=\s*"([^"]*)"')

# Fixed messages: these are what gets stored on the reference row.
ERR_UNREACHABLE = "registry unreachable"
ERR_LOGIN = "registry asked for a login"
ERR_NOT_FOUND = "image or tag not found in the registry"
ERR_RATE_LIMITED = "registry rate limited the check"
ERR_UNEXPECTED = "unexpected answer from the registry"
ERR_NO_DIGEST = "registry returned no digest"


class RegistryError(Exception):
    """A failed registry call. `message` is a short fixed string, safe to store and show."""

    def __init__(self, message):
        super().__init__(message)
        self.message = message


class RateLimited(RegistryError):
    """HTTP 429. `retry_after` is in seconds."""

    def __init__(self, retry_after):
        super().__init__(ERR_RATE_LIMITED)
        self.retry_after = retry_after


def api_host(registry):
    """The host to talk to for a normalised registry name (`docker.io` -> the Hub API host)."""
    return DOCKER_HUB_API_HOST if registry == DOCKER_HUB else registry


def _default_http(method, url, headers=None, params=None, timeout=None, allow_redirects=False):
    return requests.request(method, url, headers=headers, params=params, timeout=timeout,
                            allow_redirects=allow_redirects)


def parse_retry_after(value, now=None):
    """Seconds to wait from a Retry-After header (delta-seconds or an HTTP date); the
    default when absent or unreadable, capped at a day."""
    if value:
        value = str(value).strip()
        try:
            return max(1, min(int(float(value)), MAX_RETRY_AFTER))
        except ValueError:
            try:
                from email.utils import parsedate_to_datetime
                when = parsedate_to_datetime(value)
                delta = when.timestamp() - (now if now is not None else time.time())
                return max(1, min(int(delta), MAX_RETRY_AFTER))
            except (TypeError, ValueError, OverflowError):
                pass
    return DEFAULT_RETRY_AFTER


def parse_challenge(header):
    """`WWW-Authenticate` -> (scheme lower-case, {param: value}); (None, {}) when empty."""
    if not header:
        return None, {}
    scheme, _, rest = header.strip().partition(" ")
    return scheme.lower(), dict(_CHALLENGE_RE.findall(rest))


class RegistryClient:
    """One instance per check run. Thread-safe: the token cache, the pause table and the
    per-host semaphores are guarded."""

    def __init__(self, user_agent="service-tracker-dashboard/unknown", http=None, now=time.time):
        self.user_agent = user_agent
        self._http = http or _default_http
        self._now = now
        self._lock = threading.Lock()
        self._tokens = {}            # (host, scope) -> (token, expires_at)
        self._paused = {}            # api host -> epoch seconds the pause ends
        self._sems = {}              # api host -> BoundedSemaphore

    # -- state ------------------------------------------------------------------------

    def paused_until(self, registry):
        """Epoch seconds until which `registry` is paused after a 429, or 0."""
        with self._lock:
            return self._paused.get(api_host(registry), 0)

    def _pause(self, host, seconds):
        with self._lock:
            until = self._now() + seconds
            self._paused[host] = max(self._paused.get(host, 0), until)

    def _sem(self, host):
        with self._lock:
            sem = self._sems.get(host)
            if sem is None:
                sem = self._sems[host] = threading.BoundedSemaphore(MAX_PER_HOST)
            return sem

    def _cached_token(self, host, scope):
        with self._lock:
            hit = self._tokens.get((host, scope))
        if hit and hit[1] > self._now():
            return hit[0]
        return None

    # -- transport --------------------------------------------------------------------

    def _send(self, method, url, headers, params=None):
        """One HTTP call with the timeouts and one retry on a connection failure."""
        headers = {"User-Agent": self.user_agent, **headers}
        last = None
        for _ in range(2):
            try:
                return self._http(method, url, headers=headers, params=params,
                                  timeout=(CONNECT_TIMEOUT, READ_TIMEOUT), allow_redirects=False)
            except requests.RequestException as exc:
                last = exc
        logger.debug("registry request failed: %s", last.__class__.__name__)
        raise RegistryError(ERR_UNREACHABLE)

    def _token(self, challenge_params, host, default_scope):
        """Anonymous token for a Bearer challenge. The realm must be https."""
        realm = challenge_params.get("realm") or ""
        if urlparse(realm).scheme != "https":
            raise RegistryError(ERR_UNEXPECTED)
        scope = challenge_params.get("scope") or default_scope
        query = {}
        if challenge_params.get("service"):
            query["service"] = challenge_params["service"]
        if scope:
            query["scope"] = scope
        resp = self._send("GET", realm, {"Accept": "application/json"}, params=query or None)
        if resp.status_code == 429:
            seconds = parse_retry_after(resp.headers.get("Retry-After"), self._now())
            self._pause(host, seconds)
            raise RateLimited(seconds)
        if resp.status_code in (401, 403):
            raise RegistryError(ERR_LOGIN)
        if resp.status_code != 200:
            raise RegistryError(ERR_UNEXPECTED)
        try:
            body = resp.json()
            token = body.get("token") or body.get("access_token")
            expires = body.get("expires_in", DEFAULT_TOKEN_SECONDS)
            expires = float(expires) if not isinstance(expires, bool) else DEFAULT_TOKEN_SECONDS
        except (ValueError, AttributeError, TypeError):
            raise RegistryError(ERR_UNEXPECTED) from None
        if not isinstance(token, str) or not token:
            raise RegistryError(ERR_UNEXPECTED)
        with self._lock:
            # Keyed by the scope this client asks for, so the next request for the same
            # repository finds it even if the registry words the granted scope differently.
            self._tokens[(host, default_scope)] = (
                token, self._now() + max(expires - TOKEN_MARGIN_SECONDS, 0))
        return token

    def _request(self, method, registry, repository, path, headers=None, params=None,
                 follow_redirects=False):
        """A v2 API call to `registry` with the Bearer flow. Returns the final response
        (any status); raises RateLimited / RegistryError on transport trouble, a 429, or a
        login demand."""
        host = api_host(registry)
        until = self.paused_until(registry)
        if until > self._now():
            raise RateLimited(max(1, int(until - self._now())))
        scope = f"repository:{repository}:pull"
        url = f"https://{host}{path}"
        base_headers = dict(headers or {})
        token = self._cached_token(host, scope)
        for attempt in range(2):
            h = dict(base_headers)
            if token:
                h["Authorization"] = f"Bearer {token}"
            with self._sem(host):
                resp = self._follow(method, url, h, params, follow_redirects, host)
            if resp.status_code == 429:
                seconds = parse_retry_after(resp.headers.get("Retry-After"), self._now())
                self._pause(host, seconds)
                raise RateLimited(seconds)
            if resp.status_code != 401:
                return resp
            scheme, challenge = parse_challenge(resp.headers.get("WWW-Authenticate"))
            if attempt == 1 or scheme != "bearer":
                raise RegistryError(ERR_LOGIN)
            token = self._token(challenge, host, scope)
        raise RegistryError(ERR_LOGIN)  # pragma: no cover - the loop returns or raises

    def _follow(self, method, url, headers, params, follow_redirects, host):
        """Send, and (GET only) follow a few redirects. The Authorization header is dropped
        when a redirect leaves the registry host: a token is never forwarded."""
        resp = self._send(method, url, headers, params)
        hops = 0
        while follow_redirects and resp.status_code in (301, 302, 303, 307, 308) and hops < MAX_REDIRECTS:
            location = resp.headers.get("Location")
            if not location:
                break
            url = urljoin(url, location)
            if urlparse(url).scheme != "https":
                raise RegistryError(ERR_UNEXPECTED)
            h = dict(headers)
            if urlparse(url).hostname != host:
                h.pop("Authorization", None)
            resp = self._send(method, url, h, None)
            hops += 1
        return resp

    # -- API --------------------------------------------------------------------------

    def head_manifest(self, registry, repository, reference):
        """The content digest the registry has for `reference` (a tag), as `sha256:<hex>`.

        HEAD with the four media types. When HEAD carries no `Docker-Content-Digest`, fall
        back to a GET and hash the body, except on Docker Hub where a GET counts as a pull."""
        path = f"/v2/{repository}/manifests/{reference}"
        accept = {"Accept": MANIFEST_ACCEPT}
        resp = self._request("HEAD", registry, repository, path, accept)
        self._raise_for_status(resp)
        digest = (resp.headers.get("Docker-Content-Digest") or "").strip().lower()
        if digest:
            if not _DIGEST_RE.match(digest):
                raise RegistryError(ERR_UNEXPECTED)
            return digest
        if registry == DOCKER_HUB:
            raise RegistryError(ERR_NO_DIGEST)
        resp = self._request("GET", registry, repository, path, accept)
        self._raise_for_status(resp)
        body = resp.content or b""
        if not body or len(body) > MAX_MANIFEST_BYTES:
            raise RegistryError(ERR_NO_DIGEST)
        return "sha256:" + hashlib.sha256(body).hexdigest()

    def list_tags(self, registry, repository):
        """`(tags, truncated)`: every tag of the repository, following `Link` pagination up
        to `MAX_TAG_PAGES` pages. `truncated` is true when a next page was left unread."""
        host = api_host(registry)
        path = f"/v2/{repository}/tags/list"
        params = {"n": TAG_PAGE_SIZE}
        tags = []
        for _ in range(MAX_TAG_PAGES):
            resp = self._request("GET", registry, repository, path, {"Accept": "application/json"},
                                 params=params, follow_redirects=True)
            self._raise_for_status(resp)
            try:
                body = resp.json()
                page_tags = body.get("tags") or []
            except (ValueError, AttributeError):
                raise RegistryError(ERR_UNEXPECTED) from None
            if not isinstance(page_tags, list) or not all(isinstance(t, str) for t in page_tags):
                raise RegistryError(ERR_UNEXPECTED)
            tags.extend(page_tags)
            nxt = _next_link(resp.headers.get("Link"))
            if not nxt:
                return tags, False
            target = urlparse(urljoin(f"https://{host}{path}", nxt))
            if target.hostname != host or not target.path.startswith("/v2/"):
                raise RegistryError(ERR_UNEXPECTED)
            path, params = target.path, dict(parse_qsl(target.query))
        return tags, True

    @staticmethod
    def _raise_for_status(resp):
        code = resp.status_code
        if 200 <= code < 300:
            return
        if code == 404:
            raise RegistryError(ERR_NOT_FOUND)
        if code in (401, 403):
            raise RegistryError(ERR_LOGIN)
        raise RegistryError(ERR_UNEXPECTED)


def _next_link(header):
    """The `rel="next"` target of a Link header, or None."""
    if not header:
        return None
    for part in header.split(","):
        m = re.match(r'\s*<([^>]+)>\s*;(.*)', part)
        if m and re.search(r'rel\s*=\s*"?next"?', m.group(2)):
            return m.group(1)
    return None
