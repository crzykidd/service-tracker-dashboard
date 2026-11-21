"""The pure half of the image update check: the tag model, the digest model, and the state
of one entry (design 2.1 to 2.3, 5.1). No database, no network, no Flask.

`evaluate()` turns what STD knows about an entry (its reference, policy, running digest) and
what the registry said about that reference (a `RefFacts`) into an `Evaluation`: a state in
the 5.1 vocabulary, the newer tag or digest, the kind of change, and a short reason. The job
and the register path both call it, so they cannot disagree.
"""

import re
from dataclasses import dataclass

from image_ref import parse as parse_image_ref

POLICIES = ("auto", "tags", "digest", "off")
SCOPES = ("any", "minor", "patch")
DEFAULT_SCOPE = "any"
STATES = ("update", "current", "unknown", "error", "pinned", "off")
KINDS = ("major", "minor", "patch", "build", "digest")

MAX_CANDIDATES = 50
MAX_TAG_LEN = 128            # longer tags are never evaluated (bounds the regex cost)
MAX_PATTERN_LEN = 200

_RUNS = re.compile(r"\d+|\D+")
_DIGITS = re.compile(r"\d+")
_REPO_DIGEST_RE = re.compile(r"^[^@\s]{1,255}@sha256:[0-9a-f]{64}$")

REASON_NOT_CHECKED = "not checked yet"
REASON_NEEDS_NOTIFIER = "needs notifier 0.5.0 or later to report the running digest"
REASON_LOCAL_IMAGE = "no registry digest for this image (a local build, or another repository)"
REASON_NO_VERSION = "this tag has no version to compare"
REASON_PATTERN_PENDING = "the tag pattern applies at the next check"
REASON_NO_REMOTE_DIGEST = "the registry returned no digest"


# --- tag model ------------------------------------------------------------------------

def tag_shape(tag):
    """`(skeleton, version)` of a tag, or None when it has no digit.

    The skeleton is the tag with every digit run replaced by `N`; the version is the tuple
    of those runs as integers. `16.4-alpine3.20` -> (`N.N-alpineN.N`, (16, 4, 3, 20))."""
    if not isinstance(tag, str) or not tag or len(tag) > MAX_TAG_LEN:
        return None
    versions = tuple(int(m) for m in _DIGITS.findall(tag))
    if not versions:
        return None
    skeleton = "".join("N" if r[0].isdigit() else r for r in _RUNS.findall(tag))
    return skeleton, versions


def numeric_components(tag):
    """How many digit runs a tag has (0 for `latest`, 1 for `16`, 3 for `1.4.2`)."""
    return len(_DIGITS.findall(tag or ""))


def classify(running, candidate):
    """`major` / `minor` / `patch` / `build` by the first differing version component."""
    for i in range(max(len(running), len(candidate))):
        a = running[i] if i < len(running) else 0
        b = candidate[i] if i < len(candidate) else 0
        if a != b:
            return ("major", "minor", "patch")[i] if i < 3 else "build"
    return "build"


def _in_scope(running, candidate, scope):
    if scope == "minor":
        return candidate[:1] == running[:1]
    if scope == "patch":
        return candidate[:2] == running[:2]
    return True


def newer_candidates(running_tag, tags, pattern=None):
    """Tags that are newer than `running_tag`, ascending by version, at most the 50 highest.

    Without a pattern: the same skeleton and a greater version tuple. With one, the pattern
    (a full match) replaces the skeleton rule. Tags over 128 characters are skipped."""
    shape = tag_shape(running_tag)
    if shape is None:
        return []
    skeleton, running = shape
    rx = re.compile(pattern) if pattern else None
    found = {}
    for tag in tags:
        s = tag_shape(tag)
        if s is None or s[1] <= running:
            continue
        if rx is not None:
            if rx.fullmatch(tag) is None:
                continue
        elif s[0] != skeleton:
            continue
        found[tag] = s[1]
    ordered = sorted(found, key=lambda t: (found[t], t))
    return ordered[-MAX_CANDIDATES:]


def choose_latest(running_tag, candidates, scope):
    """`(tag, kind)` of the highest in-scope candidate, or (None, None)."""
    shape = tag_shape(running_tag)
    if shape is None:
        return None, None
    running = shape[1]
    best, best_v = None, None
    for tag in candidates:
        s = tag_shape(tag)
        if s is None or s[1] <= running or not _in_scope(running, s[1], scope):
            continue
        if best_v is None or s[1] > best_v:
            best, best_v = tag, s[1]
    if best is None:
        return None, None
    return best, classify(running, best_v)


# --- pattern validation -----------------------------------------------------------------

def _repeats(items):
    """Yield `(min, max, body)` for every repeat in a parsed regex, recursively."""
    for op, av in items:
        name = str(op)
        if "REPEAT" in name:
            lo, hi, body = av
            yield lo, hi, body
            yield from _repeats(body)
        elif name == "SUBPATTERN":
            yield from _repeats(av[-1])
        elif name == "BRANCH":
            for branch in av[1]:
                yield from _repeats(branch)
        elif name in ("ASSERT", "ASSERT_NOT", "ATOMIC_GROUP"):
            yield from _repeats(av[-1] if name != "ATOMIC_GROUP" else av)
        elif name == "GROUPREF_EXISTS":
            for part in av[1:]:
                if part is not None:
                    yield from _repeats(part)


