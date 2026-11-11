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

    def _guard(request: httpx.Request) -> None:  # runs on every hop, including redirects (SSRF protection never relaxed)
        validate_url(str(request.url))

    # Phase 1 fixes: an honest browser-compatible UA (many hosts 403 bare bot UAs), explicit gzip/deflate, and a
    # separate connect timeout so dead hosts fail fast instead of eating the whole read timeout.
    return httpx.Client(timeout=httpx.Timeout(cfg.http_timeout, connect=cfg.http_connect_timeout), follow_redirects=True,
                        max_redirects=8, transport=transport,
                        headers={"User-Agent": cfg.user_agent, "Accept-Encoding": "gzip, deflate",
                                 "Accept": "application/rss+xml, application/xml;q=0.9, text/xml;q=0.8, */*;q=0.5"},
                        event_hooks={"request": [_guard]})


# ───────────────────────────── failure diagnosis ─────────────────────────────
ERROR_KINDS = ("dns", "timeout", "http_4xx", "http_5xx", "tls", "invalid_xml", "empty", "too_large", "ssrf_blocked",
               "connection", "redirects", "invalid_url", "other")
RETRYABLE = {"timeout", "connection", "http_5xx"}


class HttpStatusError(RuntimeError):
    def __init__(self, status: int):
        super().__init__(f"HTTP {status}")
        self.status = status


class EmptyResponse(ValueError):
    pass


class NotAFeed(ValueError):
    pass


_DNS = ("getaddrinfo", "name or service not known", "nodename nor servname", "no address associated", "cannot resolve host",
        "name resolution", "11001", "11004")
_TLS = ("ssl", "certificate", "tls", "handshake")


def classify_error(exc: BaseException | None = None, *, status: int | None = None, text: str | None = None) -> str:
    """Map a fetch failure to one stable reason code. Works on exceptions, HTTP statuses, or stored error strings."""
    if status is not None:
        return "http_4xx" if 400 <= status < 500 else "http_5xx" if status >= 500 else "other"
    if exc is not None:
        msg = f"{type(exc).__name__}: {exc}".lower()
        if isinstance(exc, InvalidUrl):
            return "ssrf_blocked" if "private or reserved" in msg else "dns" if "cannot resolve" in msg else "invalid_url"
        if isinstance(exc, HttpStatusError):
            return classify_error(status=exc.status)
        if isinstance(exc, FeedTooLarge):
            return "too_large"
        if isinstance(exc, EmptyResponse):
            return "empty"
        if isinstance(exc, NotAFeed):
            return "invalid_xml"
        if isinstance(exc, httpx.TimeoutException):
            return "timeout"
        if isinstance(exc, httpx.TooManyRedirects):
            return "redirects"
        if isinstance(exc, httpx.ConnectError):
            return "dns" if any(k in msg for k in _DNS) else "tls" if any(k in msg for k in _TLS) else "connection"
        if isinstance(exc, (httpx.RemoteProtocolError, httpx.ReadError, httpx.WriteError, httpx.NetworkError)):
            return "tls" if any(k in msg for k in _TLS) else "connection"
        return classify_error(text=msg)
    t = (text or "").lower()
    import re as _re
    m = _re.search(r"http (\d{3})", t)
    if m:
        return classify_error(status=int(m.group(1)))
    for kind, keys in (("ssrf_blocked", ("private or reserved",)), ("too_large", ("exceeds", "feedtoolarge")),
                       ("timeout", ("timeout", "timed out")), ("dns", _DNS), ("tls", _TLS),
                       ("redirects", ("redirect",)), ("empty", ("empty response", "emptyresponse")),
                       ("invalid_xml", ("not a podcast", "not a feed", "notafeed", "xml")),
                       ("connection", ("connecterror", "remoteprotocol", "connection", "readerror", "disconnected"))):
        if any(k in t for k in keys):
            return kind
    return "other"


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
    error_kind: str | None = None
    target: str | None = None

    @property
    def fields_returned(self) -> list[str]:
        return sorted(k for k, v in self.fields.items() if v not in (None, "", [], {}))


class Connector(Protocol):
    name: str
    kind: str
    expected_fields: list[str]


def log_run(s: Session, res: ConnectorResult, expected: list[str], show_id: str | None) -> None:
    s.add(ConnectorRun(connector=res.connector, show_id=show_id, ok=res.ok, fields_returned=res.fields_returned,
                       fields_expected=expected, duration_ms=res.duration_ms, error=res.error,
                       error_kind=None if res.ok else (res.error_kind or classify_error(text=res.error)), target=res.target))


class Timer:
    def __enter__(self) -> "Timer":
        self.t = time.perf_counter()
        return self

    def __exit__(self, *a: object) -> None:
        self.ms = int((time.perf_counter() - self.t) * 1000)
