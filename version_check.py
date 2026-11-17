"""Build identity, display strings and the GitHub "update available" check.

Two halves:

* Pure helpers (`short_sha`, `display_info`, `parse_semver`, `is_newer`) turn
  the `VERSION_INFO` dict (version / commit / channel / build_time, see
  `app.read_version_info`) into what the header shows.
* The update check asks GitHub for the latest *release* (never the dev branch)
  and caches the answer. It is page-load driven: `maybe_refresh()` is called
  while a page renders, and when the cached result is older than the interval
  it starts ONE background thread and returns immediately; the page renders
  with the cached value and never waits on GitHub. gunicorn runs exactly one
  worker, so a process-local cache plus a lock is enough. The last good result
  is also persisted in the DB settings store so a restart does not refetch at
  once. Browsers never call GitHub.

The bare version is used everywhere in code; the `v` prefix is added only in
display strings.
"""

import logging
import re
import threading
import time
from datetime import datetime, timezone

import requests

import settings_store

logger = logging.getLogger(__name__)

REPO = "crzykidd/service-tracker-dashboard"
RELEASES_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
COMMIT_URL = f"https://github.com/{REPO}/commit/"
HTTP_TIMEOUT = 5
MAX_BACKOFF_SECONDS = 24 * 3600

CHANNELS = ("release", "main", "dev", "pr", "local")
_SEMVER = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:[+-].*)?$")


# --- build identity -------------------------------------------------------------

def short_sha(commit):
    """First 7 hex characters of a full SHA, or None when unknown."""
    c = (commit or "").strip().lower()
    if re.fullmatch(r"[0-9a-f]{7,40}", c):
        return c[:7]
    return None


def display_info(version_info):
    """What the header shows for this build.

    Returns {label, sha, sha_url, text, channel, is_release}:
    * release        -> label `v0.9.0`
    * main           -> label `v0.9.0 · main`, short SHA linked
    * dev/pr/local   -> label `dev · 0.9.0`, short SHA linked when known;
                        `text` is the one-line form `dev · 0.9.0+sha-abc1234`
    """
    version = (version_info.get("version") or "unknown").strip() or "unknown"
    channel = (version_info.get("channel") or "local").strip().lower()
    if channel not in CHANNELS:
        channel = "local"
    sha = short_sha(version_info.get("commit"))
    sha_url = COMMIT_URL + version_info["commit"].strip() if sha else None
    if channel == "release":
        label = text = f"v{version}"
        sha = sha_url = None  # a release is identified by its tag
    elif channel == "main":
        label = f"v{version} · main"
        text = label + (f"+sha-{sha}" if sha else "")
    else:
        label = f"dev · {version}"
        text = label + (f"+sha-{sha}" if sha else "")
    return {"label": label, "sha": sha, "sha_url": sha_url, "text": text,
            "channel": channel, "is_release": channel == "release"}


def parse_semver(value):
    """(major, minor, patch) of `0.9.0`, `v0.9.0` or `0.9.0+sha...`; None if unparseable."""
    m = _SEMVER.match(value.strip()) if isinstance(value, str) else None
    return tuple(int(g) for g in m.groups()) if m else None


def is_newer(latest, running):
    """True only when `latest` > `running`. `0.9.0+sha...` vs `0.9.0` is not newer;
    anything unparseable is not newer (no update link)."""
    a, b = parse_semver(latest), parse_semver(running)
    return a is not None and b is not None and a > b


# --- update-check cache ---------------------------------------------------------

_state_lock = threading.Lock()
_inflight = threading.Lock()   # held for the whole refresh: at most one in flight
_state = {}


def reset():
    """Clear the in-memory cache (tests; also lets a settings change refetch)."""
    if _inflight.locked():
        _inflight.release()
    with _state_lock:
        _state.clear()
        _state.update({"loaded": False, "latest_version": None, "release_url": None,
                       "checked_at": None, "last_error": None, "next_check_at": 0.0,
                       "failures": 0, "etag": None})


reset()


def _now():
    return time.time()


def _iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_persisted(interval_s):
    """Seed the cache from the DB once per process. Caller holds _state_lock."""
    if _state["loaded"]:
        return
    _state["loaded"] = True
    saved = settings_store.get_update_check_cache()
    if saved.get("checked_at"):
        _state.update(latest_version=saved.get("latest_version"),
                      release_url=saved.get("release_url"),
                      checked_at=saved["checked_at"], etag=saved.get("etag"))
        try:
            ts = datetime.strptime(saved["checked_at"], "%Y-%m-%dT%H:%M:%SZ") \
                .replace(tzinfo=timezone.utc).timestamp()
            _state["next_check_at"] = ts + interval_s
        except ValueError:
            pass


def _persist():
    settings_store.save_update_check_cache({
        "latest_version": _state["latest_version"], "release_url": _state["release_url"],
        "checked_at": _state["checked_at"], "etag": _state["etag"]})


