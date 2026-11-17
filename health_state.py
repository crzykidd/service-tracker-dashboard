"""Roll an entry's health checks up into one state (PRD 13.1 / 13.6).

`entry_health(entry)` is a pure read over `entry.checks` (the view handlers
eager-load them with selectinload, so rolling up a whole page costs no extra
queries). `health.py` stays the liveness endpoint; this is the per-entry
dashboard signal.
"""

from dataclasses import dataclass

from models import CHECK_KIND_CONTAINER, check_counts

STATE_UP = "up"
STATE_DEGRADED = "degraded"
STATE_DOWN = "down"
STATE_UNKNOWN = "unknown"
STATE_NONE = "none"
STATES = (STATE_UP, STATE_DEGRADED, STATE_DOWN, STATE_UNKNOWN, STATE_NONE)

STATE_LABELS = {
    STATE_UP: "Up",
    STATE_DEGRADED: "Degraded",
    STATE_DOWN: "Down",
    STATE_UNKNOWN: "Unknown",
    STATE_NONE: "Not monitored",
}


@dataclass(frozen=True)
class EntryHealth:
    state: str
    total: int      # checks that count (enabled and able to run)
    failing: int    # of those, last result failed
    failures: tuple  # ((check name, message), ...) for the failing checks

    @property
    def label(self):
        return STATE_LABELS[self.state]

    @property
    def tooltip(self):
        """One line per failing check, else the state label."""
        if self.failures:
            lines = [f"{name}: {msg or 'failed'}" for name, msg in self.failures]
            return self.label + "\n" + "\n".join(lines)
        if self.state == STATE_UP:
            return f"Up ({self.total} check{'s' if self.total != 1 else ''} passing)"
        if self.state == STATE_UNKNOWN:
            return "Unknown: checks enabled, none has run yet"
        return self.label


def entry_health(entry):
    """Roll `entry`'s checks up into an `EntryHealth`.

    The Container check counts on its own; the URL and service checks
    (http, tcp, ping, dns) are judged as a group. Among checks that count:

    - none: no checks count.
    - unknown: checks count, none has run yet.
    - down: the Container check is failing, OR every URL/service check that
      has run is failing (even when the container is running).
    - degraded: some URL/service checks pass and some fail.
    - up: nothing that has run is failing (checks still waiting for their
      first run do not hold the state back). An entry with only a Container
      check is up when it passes, down when it fails.
    """
    active = [c for c in entry.checks if check_counts(entry, c)]
    if not active:
        return EntryHealth(STATE_NONE, 0, 0, ())
    ran = [c for c in active if c.last_ok is not None]
    if not ran:
        return EntryHealth(STATE_UNKNOWN, len(active), 0, ())
    failed = [c for c in ran if not c.last_ok]
    failures = tuple((c.name or c.kind, c.last_message) for c in failed)
    group_ran = [c for c in ran if c.kind != CHECK_KIND_CONTAINER]
    group_failed = [c for c in group_ran if not c.last_ok]
    if any(c.kind == CHECK_KIND_CONTAINER and not c.last_ok for c in ran):
        state = STATE_DOWN
    elif not group_failed:
        state = STATE_UP
    elif len(group_failed) == len(group_ran):
        state = STATE_DOWN
    else:
        state = STATE_DEGRADED
    return EntryHealth(state, len(active), len(failed), failures)
