"""The image update check: is a newer image available than the one a container runs?

Design: docs/design/2026-11-21-image-update-check.md; PRD section 21.

* `image_tags.py` is the pure model (tags, digests, the state of one entry).
* `registry_client.py` talks to the registries.
* This module is the engine around them:
  - the provider seam (`UpdateProvider`, `PROVIDERS`): a provider has an id, produces a
    per-entry state in the 5.1 vocabulary, and the job iterates the ENABLED providers. The
    built-in `registry` provider is the only one; the provider id is stored with each
    entry's computed result, so another (What's Up Docker, Komodo) needs no schema change.
  - the settings (enabled: default off, env `STD_IMAGE_UPDATE_ENABLED` wins; scope),
  - the run: dedupe by reference, one tag list per repository, a 4-thread pool, a run
    budget, per-reference backoff, `_RUN_LOCK`; registry I/O never holds a DB transaction,
    never the register lock, and never runs on a request thread,
  - Check now (throttled) and the register-path nudge (debounced),
  - the register-time recompute (`apply_register`, `recompute_entry`: no network),
  - nightly retention of unused reference rows.

STD never updates a container, and the update state is not part of the health roll-up.
"""

import logging
import math
import os
import re
import threading
import time
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import image_tags
import settings_store
from extensions import db
from image_ref import parse as parse_image_ref
from image_tags import REASON_NOT_CHECKED, EntryFacts, RefFacts
from models import SOURCE_NOTIFIER, ImageReference, ServiceEntry
from registry_client import RateLimited, RegistryClient, RegistryError

logger = logging.getLogger(__name__)

PROVIDER_REGISTRY = "registry"
ENV_ENABLED = "STD_IMAGE_UPDATE_ENABLED"
JOB_ID = "image_update_check_job"
INTERVAL_HOURS = 24                       # fixed: there is no interval setting
JITTER_SECONDS = 30 * 60
FIRST_RUN_DELAY_SECONDS = 180             # when the check is first enabled
NUDGE_DELAY_SECONDS = 30

MAX_WORKERS = 4
RUN_BUDGET_SECONDS = 30 * 60
BACKOFF_DAYS_CAP = 7
BACKOFF_SLACK = timedelta(hours=1)        # absorbs the job's jitter: a 1-day backoff retries next run
GLOBAL_COOLDOWN_SECONDS = 3600            # Check now, all references
REF_COOLDOWN_SECONDS = 15 * 60            # Check now, one reference
NUDGE_DEBOUNCE_SECONDS = 5 * 60
RETENTION_DAYS = 30

_RUN_LOCK = threading.Lock()
_STATE_LOCK = threading.Lock()
_PENDING = {"everything": False, "new": False, "refs": set()}
_THROTTLE = {"global": None, "refs": {}, "nudge": None}      # global/refs: UTC datetimes; nudge: monotonic


def reset_state():
    """Clear the in-memory throttles and pending requests (tests)."""
    with _STATE_LOCK:
        _PENDING.update(everything=False, new=False, refs=set())
        _THROTTLE.update({"global": None, "refs": {}, "nudge": None})
    if _RUN_LOCK.locked():
        _RUN_LOCK.release()


def _now():
    return datetime.utcnow()


def _iso(dt):
    return dt.replace(microsecond=0).isoformat() + "Z" if dt else None


# --- settings ---------------------------------------------------------------------------

def _env_enabled():
    raw = (os.environ.get(ENV_ENABLED) or "").strip().lower()
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    return None


def effective_enabled():
    """`(enabled, origin)`: origin is `env`, `ui` or `default`. The default is off."""
    env = _env_enabled()
    if env is not None:
        return env, "env"
    stored = settings_store.get_image_update_value(settings_store.KEY_IMAGE_UPDATE_ENABLED)
    if isinstance(stored, bool):
        return stored, "ui"
    return False, "default"


def is_enabled():
    return effective_enabled()[0]


def default_scope():
    stored = settings_store.get_image_update_value(settings_store.KEY_IMAGE_UPDATE_SCOPE)
    return stored if stored in image_tags.SCOPES else image_tags.DEFAULT_SCOPE


