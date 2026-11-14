"""Registrable domains, OFFLINE. tldextract with its bundled public-suffix snapshot (suffix_list_urls=() -> never fetches).
Domains are never verified as legitimate in this phase (no fetching): brands carry domain_verified=False (seam)."""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import yaml

SEED = Path(__file__).with_name("seed")
URL_RX = re.compile(r"(?:https?://|www\.)[^\s\"'<>()\[\]{}|\\^`]+|\b[a-z0-9][a-z0-9-]{1,62}\.(?:com|co|io|net|org|me|fm|app|ai|co\.uk|tv|shop|store|ly|to|gg)(?:/[^\s\"'<>()\[\]{}|\\^`]*)?",
                    re.I)
AFFILIATE_DOMAINS = {"amzn.to", "amazon.com", "amazon.co.uk", "amazon.ca", "geni.us", "shareasale.com", "awin1.com", "skimresources.com",
                     "rstyle.me", "howl.me", "linksynergy.com", "anrdoezrs.net", "dpbolvw.net", "jdoqocy.com", "tkqlhce.com", "kqzyfj.com",
                     "shop-links.co", "bookshop.org", "impact.com", "sjv.io", "pxf.io", "go.redirectingat.com", "fave.co", "click.linksynergy.com"}


@lru_cache(maxsize=1)
def _extractor():
    import tldextract
    return tldextract.TLDExtract(suffix_list_urls=(), cache_dir=None)


@lru_cache(maxsize=1)
def denylist() -> frozenset[str]:
    d = yaml.safe_load((SEED / "denylist.yaml").read_text(encoding="utf-8"))
    return frozenset(x.lower() for v in d.values() for x in v)


def clean_url(raw: str) -> str | None:
    if not raw or "@" in raw or raw.lower().startswith("mailto:"):
        return None
    u = raw.rstrip(".,;:!?)'\"”’")
    u = re.sub(r"([a-z0-9/])([A-Z][a-z]+)$", r"\1", u)       # 'site.com/codeListen' (text glued after a URL)
    if not re.match(r"https?://", u, re.I):
        u = "https://" + u
    p = urlsplit(u)
    return u[:400] if p.netloc and "." in p.netloc else None


TENANT_PLATFORMS = {"onelink.me", "app.link", "page.link", "ubpages.com", "myshopify.com", "pxf.io", "sjv.io", "go2cloud.org",
                    "hubspotpagebuilder.com", "carrd.co", "webflow.io", "framer.website", "typedream.app"}


def registrable(url_or_host: str) -> str | None:
    """Brand identity domain. For link / landing platforms where each tenant gets a subdomain (prizepicks.onelink.me,
    afterglow.ubpages.com) the tenant host is the identity, so different advertisers never merge into the platform."""
    reg = _registrable(url_or_host)
    if reg in TENANT_PLATFORMS:
        host = (urlsplit(url_or_host if "//" in url_or_host else "https://" + url_or_host).hostname or "").lower().removeprefix("www.")
        sub_ = host[: -len(reg)].rstrip(".")
        return f"{sub_.split('.')[-1]}.{reg}" if sub_ else None
    return reg


def _registrable(url_or_host: str) -> str | None:
    host = urlsplit(url_or_host if "//" in url_or_host else "https://" + url_or_host).hostname or ""
    if not host:
        return None
    e = _extractor()(host)
    dom = getattr(e, "top_domain_under_public_suffix", None) or e.registered_domain
    return dom.lower() if dom else None


def full_host(url: str) -> str:
    return (urlsplit(url).hostname or "").lower().removeprefix("www.")


def is_denylisted(url: str) -> bool:
    dl = denylist()
    host, reg = full_host(url), registrable(url) or ""
    return host in dl or reg in dl or any(host.endswith("." + d) for d in dl)


def is_affiliate(url: str) -> str | None:
    p = urlsplit(url)
    host, reg = full_host(url), registrable(url) or ""
    if host in AFFILIATE_DOMAINS or reg in AFFILIATE_DOMAINS:
        return "affiliate_domain"
    q = parse_qs(p.query)
    if any(k in q for k in ("tag", "aff", "affid", "affiliate", "aff_id", "ref_id")) or "ref" in q:
        return "affiliate_param"
    if re.search(r"/(aff|affiliate|affiliates|go)/", p.path or "", re.I):
        return "affiliate_path"
    return None


def vanity_path(url: str) -> str | None:
    """brand.com/<one short segment> (e.g. betterhelp.com/showname) - the classic host-read vanity URL."""
    path = (urlsplit(url).path or "").strip("/")
    if path and "/" not in path and 2 <= len(path) <= 30 and re.fullmatch(r"[A-Za-z0-9_-]+", path) and not re.fullmatch(
            r"(home|index|about|contact|shop|store|blog|en|us|products?|collections?|pages?|podcast|podcasts|episodes?)", path, re.I):
        return path
    return None


def label(domain: str) -> str:
    """Brand label from a registrable domain: 'betterhelp.com' -> 'betterhelp'."""
    return domain.split(".")[0]
