"""Declared collaboration / contact routes (Phase 2 close-out, Layer 4 commercial readiness). Rule-based, no LLM, no fetching.

A route is a PUBLIC page the show itself points to for contact, booking, guest applications or collaborations:
  - a URL in the show description or recent episode notes whose PATH is a contact / booking / guest / collab page
  - the feed's website link when its path is such a page
  - a <podcast:person href=...> link (captured from Phase 2 ingests on)
A plain homepage is NOT a route. E-mail addresses are never extracted, stored or derived: anything with '@' or mailto is
dropped before matching. Stored as field 'contact_routes' (tier verified: read from the publisher's own feed), each route
with where it was found (+ episode id), and as evidence rows."""
from __future__ import annotations

import re
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Episode, Evidence
from .trust.provenance import add_evidence, get_source, live_rows, record

URL_RX = re.compile(r"https?://[^\s\"'<>()\[\]{}|\\^`]+", re.I)
# path segment that names a contact / booking / guest / collaboration page
ROUTE_RX = re.compile(r"(?:^|/)(contact(?:-?us|-?me)?|get-in-touch|booking|bookings|book-?a-?call|book-?me|be-?a-?guest|be-?on-?the-?show|"
                      r"guest(?:s|-?application|-?form|-?request)?|apply|application|pitch|collab(?:orate|oration|orations)?|"
                      r"work-?with-?(?:me|us)|partner(?:ship|ships)?)(?=$|[/?#.]|-)", re.I)   # sponsor/advertise pages are for advertisers: not counted
KIND = [("guest_application", re.compile(r"guest|be-?a-?guest|be-?on-?the-?show|apply|application|pitch", re.I)),
        ("booking", re.compile(r"book", re.I)), ("collaboration", re.compile(r"collab|partner|work-?with", re.I)),
        ("contact_page", re.compile(r"contact|get-in-touch", re.I))]
GLUED = re.compile(r"([a-z0-9/])([A-Z][a-z]+)$")      # 'https://x.com/contactListen' (text glued after the URL)


def _clean(u: str) -> str | None:
    if "@" in u or u.lower().startswith("mailto:"):
        return None
    u = u.rstrip(".,;:!?)'\"")
    u = GLUED.sub(r"\1", u)
    p = urlsplit(u)
    if p.scheme not in ("http", "https") or not p.netloc:
        return None
    return u[:300]


def route_kind(url: str) -> str | None:
    path = urlsplit(url).path or "/"
    if not ROUTE_RX.search(path):
        return None
    return next((k for k, rx in KIND if rx.search(path)), "contact_page")


def _key(u: str) -> str:
    p = urlsplit(u.lower())
    return p.netloc.removeprefix("www.") + p.path.rstrip("/")


def find_routes(s: Session, show_id: str, max_episodes: int = 60) -> list[dict]:
    out: dict[str, dict] = {}

    def add(raw: str, found_in: str, episode_id: str | None = None) -> None:
        u = _clean(raw)
        if not u:
            return
        k = route_kind(u)
        if k and _key(u) not in out:
            out[_key(u)] = {"kind": k, "url": u, "found_in": found_in, **({"episode_id": episode_id} if episode_id else {})}

    w = live_rows(s, "show", show_id, "website")
    if w and isinstance(w[0].value_json, str):
        add(w[0].value_json, "website_link")
    d = live_rows(s, "show", show_id, "description")
    for u in URL_RX.findall(str(d[0].value_json) if d else ""):
        add(u, "show_description")
    eps = s.scalars(select(Episode).where(Episode.show_id == show_id, Episode.removed.is_(False))
                    .order_by(Episode.published_at.desc()).limit(max_episodes))
    for e in eps:
        for u in URL_RX.findall(e.description or ""):
            add(u, "episode_notes", e.id)
        for p in e.persons or []:
            if isinstance(p, dict) and p.get("href"):
                add(str(p["href"]), "podcast_person", e.id)
    return sorted(out.values(), key=lambda r: (["guest_application", "booking", "collaboration", "contact_page"].index(r["kind"]), r["url"]))[:5]


def record_routes(s: Session, show_id: str) -> list[dict]:
    routes = find_routes(s, show_id)
    rss = get_source(s, "rss", "rss")
    record(s, "show", show_id, "contact_routes", routes, source=rss, tier="verified", method="rule", confidence=0.9,
           source_ref=f"{len(routes)} declared contact/booking/guest route(s) in the feed text; e-mail addresses ignored")
    s.query(Evidence).filter(Evidence.entity_type == "show", Evidence.entity_id == show_id, Evidence.kind == "contact_routes").delete()
    for r in routes:
        snippet = f"{r['kind'].replace('_', ' ')}: {r['url']} (found in {r['found_in'].replace('_', ' ')})"
        add_evidence(s, "show", show_id, "contact_routes", snippet, {"url": r["url"], **({"episode_id": r["episode_id"]} if r.get("episode_id") else {})}, rss)
    return routes
