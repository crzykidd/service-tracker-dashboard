"""Health-check probes (v0.7.0, PRD 13.4).

Pure network functions: no Flask, no database, no session. Each probe takes
plain values, returns a `ProbeResult` and never raises, so they are safe to
run on the worker threads of the checker pool (all DB writes happen on the
scheduler thread, see jobs.py).
"""

import ipaddress
import socket
import ssl
import time
import warnings
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

import dns.exception
import dns.message
import dns.query
import dns.rcode
import dns.rdatatype
import dns.reversename
import requests
from cryptography import x509
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
DNS_DEFAULT_PORT = 53


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
    # Leaf certificate notAfter (naive UTC), set only by an https probe that
    # was given `cert_min_days` and got a certificate.
    cert_expires_at: datetime | None = None


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


def _read_cert_expiry(host, port, timeout):
    """The leaf certificate's notAfter (aware UTC) from a fresh TLS handshake
    to `host:port` (SNI set to `host`). Raises on any connection, handshake or
    parse failure.

    Verification is deliberately off (the point is to read the certificate, so
    a self-signed or expired one must not stop the handshake). This is its own
    connection, so it does not follow an `HTTPS_PROXY` the way `requests` does.
    """
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    with socket.create_connection((host, port), timeout=timeout) as sock:
        with context.wrap_socket(sock, server_hostname=host) as tls:
            der = tls.getpeercert(binary_form=True)
    if not der:
        raise ssl.SSLError("the server presented no certificate")
    return x509.load_der_x509_certificate(der).not_valid_after_utc


def _naive_utc(moment):
    if moment.tzinfo is not None:
        moment = moment.astimezone(timezone.utc).replace(tzinfo=None)
    return moment


