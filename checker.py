"""Health-check probes (v0.7.0, PRD 13.4).

Pure network functions: no Flask, no database, no session. Each probe takes
plain values, returns a `ProbeResult` and never raises, so they are safe to
run on the worker threads of the checker pool (all DB writes happen on the
scheduler thread, see jobs.py).
"""

import socket
import time
import warnings
from dataclasses import dataclass

import requests
from urllib3.exceptions import InsecureRequestWarning

try:  # icmplib is a pinned dependency; guard so a broken install fails the probe, not the app
    import icmplib
except ImportError:  # pragma: no cover
    icmplib = None

BODY_READ_LIMIT = 4096
ERROR_MESSAGE_LIMIT = 200
UNEXPECTED_PREVIEW = 60
MESSAGE_COLUMN_LIMIT = 255
PING_COUNT = 3
ICMP_NOT_PERMITTED = "ICMP not permitted"


@dataclass
class ProbeResult:
    """Outcome of one probe.

    `error_type` is the exception class name when the probe failed on an
    exception (used to build the legacy `Error: <Name>` status string).
    """

    ok: bool
    latency_ms: int
    status_code: int | None = None
    message: str | None = None
    error_type: str | None = None


def _elapsed_ms(started):
    return int((time.monotonic() - started) * 1000)


def _clip(text, limit=MESSAGE_COLUMN_LIMIT):
    text = str(text)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _exception_message(exc):
    detail = str(exc).strip()
    name = type(exc).__name__
    return _clip(f"{name}: {detail}" if detail else name)


def _failure(started, exc):
    return ProbeResult(
        ok=False,
        latency_ms=_elapsed_ms(started),
        message=_exception_message(exc),
        error_type=type(exc).__name__,
    )


def _read_body(response):
    """At most BODY_READ_LIMIT bytes of the response, decoded and trimmed."""
    raw = b""
    for chunk in response.iter_content(chunk_size=1024):
        raw += chunk
        if len(raw) >= BODY_READ_LIMIT:
            break
    return raw[:BODY_READ_LIMIT].decode("utf-8", errors="replace").strip()


def _error_text(body):
    """The text after an `Error:` prefix (case-sensitive per the spec), else None."""
    if body.startswith("Error:"):
        return body[len("Error:"):].strip()[:ERROR_MESSAGE_LIMIT]
    return None


def probe_http(target, mode="status", timeout=5, verify=True):
    """GET `target` (redirects followed) and judge it by `mode`.

    status: below 400 is ok; failures carry the code or exception text.
    body: reads at most 4 KB. `OK` (case-insensitive) is ok; an `Error:`
    prefix gives that text as the message; anything else is
    `Unexpected response: <first 60 chars>`; a status of 400 or above is
    failing, using the `Error:` text when present, else the status code.

    The urllib3 InsecureRequestWarning is silenced for this call only, and
    only when `verify` is off.
    """
    started = time.monotonic()
    body_mode = mode == "body"
    try:
        with warnings.catch_warnings():
            if not verify:
                warnings.simplefilter("ignore", InsecureRequestWarning)
            response = requests.get(target, timeout=timeout, verify=verify, stream=body_mode)
        try:
            code = int(response.status_code)
            if not body_mode:
                ok = code < 400
                return ProbeResult(ok, _elapsed_ms(started), code, None if ok else str(code))
            body = _read_body(response)
        finally:
            close = getattr(response, "close", None)
            if close:
                close()
        latency = _elapsed_ms(started)
        error_text = _error_text(body)
        if code >= 400:
            return ProbeResult(False, latency, code, error_text or str(code))
        if body.upper() == "OK":
            return ProbeResult(True, latency, code, None)
        if error_text is not None:
            return ProbeResult(False, latency, code, error_text)
        return ProbeResult(False, latency, code, f"Unexpected response: {body[:UNEXPECTED_PREVIEW]}")
    except Exception as e:
        return _failure(started, e)


def split_host_port(target):
    """`host:port` (or `[v6]:port`) -> (host, int port). Raises ValueError."""
    target = (target or "").strip()
    host, sep, port = target.rpartition(":")
    if not sep or not host:
        raise ValueError("target must be host:port")
    host = host.strip("[]")
    port = int(port)
    if not host or not 1 <= port <= 65535:
        raise ValueError("target must be host:port with a port of 1-65535")
    return host, port


def probe_tcp(target, timeout=5):
    """Connect to `host:port`; latency is the connect time."""
    started = time.monotonic()
    try:
        host, port = split_host_port(target)
        with socket.create_connection((host, port), timeout=timeout):
            pass
        return ProbeResult(True, _elapsed_ms(started))
    except Exception as e:
        return _failure(started, e)


def probe_ping(target, timeout=5):
    """ICMP echo, 3 packets, ok when any reply arrives.

    Tries a privileged (raw) socket first, then an unprivileged (datagram)
    one; when neither is allowed the result is failing with
    `ICMP not permitted`. `timeout` is the wait for each reply.
    """
    started = time.monotonic()
    if icmplib is None:  # pragma: no cover
        return ProbeResult(False, 0, None, "icmplib not installed", "ImportError")
    host = (target or "").strip()
    if not host:
        return ProbeResult(False, 0, None, "target is empty", "ValueError")
    last_error = None
    for privileged in (True, False):
        try:
            result = icmplib.ping(
                host, count=PING_COUNT, interval=0.2, timeout=timeout, privileged=privileged
            )
        except icmplib.SocketPermissionError:
            continue
        except Exception as e:
            last_error = e
            if isinstance(e, PermissionError):
                continue
            return _failure(started, e)
        if result.packets_received > 0:
            return ProbeResult(True, int(round(result.avg_rtt)))
        return ProbeResult(
            False, _elapsed_ms(started), None,
            f"No reply ({result.packets_sent} packets sent)",
        )
    message = ICMP_NOT_PERMITTED
    return ProbeResult(
        False, _elapsed_ms(started), None, message,
        type(last_error).__name__ if last_error else "SocketPermissionError",
    )


def run_probe(job):
    """Run one probe described by a plain dict (check_type, target, mode,
    timeout, verify). Never raises."""
    check_type = job.get("check_type")
    try:
        if check_type == "tcp":
            return probe_tcp(job["target"], job["timeout"])
        if check_type == "ping":
            return probe_ping(job["target"], job["timeout"])
        return probe_http(job["target"], job.get("mode", "status"), job["timeout"], job.get("verify", True))
    except Exception as e:  # defensive: probes already catch everything
        return ProbeResult(False, 0, None, _exception_message(e), type(e).__name__)


def legacy_status(result):
    """The pre-0.7 status string the Dashboard/Tiled badges still read:
    the status code when it is a pass or a >=400 failure, else
    `Error: <ExceptionName>`."""
    code = result.status_code
    if code is not None and (result.ok or code >= 400):
        return str(code)
    return f"Error: {result.error_type or 'CheckFailed'}"