def _spawn(target):
    """Start the background refresh. Separate so tests can capture it."""
    threading.Thread(target=target, name="std-update-check", daemon=True).start()


def _http_get(url, headers):
    return requests.get(url, headers=headers, timeout=HTTP_TIMEOUT)


def maybe_refresh(app):
    """Start a background refresh if the check is enabled and the cache is stale.
    Never blocks and never raises."""
    try:
        enabled, hours = settings_store.get_update_check_settings()
        if not enabled:
            return
        interval_s = hours * 3600
        with _state_lock:
            _load_persisted(interval_s)
            if _now() < _state["next_check_at"]:
                return
        if not _inflight.acquire(blocking=False):
            return
        try:
            _spawn(lambda: _run(app))
        except Exception:
            _inflight.release()
            raise
    except Exception as exc:  # a failed check must never break a page
        logger.debug("update check not started: %s", exc)


def _run(app):
    try:
        with app.app_context():
            refresh_now(app.config.get("VERSION_INFO", {}).get("version", "unknown"))
    except Exception as exc:
        logger.warning("update check failed unexpectedly: %s", exc)
    finally:
        _inflight.release()


def refresh_now(running_version="unknown"):
    """One GitHub request, updating the cache. Needs an app context (DB). On any
    error the last good value is kept and the next attempt is pushed out with
    exponential backoff (interval * 2^failures, capped at 24h)."""
    enabled, hours = settings_store.get_update_check_settings()
    if not enabled:
        return
    base = hours * 3600
    headers = {"Accept": "application/vnd.github+json",
               "User-Agent": f"service-tracker-dashboard/{running_version}"}
    with _state_lock:
        if _state["etag"]:
            headers["If-None-Match"] = _state["etag"]
    now = _now()
    error = None
    wait_until = 0.0
    resp = None
    try:
        resp = _http_get(RELEASES_URL, headers)
    except requests.RequestException as exc:
        error = f"request failed: {exc.__class__.__name__}"
    if resp is not None:
        wait_until = _rate_limit_wait(resp, now)
        if resp.status_code == 200:
            try:
                data = resp.json()
                if not isinstance(data, dict):
                    raise ValueError("unexpected body")
            except ValueError:
                error = "unreadable response from GitHub"
            else:
                tag = data.get("tag_name") if not (data.get("draft") or data.get("prerelease")) else None
                with _state_lock:
                    _state.update(latest_version=tag.lstrip("vV") if isinstance(tag, str) else None,
                                  release_url=data.get("html_url") if isinstance(tag, str) else None,
                                  etag=resp.headers.get("ETag"))
        elif resp.status_code == 304:
            pass
        elif resp.status_code == 404:
            with _state_lock:  # no published release yet: nothing to compare
                _state.update(latest_version=None, release_url=None, etag=None)
        else:
            error = f"GitHub answered HTTP {resp.status_code}"
    with _state_lock:
        if error:
            _state["failures"] += 1
            _state["last_error"] = error
            delay = min(base * (2 ** _state["failures"]), MAX_BACKOFF_SECONDS)
            _state["next_check_at"] = max(now + delay, wait_until)
            first = _state["failures"] == 1
        else:
            _state["failures"] = 0
            _state["last_error"] = None
            _state["checked_at"] = _iso(now)
            _state["next_check_at"] = max(now + base, wait_until)
            first = False
            _persist_locked_safe()
    if error and first:
        logger.warning("update check: %s (backing off)", error)


def _persist_locked_safe():
    try:
        _persist()
    except Exception as exc:
        logger.debug("could not persist update-check cache: %s", exc)


def _rate_limit_wait(resp, now):
    """Epoch time before which GitHub must not be asked again (0 = no constraint)."""
    h = resp.headers
    until = 0.0
    try:
        if "Retry-After" in h:
            until = now + float(h["Retry-After"])
        elif h.get("X-RateLimit-Remaining") == "0" and "X-RateLimit-Reset" in h:
            until = float(h["X-RateLimit-Reset"])
    except ValueError:
        pass
    return until


def status(running_version):
    """Cached update status for templates and the API. Pure read, no I/O to GitHub."""
    enabled, hours = settings_store.get_update_check_settings()
    with _state_lock:
        _load_persisted(hours * 3600)
        latest, url = _state["latest_version"], _state["release_url"]
        checked_at, err = _state["checked_at"], _state["last_error"]
    available = bool(enabled and latest and is_newer(latest, running_version))
    return {"enabled": enabled, "interval_hours": hours, "latest_version": latest if enabled else None,
            "update_available": available, "release_url": url if available else None,
            "checked_at": checked_at, "last_error": err}


def api_update(running_version):
    """The `update` object of whoami / config."""
    s = status(running_version)
    return {"enabled": s["enabled"], "latest_version": s["latest_version"],
            "update_available": s["update_available"], "release_url": s["release_url"],
            "checked_at": s["checked_at"]}
