"""Download-link signatures and SSRF-safe URL fetching."""
from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import socket
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


def _check_host(url: str) -> None:
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.hostname:
        raise UnsafeUrl("Only http and https links are supported")
    if settings.allow_private_urls:
        return
    try:
        infos = socket.getaddrinfo(p.hostname, p.port or (443 if p.scheme == "https" else 80))
    except socket.gaierror:
        raise UnsafeUrl("Could not resolve host") from None
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            raise UnsafeUrl("Links to private or local addresses are not allowed")


def fetch_url(url: str, dest, max_bytes: int, max_redirects: int = 5) -> tuple[str, str]:
    """Download `url` into the open binary file `dest`.

    Every redirect hop is re-checked against private address ranges.
    Returns (final_url, content_type).
    """
    with httpx.Client(timeout=30, follow_redirects=False, headers={"User-Agent": f"{settings.app_name}/1.0"}) as client:
        for _ in range(max_redirects + 1):
            _check_host(url)
            with client.stream("GET", url) as r:
                if r.is_redirect:
                    url = urljoin(url, r.headers.get("location", ""))
                    continue
                if r.status_code != 200:
                    raise UnsafeUrl(f"The link returned HTTP {r.status_code}")
                size = 0
                for chunk in r.iter_bytes(65536):
                    size += len(chunk)
                    if size > max_bytes:
                        raise UnsafeUrl("The linked file is too large")
                    dest.write(chunk)
                return url, r.headers.get("content-type", "application/octet-stream").split(";")[0]
    raise UnsafeUrl("Too many redirects")