def _has_nested_quantifier(pattern):
    try:
        import re._parser as sre_parse  # Python 3.11+
        parsed = sre_parse.parse(pattern)
    except Exception:
        return bool(re.search(r"[+*}]\s*\)\s*[+*{]", pattern))
    for _lo, hi, body in _repeats(parsed):
        if hi > 1 and any(ilo != ihi for ilo, ihi, _ in _repeats(body)):
            return True
    return False


def validate_tag_pattern(pattern):
    """None when the pattern is usable, else a short message for the operator."""
    if pattern is None or pattern == "":
        return None
    if not isinstance(pattern, str):
        return "the tag pattern must be text"
    if len(pattern) > MAX_PATTERN_LEN:
        return f"the tag pattern is limited to {MAX_PATTERN_LEN} characters"
    try:
        re.compile(pattern)
    except (re.error, RecursionError, OverflowError):
        return "the tag pattern is not a valid regular expression"
    if _has_nested_quantifier(pattern):
        return "the tag pattern has a repeat inside a repeat, which can be very slow; simplify it"
    return None


# --- digest model ---------------------------------------------------------------------

def pick_running_digest(repo_digests, image_ref):
    """The `sha256:<hex>` of the RepoDigests entry that belongs to the entry's repository.

    `repo_digests` are Docker's raw values (`nginx@sha256:..`, `ghcr.io/o/a@sha256:..`);
    each repository is normalised with `image_ref.parse`, so `nginx` matches
    `docker.io/library/nginx`. None when nothing matches (a local build, another repository)."""
    target = parse_image_ref(image_ref) if isinstance(image_ref, str) else image_ref
    if target is None:
        return None
    for item in repo_digests or ():
        if not isinstance(item, str) or not _REPO_DIGEST_RE.match(item):
            continue
        parsed = parse_image_ref(item)
        if parsed and parsed.registry == target.registry and parsed.repository == target.repository:
            return parsed.digest
    return None


def short_digest(digest):
    """`sha256:` plus the first 12 hex digits (what is stored as `latest` for the digest model)."""
    algo, _, hexpart = (digest or "").partition(":")
    return f"{algo}:{hexpart[:12]}" if hexpart else None


# --- model choice and state -------------------------------------------------------------

def choose_model(policy, tag):
    """`tags` or `digest` for an entry (design 2.1). `policy` is auto | tags | digest."""
    if policy in ("tags", "digest"):
        return policy
    return "tags" if numeric_components(tag) >= 2 else "digest"


@dataclass(frozen=True)
class RefFacts:
    """What the registry said about one reference (a `ImageReference` row, detached)."""
    remote_digest: str | None = None
    candidates: dict | None = None
    checked_at: object = None
    last_error: str | None = None


@dataclass(frozen=True)
class Evaluation:
    state: str | None
    latest: str | None = None
    kind: str | None = None
    reason: str | None = None
    model: str | None = None
    rebuilt: bool = False

    def detail(self):
        return {"reason": self.reason, "model": self.model, "rebuilt": self.rebuilt}


@dataclass
class EntryFacts:
    """The inputs of `evaluate()` for one entry."""
    image_ref: str | None
    policy: str = "auto"
    scope: str | None = None
    pattern: str | None = None
    running_digest: str | None = None
    has_image_info: bool = False


def evaluate(entry, facts, default_scope=DEFAULT_SCOPE):
    """The state of one entry. `facts` is a RefFacts or None (no row yet). Pure."""
    policy = entry.policy if entry.policy in POLICIES else "auto"
    ref = parse_image_ref(entry.image_ref) if entry.image_ref else None
    if ref is None:
        return Evaluation(None)
    if policy == "off":
        return Evaluation("off")
    if ref.digest and not ref.tag:
        return Evaluation("pinned", reason="pinned by digest")
    model = choose_model(policy, ref.tag)

    def unknown(reason):
        return Evaluation("unknown", reason=reason, model=model)

    if model == "tags" and tag_shape(ref.tag) is None:
        return unknown(REASON_NO_VERSION)
    if model == "digest" and not entry.running_digest:
        return unknown(REASON_LOCAL_IMAGE if entry.has_image_info else REASON_NEEDS_NOTIFIER)
    if facts is None or (facts.checked_at is None and not facts.last_error):
        return unknown(REASON_NOT_CHECKED)
    if facts.last_error:
        return Evaluation("error", reason=facts.last_error, model=model)

    if model == "digest":
        if not facts.remote_digest:
            return unknown(REASON_NO_REMOTE_DIGEST)
        if facts.remote_digest == entry.running_digest:
            return Evaluation("current", model=model)
        return Evaluation("update", latest=short_digest(facts.remote_digest), kind="digest", model=model)

    # tag model
    candidates = facts.candidates or {}
    if entry.pattern:
        pool = (candidates.get("patterns") or {}).get(entry.pattern)
        if pool is None:
            return unknown(REASON_PATTERN_PENDING)
    else:
        pool = candidates.get("tags") or []
    scope = entry.scope if entry.scope in SCOPES else (default_scope if default_scope in SCOPES else DEFAULT_SCOPE)
    latest, kind = choose_latest(ref.tag, pool, scope)
    # A pinned tag can also be rebuilt in place: a muted note, never an update.
    rebuilt = bool(entry.running_digest and facts.remote_digest
                   and entry.running_digest != facts.remote_digest)
    if latest:
        return Evaluation("update", latest=latest, kind=kind, model=model, rebuilt=rebuilt)
    return Evaluation("current", model=model, rebuilt=rebuilt)