def save_settings(enabled=None, scope=None):
    """Store the switch and/or the default scope. Caller validates and commits."""
    if enabled is not None:
        settings_store.set_image_update_value(settings_store.KEY_IMAGE_UPDATE_ENABLED, bool(enabled))
    if scope is not None:
        settings_store.set_image_update_value(settings_store.KEY_IMAGE_UPDATE_SCOPE, scope)


def last_run():
    raw = settings_store.get_image_update_value(settings_store.KEY_IMAGE_UPDATE_LAST_RUN)
    return raw if isinstance(raw, dict) else None


def _parse_iso(value):
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except (TypeError, ValueError):
        return None


def first_run_time(now=None):
    """When the 24-hour job should first fire after a start (naive UTC): 24 hours after
    the persisted last run, so a restart never causes an extra round of registry traffic.
    With no last run and the check on, a few minutes from now; with it off, in 24 hours
    (turning it on schedules its own first run)."""
    now = now or _now()
    soonest = now + timedelta(seconds=FIRST_RUN_DELAY_SECONDS)
    last = _parse_iso((last_run() or {}).get("at"))
    if last is not None:
        return max(last + timedelta(hours=INTERVAL_HOURS), soonest)
    return soonest if is_enabled() else now + timedelta(hours=INTERVAL_HOURS)


# --- per-entry state --------------------------------------------------------------------

def entry_facts(entry):
    return EntryFacts(
        image_ref=entry.image_ref, policy=entry.image_update_policy or "auto",
        scope=entry.image_update_scope, pattern=entry.image_tag_pattern or None,
        running_digest=entry.image_running_digest,
        has_image_info=entry.image_info is not None)


def ref_facts(row):
    if row is None:
        return None
    return RefFacts(remote_digest=row.remote_digest, candidates=row.candidates,
                    checked_at=row.checked_at, last_error=row.last_error)


def _set(entry, attr, value):
    if getattr(entry, attr) != value:
        setattr(entry, attr, value)


def apply_evaluation(entry, ev, provider=PROVIDER_REGISTRY, now=None):
    """Write an Evaluation to the entry's computed columns. Returns True when the state or
    the newer value changed (what a change event cares about). Caller commits."""
    now = now or _now()
    before = (entry.image_update_state, entry.image_update_latest)
    if ev.state == "update":
        if entry.image_update_state != "update" or entry.image_update_since is None:
            entry.image_update_since = now
    else:
        _set(entry, "image_update_since", None)
    _set(entry, "image_update_state", ev.state)
    _set(entry, "image_update_latest", ev.latest)
    _set(entry, "image_update_kind", ev.kind)
    _set(entry, "image_update_provider", provider if ev.state else None)
    _set(entry, "image_update_detail", ev.detail() if ev.state else None)
    return before != (ev.state, ev.latest)


def recompute_entry(entry, row=None, scope=None):
    """Recompute one entry's state from the stored reference row. No network. Returns the
    Evaluation (its `state` is None for an entry with no usable image)."""
    if row is None and entry.image_ref:
        row = ImageReference.query.filter_by(ref=entry.image_ref).first()
    ev = image_tags.evaluate(entry_facts(entry), ref_facts(row), scope or default_scope())
    apply_evaluation(entry, ev)
    return ev


def clean_image_info(info):
    """The stored form of a register `image_info`: the five display facts, no `repo_digests`
    (reduced to the running digest) and only an http(s) `source`."""
    out = {}
    for key in ("id", "created", "version", "revision", "source"):
        value = info.get(key)
        if value is None:
            continue
        if key == "source" and not re.match(r"^https?://", value, re.I):
            continue
        out[key] = value
    return out


def apply_register(entry, canonical, old_ref):
    """Register-time bookkeeping, inside the upsert lock (no network).

    * `image_info` absent or null: keep the stored values, unless the image changed
      (the canonical reference differs from `old_ref`), when the stored digest values are
      cleared: a digest of the previous image is never compared with the new image's tag.
    * `image_info` present: replace them.

    Then the entry's state is recomputed from the stored reference row. Returns True when
    a check run should be nudged (the check is on and this reference was never checked)."""
    info = canonical.get("image_info")
    if info is not None:
        entry.image_info = clean_image_info(info)
        entry.image_running_digest = image_tags.pick_running_digest(info.get("repo_digests"), entry.image_ref)
    elif canonical.get("image_name") and entry.image_ref != old_ref:
        entry.image_info = None
        entry.image_running_digest = None
    ev = recompute_entry(entry)
    return bool(ev.state == "unknown" and ev.reason == REASON_NOT_CHECKED and is_enabled())


