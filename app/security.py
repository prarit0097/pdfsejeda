"""Download-link signatures and SSRF-safe URL fetching."""
from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import socket
import time
from urllib.parse import urljoin, urlparse

import httpx

from .config import settings


def sign_task(task_id: str) -> str:
    """Per-task bearer signature, shaped like Sejda's `s=web-<35 chars>`."""
    mac = hmac.new(settings.secret_key.encode(), task_id.encode(), hashlib.sha256).digest()
    return "web-" + base64.urlsafe_b64encode(mac).decode()[:35]


def check_signature(task_id: str, sig: str | None) -> bool:
    return bool(sig) and hmac.compare_digest(sign_task(task_id), sig)


class UnsafeUrl(ValueError):
    pass


def ip_blocked(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """True for anything that is not a public internet address (private, loopback, link-local,
    CGNAT 100.64/10, reserved, multicast, documentation ranges, IPv4-mapped/6to4 forms of those)."""
    if isinstance(ip, ipaddress.IPv6Address):
        inner = ip.ipv4_mapped or ip.sixtofour or (ip.teredo[1] if ip.teredo else None)
        if inner is not None and ip_blocked(inner):
            return True
    return not ip.is_global or ip.is_multicast or ip.is_reserved or ip.is_loopback or ip.is_link_local


def resolve_public(url: str) -> list[str]:
    """Check scheme/host of `url` and return the IP addresses it may be fetched from.

    Raises UnsafeUrl when the scheme isn't http(s) or any address of the host is non-public.
    """
    try:
        p = urlparse(url)
        hostname = p.hostname
    except ValueError:
        raise UnsafeUrl("That doesn't look like a valid web address") from None
    if p.scheme not in ("http", "https") or not hostname:
        raise UnsafeUrl("Only http and https links are supported")
    if p.username is not None or p.password is not None:
        raise UnsafeUrl("Web addresses with embedded credentials are not supported")
    try:
        port = p.port or (443 if p.scheme == "https" else 80)
    except ValueError:
        raise UnsafeUrl("That doesn't look like a valid web address") from None
    try:
        infos = socket.getaddrinfo(p.hostname, port, type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError, OSError):
        raise UnsafeUrl("Could not resolve host") from None
    ips = []
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%")[0])
        if ip_blocked(ip) and not settings.allow_private_urls:
            raise UnsafeUrl("Links to private or local addresses are not allowed")
        if str(ip) not in ips:
            ips.append(str(ip))
    if not ips:
        raise UnsafeUrl("Could not resolve host")
    return ips


def _check_host(url: str) -> None:  # kept for callers that only need the check
    resolve_public(url)


def _pinned(url: str, ip: str) -> tuple[str, dict, dict]:
    """URL rewritten to connect to `ip` (so DNS can't change between check and connect),
    plus the Host header and TLS SNI/cert hostname of the original name."""
    p = urlparse(url)
    host_ip = f"[{ip}]" if ":" in ip else ip
    netloc = host_ip + (f":{p.port}" if p.port else "")
    pinned = p._replace(netloc=netloc).geturl()
    host_header = p.hostname + (f":{p.port}" if p.port else "")
    return pinned, {"Host": host_header}, {"sni_hostname": p.hostname}


def fetch_url(url: str, dest, max_bytes: int, max_redirects: int = 5, *, deadline_s: float = 120,
              transport: httpx.BaseTransport | None = None) -> tuple[str, str]:
    """Download `url` into the open binary file `dest`.

    Every hop (including redirects) is resolved once, checked against non-public address
    ranges and then connected to that exact IP (no DNS rebinding). The whole download must
    finish within `deadline_s` seconds. Returns (final_url, content_type).
    """
    end = time.monotonic() + deadline_s
    with httpx.Client(timeout=30, follow_redirects=False, transport=transport, trust_env=False,
                      headers={"User-Agent": f"{settings.app_name}/1.0"}) as client:
        for _ in range(max_redirects + 1):
            if time.monotonic() >= end:
                raise UnsafeUrl("The download took too long")
            ip = resolve_public(url)[0]
            target, headers, ext = _pinned(url, ip)
            with client.stream("GET", target, headers=headers, extensions=ext) as r:
                if r.is_redirect:
                    location = r.headers.get("location")
                    if not location:
                        raise UnsafeUrl("The link returned an invalid redirect")
                    url = urljoin(url, location)
                    continue
                if r.status_code != 200:
                    raise UnsafeUrl(f"The link returned HTTP {r.status_code}")
                try:
                    declared = int(r.headers.get("content-length") or 0)
                except ValueError:
                    declared = 0
                if declared > max_bytes:
                    raise UnsafeUrl("The linked file is too large")
                size = 0
                for chunk in r.iter_bytes(65536):
                    size += len(chunk)
                    if size > max_bytes:
                        raise UnsafeUrl("The linked file is too large")
                    if time.monotonic() > end:
                        raise UnsafeUrl("The download took too long")
                    dest.write(chunk)
                return url, r.headers.get("content-type", "application/octet-stream").split(";")[0].strip().lower()
    raise UnsafeUrl("Too many redirects")