def _apply_cert_condition(result, target, cert_min_days, timeout):
    """Fold the certificate-expiry condition into an HTTP `result`.

    Rules, in order: a failed HTTP result keeps its message (the expiry is
    still reported when the handshake got one); an ok result with fewer than
    `cert_min_days` days left fails with `cert expires in N days (min M)` (or
    `cert expired N days ago`); an ok result whose certificate could not be
    read fails with `cert check failed: <reason>`; otherwise it stays ok.
    Plain http targets are left alone (no handshake).
    """
    try:
        parts = urlsplit(target)
        if parts.scheme.lower() != "https" or not parts.hostname:
            return result
        port = parts.port or 443
    except ValueError:
        return result
    try:
        expires = _naive_utc(_read_cert_expiry(parts.hostname, port, timeout))
    except Exception as e:
        if not result.ok:
            return result
        return ProbeResult(
            False, result.latency_ms, result.status_code,
            _clip(f"cert check failed: {_exception_message(e)}"), type(e).__name__,
        )
    result.cert_expires_at = expires
    if not result.ok:
        return result
    left = expires - datetime.now(timezone.utc).replace(tzinfo=None)
    if left < timedelta(0):
        days_ago = int((-left).total_seconds() // 86400)
        result.ok, result.message = False, f"cert expired {days_ago} days ago"
    elif left < timedelta(days=cert_min_days):
        days = int(left.total_seconds() // 86400)
        result.ok, result.message = False, f"cert expires in {days} days (min {cert_min_days})"
    return result


def probe_http(target, mode="status", timeout=5, verify=True, cert_min_days=None):
    """GET `target` (redirects followed) and judge it by `mode`; with
    `cert_min_days` set and an https target, also judge the certificate's
    remaining validity (see `_apply_cert_condition`). The request itself is
    `_probe_http_request`.
    """
    result = _probe_http_request(target, mode, timeout, verify)
    if cert_min_days:
        try:
            result = _apply_cert_condition(result, target, cert_min_days, timeout)
        except Exception as e:  # defensive: probes never raise
            return _failure(time.monotonic(), e)
    return result


def _probe_http_request(target, mode, timeout, verify):
    """GET `target` (redirects followed) and judge it by `mode`:

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


def split_dns_server(target):
    """A DNS server target -> (ip string, int port). Raises ValueError.

    Accepts `ip`, `ip:port`, `[v6]` and `[v6]:port`; the port defaults to 53.
    The server must be an IP literal: the check never uses the system
    resolver, so a hostname could not be looked up.
    """
    text = (target or "").strip()
    if not text:
        raise ValueError("a DNS server is required")
    port = DNS_DEFAULT_PORT
    host = text
    if text.startswith("["):
        host, sep, rest = text[1:].partition("]")
        if not sep:
            raise ValueError("a DNS server must be an IP address, optionally with a port")
        if rest:
            if not rest.startswith(":"):
                raise ValueError("a DNS server must be an IP address, optionally with a port")
            port_text = rest[1:]
        else:
            port_text = None
    else:
        try:
            ipaddress.ip_address(text)  # a bare IPv4 or IPv6 literal: no port
            port_text = None
        except ValueError:
            host, sep, port_text = text.rpartition(":")
            if not sep:
                host, port_text = text, None
            elif ":" in host:  # an unbracketed IPv6 with a port is ambiguous
                raise ValueError("write an IPv6 server with a port as [address]:port") from None
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        raise ValueError("a DNS server must be an IP address (not a hostname), optionally with a port") from None
    if port_text is not None:
        if not port_text.isascii() or not port_text.isdigit() or not 1 <= int(port_text) <= 65535:
            raise ValueError("the DNS server port must be from 1 to 65535")
        port = int(port_text)
    return str(ip), port


def _dns_query_name(name, record_type):
    """The name to query: PTR takes an IP (converted to its reverse name); a
    name already under in-addr.arpa / ip6.arpa is used as is."""
    name = (name or "").strip()
    if record_type == "PTR":
        try:
            ipaddress.ip_address(name)
        except ValueError:
            return name
        return dns.reversename.from_address(name)
    return name


def _dns_norm(text, txt=False):
    """Comparison form of an answer or expected value: case-insensitive,
    trailing dot removed, whitespace runs collapsed, IPs in canonical form."""
    text = str(text).strip()
    if txt and len(text) >= 2 and text.startswith('"') and text.endswith('"'):
        text = text[1:-1]
    text = " ".join(text.split()).lower().rstrip(".")
    try:
        return str(ipaddress.ip_address(text))
    except ValueError:
        return text


def _dns_answers(response, rdtype):
    """Printable answers of `rdtype` at any owner name (so a CNAME chain
    followed by an A record still yields the A records), as
    (shown, normalized) pairs."""
    out = []
    for rrset in response.answer:
        if rrset.rdtype != rdtype:
            continue
        for rdata in rrset:
            if rdtype == dns.rdatatype.TXT:
                shown = b"".join(rdata.strings).decode("utf-8", errors="replace")
                out.append((shown, _dns_norm(shown)))
            else:
                shown = rdata.to_text().rstrip(".")
                out.append((shown, _dns_norm(shown)))
    return out


def probe_dns(server, name, record_type="A", expected_rcode=None, expected_answer=None, timeout=5):
    """Query `server` directly for `name` and judge the reply.

    Low-level dnspython (UDP, TCP fallback on truncation); the system
    resolver is never consulted. ok when the rcode equals `expected_rcode`
    (default NOERROR) and, if `expected_answer` is set, any answer record of
    the queried type matches it exactly (normalized, see `_dns_norm`). NOERROR
    with no answers (NODATA) passes only when no answer is expected.
    """
    started = time.monotonic()
    try:
        ip, port = split_dns_server(server)
        rtype = (record_type or "A").strip().upper()
        rdtype = dns.rdatatype.from_text(rtype)
        query = dns.message.make_query(_dns_query_name(name, rtype), rdtype)
        response, _used_tcp = dns.query.udp_with_fallback(query, ip, timeout=timeout, port=port)
        latency = _elapsed_ms(started)
        want_rcode = (expected_rcode or "").strip().upper() or "NOERROR"
        actual = dns.rcode.to_text(response.rcode())
        if actual != want_rcode:
            return ProbeResult(False, latency, None, _clip(f"rcode {actual}"))
        want = (expected_answer or "").strip()
        if not want:
            return ProbeResult(True, latency)
        answers = _dns_answers(response, rdtype)
        if not answers:
            return ProbeResult(False, latency, None, _clip(f"no answer, expected {want}"))
        target = _dns_norm(want, txt=rdtype == dns.rdatatype.TXT)
        if any(norm == target for _shown, norm in answers):
            return ProbeResult(True, latency)
        shown = " | ".join(s for s, _n in answers)
        return ProbeResult(False, latency, None, _clip(f"answer {shown}, expected {want}"))
    except dns.exception.Timeout:
        return ProbeResult(False, _elapsed_ms(started), None, "timeout", "Timeout")
    except Exception as e:
        return _failure(started, e)


def run_probe(job):
    """Run one probe described by a plain dict (check_type, target, mode,
    timeout, verify, and the dns_* fields for DNS). Never raises."""
    check_type = job.get("check_type")
    try:
        if check_type == "tcp":
            return probe_tcp(job["target"], job["timeout"])
        if check_type == "ping":
            return probe_ping(job["target"], job["timeout"])
        if check_type == "dns":
            return probe_dns(
                job["target"], job.get("dns_name"), job.get("dns_record_type"),
                job.get("dns_expected_rcode"), job.get("dns_expected_answer"), job["timeout"],
            )
        return probe_http(job["target"], job.get("mode", "status"), job["timeout"], job.get("verify", True),
                          job.get("cert_min_days"))
    except Exception as e:  # defensive: probes already catch everything
        return ProbeResult(False, 0, None, _exception_message(e), type(e).__name__)