# --- providers --------------------------------------------------------------------------

@dataclass
class RunPlan:
    """What one run covers: everything that is due, the never-checked references, and/or
    specific references (which ignore backoff)."""
    trigger: str = "schedule"
    everything: bool = False
    new: bool = False
    refs: frozenset = frozenset()


@dataclass
class RunSummary:
    provider: str
    refs: int = 0
    checked: int = 0
    errors: int = 0
    skipped: int = 0
    updates: int = 0
    duration_seconds: float = 0.0


class UpdateProvider(ABC):
    """A source of per-entry image update state. `run` computes the state of the entries it
    covers (the 5.1 vocabulary, via `image_tags.Evaluation`) and stores it with
    `apply_evaluation(entry, ev, provider=self.id)`."""

    id = ""

    @abstractmethod
    def enabled(self):
        """True when this provider should run."""

    @abstractmethod
    def run(self, app, plan):
        """Run once, inside no app context (push your own). Returns a RunSummary."""


@dataclass
class _Want:
    ref: str
    registry: str
    repository: str
    tag: str
    need_tags: bool = False
    need_head: bool = False
    patterns: set = field(default_factory=set)


@dataclass
class _Result:
    skipped: bool = False
    error: RegistryError | None = None
    remote_digest: str | None = None
    candidates: dict | None = None


def _backoff(failures):
    return timedelta(days=min(2 ** max(failures - 1, 0), BACKOFF_DAYS_CAP))


def _is_new(row):
    return row is None or (row.checked_at is None and not row.last_error)


def _due(row, now):
    return row is None or row.next_check_at is None or row.next_check_at <= now + BACKOFF_SLACK


