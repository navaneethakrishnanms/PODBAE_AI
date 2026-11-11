"""Connector interface + safe HTTP. Each connector reports which fields it ACTUALLY returned, so the coverage
report (our measured data-feasibility matrix) is built from facts, not from the vendors' marketing."""
from __future__ import annotations

import ipaddress
import socket
import time
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.parse import urlsplit

import httpx
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import ConnectorRun


class InvalidUrl(ValueError):
    pass


class FeedTooLarge(RuntimeError):
    pass


def validate_url(url: str) -> str:
    """Reject non-http(s), credentials, and (by default) private/loopback/link-local targets (SSRF)."""
    if not isinstance(url, str) or not url.strip() or len(url) > 2048:
        raise InvalidUrl("URL is empty or too long")
    url = url.strip()
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise InvalidUrl("only http(s) URLs are supported")
    if not parts.hostname:
        raise InvalidUrl("URL has no host")
    if parts.username or parts.password:
        raise InvalidUrl("URLs with credentials are not allowed")
    if not get_settings().allow_private_urls:
        host = parts.hostname
        try:
            infos = socket.getaddrinfo(host, parts.port or (443 if parts.scheme == "https" else 80), proto=socket.IPPROTO_TCP)
        except socket.gaierror as exc:
            raise InvalidUrl(f"cannot resolve host {host!r}") from exc
        for info in infos:
            ip = ipaddress.ip_address(info[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
                raise InvalidUrl("URL points to a private or reserved address")
    return url


def make_client(transport: httpx.BaseTransport | None = None) -> httpx.Client:
    cfg = get_settings()

    def _guard(request: httpx.Request) -> None:  # runs on every hop, including redirects
        validate_url(str(request.url))

    return httpx.Client(timeout=cfg.http_timeout, follow_redirects=True, max_redirects=8, transport=transport,
                        headers={"User-Agent": "PodBaeIntel/0.1 (+local; podcast metadata research)",
                                 "Accept": "application/rss+xml, application/xml;q=0.9, text/xml;q=0.8, */*;q=0.5"},
                        event_hooks={"request": [_guard]})


def fetch_bytes(client: httpx.Client, url: str, *, max_bytes: int, headers: dict | None = None) -> tuple[httpx.Response, bytes]:
    """GET with a hard size cap. Returns (response, body)."""
    with client.stream("GET", url, headers=headers or {}) as resp:
        if resp.status_code == 304:
            return resp, b""
        buf = bytearray()
        for chunk in resp.iter_bytes():
            buf.extend(chunk)
            if len(buf) > max_bytes:
                raise FeedTooLarge(f"response exceeds {max_bytes} bytes")
        return resp, bytes(buf)


@dataclass
class ConnectorResult:
    connector: str
    ok: bool = True
    fields: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    duration_ms: int = 0

    @property
    def fields_returned(self) -> list[str]:
        return sorted(k for k, v in self.fields.items() if v not in (None, "", [], {}))


class Connector(Protocol):
    name: str
    kind: str
    expected_fields: list[str]


def log_run(s: Session, res: ConnectorResult, expected: list[str], show_id: str | None) -> None:
    s.add(ConnectorRun(connector=res.connector, show_id=show_id, ok=res.ok, fields_returned=res.fields_returned,
                       fields_expected=expected, duration_ms=res.duration_ms, error=res.error))


class Timer:
    def __enter__(self) -> "Timer":
        self.t = time.perf_counter()
        return self

    def __exit__(self, *a: object) -> None:
        self.ms = int((time.perf_counter() - self.t) * 1000)
