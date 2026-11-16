"""Health history for the detail panel (PRD 13.7): bars, uptime, failures.

Pure functions over `HealthResult` rows (naive UTC). Raw rows have
`ts_end` NULL and one sample at `ts`. Compacted range rows have `ts_end` set
and `samples >= 1`; their samples are spread over the buckets they overlap in
proportion to the time overlap (largest-remainder rounding, so the total is
preserved).
"""

from datetime import datetime, timedelta

from extensions import db
from models import HealthResult, check_counts

RANGES = {
    # name: (bucket size, bucket count)
    "24h": (timedelta(minutes=30), 48),
    "7d": (timedelta(hours=1), 168),
}
MAX_MESSAGES = 3


def iso_z(dt):
    """Naive UTC datetime -> ISO 8601 string with a Z suffix (None-safe)."""
    return dt.replace(microsecond=0).isoformat() + "Z" if dt else None


def _floor(dt, size):
    """Floor `dt` to a multiple of `size` since the epoch."""
    epoch = datetime(1970, 1, 1)
    secs = int((dt - epoch).total_seconds())
    step = int(size.total_seconds())
    return epoch + timedelta(seconds=secs - secs % step)


def _split(total, weights):
    """Split integer `total` across `weights`, preserving the sum."""
    wsum = sum(weights)
    if total <= 0 or wsum <= 0:
        return [0] * len(weights)
    exact = [total * w / wsum for w in weights]
    out = [int(x) for x in exact]
    order = sorted(range(len(out)), key=lambda i: exact[i] - out[i], reverse=True)
    for i in order[: total - sum(out)]:
        out[i] += 1
    return out


def _rows(check_id, start, end):
    return (
        db.session.query(HealthResult)
        .filter(HealthResult.check_id == check_id)
        .filter(HealthResult.ts < end)
        .filter(db.func.coalesce(HealthResult.ts_end, HealthResult.ts) >= start)
        .order_by(HealthResult.ts)
        .all()
    )


def _bucketise(rows, start, size, count):
    buckets = [{"ok_samples": 0, "fail_samples": 0, "messages": []} for _ in range(count)]

    def idx(t):
        return int((t - start) // size)

    for r in rows:
        n = max(int(r.samples or 1), 1)
        last = r.ts_end or r.ts
        first_i, last_i = idx(r.ts), idx(last)
        if first_i == last_i or last <= r.ts:
            shares = {first_i: n}
        else:
            span = (last - r.ts).total_seconds()
            idxs = list(range(first_i, last_i + 1))
            weights = []
            for i in idxs:
                lo = max(r.ts, start + i * size)
                hi = min(last, start + (i + 1) * size)
                weights.append(max((hi - lo).total_seconds(), 0) / span)
            shares = dict(zip(idxs, _split(n, weights), strict=True))
        for i, share in shares.items():
            if not 0 <= i < count or share <= 0:
                continue
            b = buckets[i]
            if r.ok:
                b["ok_samples"] += share
            else:
                b["fail_samples"] += share
                msg = r.message
                if msg and msg not in b["messages"] and len(b["messages"]) < MAX_MESSAGES:
                    b["messages"].append(msg)
    return buckets


def bars(check, range_name="24h", now=None):
    """Bar series for `check`: a list of dicts with `start` / `end` (naive
    UTC datetimes), `ok_samples`, `fail_samples`, `messages` (up to 3)."""
    size, count = RANGES[range_name]
    now = now or datetime.utcnow()
    end = _floor(now, size) + size  # the last bucket is the current, partial one
    start = end - size * count
    buckets = _bucketise(_rows(check.id, start, end), start, size, count)
    for i, b in enumerate(buckets):
        b["start"] = start + i * size
        b["end"] = start + (i + 1) * size
    return buckets


def uptime(check, hours, now=None):
    """Percent of ok samples in the last `hours`, or None with no samples."""
    now = now or datetime.utcnow()
    start = now - timedelta(hours=hours)
    size = timedelta(hours=hours)
    (b,) = _bucketise(_rows(check.id, start, now + timedelta(seconds=1)), start, size, 1)
    total = b["ok_samples"] + b["fail_samples"]
    if not total:
        return None
    return round(100.0 * b["ok_samples"] / total, 1)


def recent_failures(check, limit=20):
    """Most recent failed samples, newest first."""
    rows = (
        db.session.query(HealthResult)
        .filter(HealthResult.check_id == check.id, HealthResult.ok.is_(False))
        .order_by(HealthResult.ts.desc())
        .limit(limit)
        .all()
    )
    return [{"ts": r.ts, "message": r.message, "status_code": r.status_code} for r in rows]


def _check_state(check):
    if check.last_ok is None:
        return "unknown"
    return "up" if check.last_ok else "down"


def _target(entry, check):
    if check.kind == "internal_url":
        return entry.internalurl
    if check.kind == "external_url":
        return entry.externalurl
    if check.kind == "container":
        return None
    return check.target


def check_payload(entry, check, range_name="24h", now=None):
    """JSON-ready dict for one check (PRD 13.7)."""
    now = now or datetime.utcnow()
    return {
        "id": check.id,
        "kind": check.kind,
        "name": check.name or check.kind,
        "check_type": check.check_type,
        "target": _target(entry, check),
        "mode": check.mode,
        "state": _check_state(check),
        "last_checked_at": iso_z(check.last_checked_at),
        "latency_ms": check.last_latency_ms,
        "status_code": check.last_status_code,
        "message": check.last_message,
        "uptime_24h": uptime(check, 24, now),
        "uptime_7d": uptime(check, 168, now),
        "failures": [
            {"ts": iso_z(f["ts"]), "message": f["message"], "status_code": f["status_code"]}
            for f in recent_failures(check)
        ],
        "bars": [
            {
                "start": iso_z(b["start"]),
                "end": iso_z(b["end"]),
                "ok": b["ok_samples"],
                "fail": b["fail_samples"],
                "messages": b["messages"],
            }
            for b in bars(check, range_name, now)
        ],
    }


def entry_payload(entry, range_name="24h", now=None):
    """Payload for the detail panel: every check that counts (enabled, with a
    target to probe; the container check on an unlocked notifier entry)."""
    now = now or datetime.utcnow()
    checks = [
        c for c in entry.checks
        if check_counts(entry, c)
    ]
    return {
        "entry_id": entry.id,
        "range": range_name,
        "generated_at": iso_z(now),
        "checks": [check_payload(entry, c, range_name, now) for c in checks],
    }