class RegistryProvider(UpdateProvider):
    """The built-in provider: asks the image registries directly (anonymous, HTTPS)."""

    id = PROVIDER_REGISTRY

    def enabled(self):
        return is_enabled()

    # -- planning -----------------------------------------------------------------------

    def _collect(self):
        """`{ref: _Want}` of what the active Docker entries need from a registry. An entry
        needs nothing when it is pinned by digest, has policy off, or (digest model) has no
        running digest to compare: its state is unknown without a request."""
        wants = {}
        entries = (ServiceEntry.query
                   .filter(ServiceEntry.deleted_at.is_(None), ServiceEntry.source == SOURCE_NOTIFIER,
                           ServiceEntry.image_ref.isnot(None)).all())
        for e in entries:
            policy = e.image_update_policy or "auto"
            parsed = parse_image_ref(e.image_ref)
            if policy == "off" or parsed is None or not parsed.tag:
                continue
            model = image_tags.choose_model(policy, parsed.tag)
            need_tags = model == "tags" and image_tags.tag_shape(parsed.tag) is not None
            need_head = bool(e.image_running_digest) and (model == "digest" or need_tags)
            if not (need_tags or need_head):
                continue
            want = wants.get(e.image_ref)
            if want is None:
                want = wants[e.image_ref] = _Want(e.image_ref, parsed.registry, parsed.repository, parsed.tag)
            want.need_tags = want.need_tags or need_tags
            want.need_head = want.need_head or need_head
            if need_tags and e.image_tag_pattern:
                want.patterns.add(e.image_tag_pattern)
        return wants

    def _select(self, plan, wants, rows, now):
        selected = []
        for ref, want in wants.items():
            row = rows[ref]
            if ref in plan.refs:
                selected.append(want)
            elif plan.everything and _due(row, now):
                selected.append(want)
            elif plan.new and _is_new(row) and _due(row, now):
                selected.append(want)
        return selected

    # -- network (worker threads; no database) ------------------------------------------

    @staticmethod
    def _candidates(want, tags, truncated):
        patterns = {}
        for pattern in want.patterns:
            try:
                patterns[pattern] = image_tags.newer_candidates(want.tag, tags, pattern)
            except re.error:
                continue
        return {"tags": image_tags.newer_candidates(want.tag, tags), "tags_total": len(tags),
                "truncated": truncated, "patterns": patterns}

    def _check_repository(self, client, registry, repository, wants, deadline):
        out = {}
        tags = truncated = tags_error = None
        if any(w.need_tags for w in wants):
            if time.monotonic() > deadline:
                return {w.ref: _Result(skipped=True) for w in wants}
            try:
                tags, truncated = client.list_tags(registry, repository)
            except RegistryError as exc:
                tags_error = exc
        for want in wants:
            if time.monotonic() > deadline:
                out[want.ref] = _Result(skipped=True)
                continue
            result = _Result()
            if want.need_tags:
                if tags_error is not None:
                    result.error = tags_error
                else:
                    result.candidates = self._candidates(want, tags, truncated)
            if want.need_head and result.error is None:
                try:
                    result.remote_digest = client.head_manifest(registry, repository, want.tag)
                except RegistryError as exc:
                    # Only the digest model depends on it; for the tag model it is a bonus
                    # (the muted "rebuilt" note), so a failure there is not an error.
                    if not want.need_tags:
                        result.error = exc
            out[want.ref] = result
        return out

    # -- the run ------------------------------------------------------------------------

    def run(self, app, plan):
        started = time.monotonic()
        summary = RunSummary(self.id)
        version = (app.config.get("VERSION_INFO") or {}).get("version") or "unknown"
        with app.app_context():
            try:
                now = _now()
                wants = self._collect()
                rows = self._upsert_rows(wants, now)
                selected = self._select(plan, wants, rows, now)
                summary.refs = len(selected)
                results = {}
                if selected:
                    client = RegistryClient(user_agent=f"service-tracker-dashboard/{version}",
                                            http=_http_override())
                    deadline = time.monotonic() + RUN_BUDGET_SECONDS
                    groups = {}
                    for want in selected:
                        groups.setdefault((want.registry, want.repository), []).append(want)
                    # Registry I/O: no DB transaction is open (committed above), no register lock.
                    with ThreadPoolExecutor(max_workers=MAX_WORKERS, thread_name_prefix="std-imgcheck") as pool:
                        futures = [pool.submit(self._check_repository, client, reg, repo, ws, deadline)
                                   for (reg, repo), ws in groups.items()]
                        for fut in futures:
                            try:
                                results.update(fut.result())
                            except Exception:  # a bug in one repository must not stop the run
                                logger.exception("image update check: a repository task failed")
                self._store_results(selected, results, now, summary)
                summary.updates = self._recompute_all()
            except Exception:
                logger.exception("image update check failed; rolling back")
                db.session.rollback()
        summary.duration_seconds = round(time.monotonic() - started, 2)
        return summary

    @staticmethod
    def _upsert_rows(wants, now):
        """The reference rows of every wanted reference (created on first sight), with
        `last_wanted_at` refreshed. One short transaction."""
        rows = {}
        if wants:
            for row in ImageReference.query.filter(ImageReference.ref.in_(list(wants))).all():
                rows[row.ref] = row
        for ref, want in wants.items():
            row = rows.get(ref)
            if row is None:
                row = rows[ref] = ImageReference(
                    ref=ref, registry_name=want.registry, repository=want.repository, tag=want.tag,
                    failures=0, last_wanted_at=now)
                db.session.add(row)
            else:
                row.last_wanted_at = now
        db.session.commit()
        return rows

    @staticmethod
    def _store_results(selected, results, now, summary):
        for want in selected:
            result = results.get(want.ref)
            row = ImageReference.query.filter_by(ref=want.ref).first()
            if row is None or result is None or result.skipped:
                summary.skipped += 1
                continue
            if result.error is not None:
                row.failures = (row.failures or 0) + 1
                row.last_error = result.error.message[:300]
                row.last_error_at = now
                wait = _backoff(row.failures)
                if isinstance(result.error, RateLimited):
                    wait = max(wait, timedelta(seconds=result.error.retry_after))
                row.next_check_at = now + wait
                summary.errors += 1
                continue
            if result.remote_digest is not None:
                if row.remote_digest and row.remote_digest != result.remote_digest:
                    row.remote_digest_changed_at = now
                row.remote_digest = result.remote_digest
            if result.candidates is not None:
                row.candidates = result.candidates
            row.checked_at = now
            row.last_error = None
            row.last_error_at = None
            row.failures = 0
            row.next_check_at = None
            summary.checked += 1
        db.session.commit()

    @staticmethod
    def _recompute_all():
        """Recompute every Docker entry's state from the reference rows. Commits once.
        Returns how many entries show `update`."""
        scope = default_scope()
        rows = {r.ref: r for r in ImageReference.query.all()}
        updates = 0
        entries = (ServiceEntry.query
                   .filter(ServiceEntry.deleted_at.is_(None), ServiceEntry.source == SOURCE_NOTIFIER,
                           ServiceEntry.image_ref.isnot(None)).all())
        for e in entries:
            ev = image_tags.evaluate(entry_facts(e), ref_facts(rows.get(e.image_ref)), scope)
            apply_evaluation(e, ev)
            updates += ev.state == "update"
        db.session.commit()
        return updates


PROVIDERS = {PROVIDER_REGISTRY: RegistryProvider()}

# Tests replace this to serve a fake registry; production leaves it None (real HTTP).
_HTTP_OVERRIDE = None


def _http_override():
    return _HTTP_OVERRIDE


def enabled_providers():
    return [p for p in PROVIDERS.values() if p.enabled()]


# --- running ----------------------------------------------------------------------------

def _drain_pending():
    with _STATE_LOCK:
        plan = RunPlan("manual", everything=_PENDING["everything"], new=_PENDING["new"],
                       refs=frozenset(_PENDING["refs"]))
        _PENDING.update(everything=False, new=False, refs=set())
    return plan


def _has_pending():
    with _STATE_LOCK:
        return bool(_PENDING["everything"] or _PENDING["new"] or _PENDING["refs"])


def _merge(a, b):
    return RunPlan(a.trigger, everything=a.everything or b.everything, new=a.new or b.new,
                   refs=a.refs | b.refs)


def execute(app, plan):
    """Run every enabled provider once. `_RUN_LOCK` is taken non-blocking: when a run is in
    progress, the request stays pending and is served by a follow-up run when it ends.
    Returns the list of RunSummary, or None when nothing ran."""
    if not _RUN_LOCK.acquire(blocking=False):
        return None
    summaries = []
    try:
        # The scheduler calls this with no app context; reading the switch needs one.
        with app.app_context():
            providers = enabled_providers()
        if not providers:
            _drain_pending()                      # asked while the check is off: dropped
            return None
        plan = _merge(plan, _drain_pending())
        for provider in providers:
            summaries.append(provider.run(app, plan))
        if plan.everything or plan.new:
            _save_last_run(app, plan, summaries)
    finally:
        _RUN_LOCK.release()
    if _has_pending():
        _schedule(app, NUDGE_DELAY_SECONDS)
    return summaries


def _save_last_run(app, plan, summaries):
    with app.app_context():
        try:
            total = lambda attr: sum(getattr(s, attr) for s in summaries)  # noqa: E731
            settings_store.set_image_update_value(settings_store.KEY_IMAGE_UPDATE_LAST_RUN, {
                "at": _iso(_now()), "trigger": plan.trigger, "refs": total("refs"),
                "checked": total("checked"), "updates": total("updates"), "errors": total("errors"),
                "skipped": total("skipped"), "duration_seconds": round(total("duration_seconds"), 2)})
            db.session.commit()
        except Exception:
            logger.exception("could not record the image update check run")
            db.session.rollback()


def run_scheduled(app):
    """The daily job body (`jobs.image_update_check_job`)."""
    if not is_enabled_in(app):
        return None
    return execute(app, RunPlan("schedule", everything=True))


def run_pending(app):
    """The one-shot body for Check now and the register nudge: serve what is pending."""
    if not _has_pending():
        return None
    return execute(app, RunPlan("manual"))


def is_enabled_in(app):
    with app.app_context():
        return is_enabled()


def _schedule(app, delay_seconds):
    """Ask the scheduler for a one-shot `run_pending`. False when there is no scheduler
    (tests, or before startup)."""
    try:
        import jobs
        return jobs.schedule_image_update_run(app, delay_seconds)
    except Exception:
        logger.debug("could not schedule an image update run", exc_info=True)
        return False


# --- requests: Check now, nudge, first enable ---------------------------------------------

class CheckRequestError(Exception):
    """A refused Check now. `status` is the HTTP status the API answers. `confirm_required` marks
    a request inside the cooldown that the UI may repeat with `force=True` (`ago_seconds` is how
    long ago the last check was); the management API has no one to ask and keeps the 429."""

    def __init__(self, status, message, retry_after=None, confirm_required=False, ago_seconds=None):
        super().__init__(message)
        self.status, self.message, self.retry_after = status, message, retry_after
        self.confirm_required, self.ago_seconds = confirm_required, ago_seconds


class CheckQueued(int):
    """The number of references queued; `already_running` when a run was already pending or
    in progress, so nothing new was queued."""

    already_running = False


def _already_running():
    result = CheckQueued(0)
    result.already_running = True
    return result


def ago_text(seconds):
    """Plain words for how long ago: 'less than a minute ago', '1 minute ago', '27 minutes ago'."""
    minutes = int(max(0, seconds) // 60)
    if minutes < 1:
        return "less than a minute ago"
    if minutes < 60:
        return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
    hours = minutes // 60
    return f"{hours} hour{'s' if hours != 1 else ''} ago"


def _later(*times):
    times = [t for t in times if t is not None]
    return max(times) if times else None


def checkable_refs():
    """The distinct references an entry could be checked for (not off, not pinned)."""
    refs = set()
    q = (ServiceEntry.query.filter(ServiceEntry.deleted_at.is_(None), ServiceEntry.source == SOURCE_NOTIFIER,
                                   ServiceEntry.image_ref.isnot(None)))
    for e in q.all():
        parsed = parse_image_ref(e.image_ref)
        if (e.image_update_policy or "auto") != "off" and parsed is not None and parsed.tag:
            refs.add(e.image_ref)
    return refs


def request_check(app, entry=None, force=False):
    """Check now: everything (cooldown an hour) or one entry's reference (15 minutes per
    reference; ignores backoff). Inside the cooldown it raises a `confirm_required`
    CheckRequestError unless `force`. A run already pending or in progress is not doubled: the
    result has `already_running`. Otherwise records the request and asks for a one-shot run.
    Returns the number of references queued. Raises CheckRequestError."""
    if not is_enabled():
        raise CheckRequestError(409, "The image update check is off; turn it on first.")
    now = _now()
    if entry is None:
        queued = len(checkable_refs())
        last_check = _later(_parse_iso((last_run() or {}).get("at")))
        cooldown, what = GLOBAL_COOLDOWN_SECONDS, "Checked for every image"
    else:
        parsed = parse_image_ref(entry.image_ref) if entry.image_ref else None
        if (entry.source != SOURCE_NOTIFIER or entry.deleted_at is not None or parsed is None
                or not parsed.tag or (entry.image_update_policy or "auto") == "off"):
            raise CheckRequestError(409, "This entry has no image reference to check.")
        queued = 1
        row = ImageReference.query.filter_by(ref=entry.image_ref).first()
        last_check = row.checked_at if row is not None else None
        cooldown, what = REF_COOLDOWN_SECONDS, "This image was checked"
    with _STATE_LOCK:
        if entry is None:
            last_check = _later(last_check, _THROTTLE["global"])
        else:
            last_check = _later(last_check, _THROTTLE["refs"].get(entry.image_ref))
        if last_check is not None and not force:
            ago = (now - last_check).total_seconds()
            if 0 <= ago < cooldown:
                raise CheckRequestError(
                    429, f"{what} a moment ago; try again later.", math.ceil(cooldown - ago),
                    confirm_required=True, ago_seconds=int(ago))
        if entry is None:
            if _PENDING["everything"] or _RUN_LOCK.locked():
                return _already_running()
            _THROTTLE["global"] = now
            _PENDING["everything"] = True
        else:
            if (_PENDING["everything"] or entry.image_ref in _PENDING["refs"]
                    or _RUN_LOCK.locked()):
                return _already_running()
            _THROTTLE["refs"][entry.image_ref] = now
            _PENDING["refs"].add(entry.image_ref)
    _schedule(app, 0)
    return CheckQueued(queued)


def maybe_nudge(app):
    """A reference nobody has checked yet showed up in a register: ask for a run of the
    never-checked references, at most once per 5 minutes, and only when the check is on."""
    if not is_enabled():
        return False
    now = time.monotonic()
    with _STATE_LOCK:
        last = _THROTTLE["nudge"]
        if last is not None and now - last < NUDGE_DEBOUNCE_SECONDS:
            return False
        _THROTTLE["nudge"] = now
        _PENDING["new"] = True
    _schedule(app, NUDGE_DELAY_SECONDS)
    return True


def on_settings_changed(app, was_enabled):
    """After the switch changes: turning it on schedules the first run a few minutes out,
    unless one ran in the last 24 hours. Either way a change of the switch asks for a full MQTT
    sync, which publishes or withdraws the image topics and the Home Assistant entities."""
    if was_enabled != is_enabled():
        import notify
        notify.request_sync(force=True)
    if was_enabled or not is_enabled():
        return False
    last = _parse_iso((last_run() or {}).get("at"))
    if last is not None and _now() - last < timedelta(hours=INTERVAL_HOURS):
        return False
    with _STATE_LOCK:
        _PENDING["everything"] = True
    _schedule(app, FIRST_RUN_DELAY_SECONDS)
    return True


# --- retention --------------------------------------------------------------------------

def prune_references(now=None):
    """Delete reference rows no active entry has wanted for 30 days. Skipped while the
    check is off: nothing refreshes `last_wanted_at` then, and the stored results are kept
    for when it is turned back on. Needs an app context; commits. Returns rows deleted."""
    if not is_enabled():
        return 0
    cutoff = (now or _now()) - timedelta(days=RETENTION_DAYS)
    deleted = (ImageReference.query.filter(ImageReference.last_wanted_at < cutoff)
               .delete(synchronize_session=False))
    db.session.commit()
    return deleted


# --- reporting (API) ----------------------------------------------------------------------

def effective_state(entry, enabled=None):
    """The state to show: `off` while the check is switched off (stored results are kept
    and come back when it is turned on), else the stored state."""
    enabled = is_enabled() if enabled is None else enabled
    if entry.image_update_state is None:
        return None
    return "off" if not enabled else entry.image_update_state


def reference_report(state=None):
    """Per-reference list for the API: every reference an active Docker entry runs, with the
    entries using it. `state` keeps references with an entry in that (effective) state."""
    enabled = is_enabled()
    rows = {r.ref: r for r in ImageReference.query.all()}
    entries = (ServiceEntry.query
               .filter(ServiceEntry.deleted_at.is_(None), ServiceEntry.source == SOURCE_NOTIFIER,
                       ServiceEntry.image_ref.isnot(None))
               .order_by(ServiceEntry.id).all())
    grouped = {}
    for e in entries:
        grouped.setdefault(e.image_ref, []).append(e)
    items = []
    for ref in sorted(grouped):
        members = grouped[ref]
        states = {e.id: effective_state(e, enabled) for e in members}
        if state and state not in states.values():
            continue
        parsed = parse_image_ref(ref)
        row = rows.get(ref)
        candidates = (row.candidates or {}) if row else {}
        items.append({
            "ref": ref,
            "registry": parsed.registry if parsed else None,
            "repository": parsed.repository if parsed else None,
            "tag": parsed.tag if parsed else None,
            "remote_digest": row.remote_digest if row else None,
            "remote_digest_changed_at": _iso(row.remote_digest_changed_at) if row else None,
            "checked_at": _iso(row.checked_at) if row else None,
            "error": row.last_error if row else None,
            "error_at": _iso(row.last_error_at) if row else None,
            "failures": (row.failures or 0) if row else 0,
            "next_check_at": _iso(row.next_check_at) if row else None,
            "tags_total": candidates.get("tags_total"),
            "entries": [{
                "id": e.id, "name": e.container_name, "host": e.host, "state": states[e.id],
                "latest": e.image_update_latest, "kind": e.image_update_kind,
                "since": _iso(e.image_update_since), "policy": e.image_update_policy or "auto",
            } for e in members],
        })
    return items

