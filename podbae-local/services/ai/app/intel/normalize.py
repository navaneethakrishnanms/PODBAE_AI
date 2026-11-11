"""Normalization + identity: URL keys, language detection, inactivity detection, canonical show identity."""
from __future__ import annotations

import re
import statistics
from datetime import datetime
from urllib.parse import parse_qsl, urlencode, urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Episode, Show, ShowAlias, now
from .trust.audit import audit

_TRACKING = re.compile(r"^(utm_|fbclid|gclid|mc_|ref$)", re.I)


def url_key(url: str) -> str:
    """Identity key for a feed URL: scheme-insensitive (http==https), no www., no default port/fragment/trailing
    slash/tracking params, lower-cased host."""
    p = urlsplit(url.strip())
    host = (p.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    port = f":{p.port}" if p.port and p.port not in (80, 443) else ""
    path = re.sub(r"/{2,}", "/", p.path or "/")
    if len(path) > 1:
        path = path.rstrip("/")
    q = urlencode(sorted((k, v) for k, v in parse_qsl(p.query, keep_blank_values=True) if not _TRACKING.match(k)))
    return f"{host}{port}{path}" + (f"?{q}" if q else "")


# ───────────────────────────── language ─────────────────────────────
_lang_ready = False


def detect_language(text: str, min_chars: int = 40) -> tuple[str | None, float]:
    """Returns (iso639-1 code, probability). langdetect is lightweight; seeded for determinism."""
    global _lang_ready
    t = re.sub(r"https?://\S+|\S+@\S+", " ", text or "")
    t = re.sub(r"\s+", " ", t).strip()
    if len(t) < min_chars:
        return None, 0.0
    from langdetect import DetectorFactory, detect_langs
    if not _lang_ready:
        DetectorFactory.seed = 0
        _lang_ready = True
    try:
        best = detect_langs(t[:3000])[0]
        return best.lang.split("-")[0], float(best.prob)
    except Exception:  # noqa: BLE001 - LangDetectException on odd input
        return None, 0.0


def short_lang(tag: str | None) -> str | None:
    return tag.split("-")[0].split("_")[0].lower() if tag else None


# ───────────────────────────── activity / cadence ─────────────────────────────
def cadence_stats(dates: list[datetime]) -> dict:
    ds = sorted({d for d in dates if d}, reverse=True)
    out: dict = {"n_dated": len(ds), "median_gap_days": None, "last_published": ds[0] if ds else None}
    if len(ds) >= 2:
        gaps = [(a - b).total_seconds() / 86400 for a, b in zip(ds, ds[1:]) if a != b]
        gaps = gaps[:30]
        if gaps:
            out["median_gap_days"] = round(statistics.median(gaps), 2)
    return out


def activity_status(dates: list[datetime], at: datetime | None = None) -> str | None:
    """active / slowing / inactive from publishing gaps. None = cannot tell (no dated episodes)."""
    st = cadence_stats(dates)
    last = st["last_published"]
    if last is None:
        return None
    at = at or now()
    age = (at - last).total_seconds() / 86400
    g = st["median_gap_days"] or 14.0
    if age > max(90.0, 5 * g):
        return "inactive"
    if age > max(30.0, 2.5 * g):
        return "slowing"
    return "active"


# ───────────────────────────── identity ─────────────────────────────
def alias_lookup(s: Session, kind: str, value: str) -> str | None:
    return s.scalar(select(ShowAlias.show_id).where(ShowAlias.kind == kind, ShowAlias.value == value))


def add_alias(s: Session, show_id: str, kind: str, value: str | None) -> bool:
    if not value:
        return False
    cur = s.scalar(select(ShowAlias).where(ShowAlias.kind == kind, ShowAlias.value == value))
    if cur is not None:
        return cur.show_id == show_id
    s.add(ShowAlias(show_id=show_id, kind=kind, value=value))
    s.flush()
    return True


def resolve_root(s: Session, show_id: str) -> str:
    seen = set()
    while show_id not in seen:
        seen.add(show_id)
        sh = s.get(Show, show_id)
        if sh is None or not sh.merged_into:
            return show_id
        show_id = sh.merged_into
    return show_id


def merge_shows(s: Session, keep_id: str, drop_id: str, reason: str) -> None:
    """Collapse a duplicate show into the older canonical one. Aliases and non-duplicate episodes move over."""
    if keep_id == drop_id:
        return
    keep_guids = set(s.scalars(select(Episode.guid).where(Episode.show_id == keep_id)))
    for ep in s.scalars(select(Episode).where(Episode.show_id == drop_id)):
        if ep.guid in keep_guids:
            s.delete(ep)
        else:
            ep.show_id = keep_id
    for al in s.scalars(select(ShowAlias).where(ShowAlias.show_id == drop_id)):
        al.show_id = keep_id
    s.get(Show, drop_id).merged_into = keep_id
    audit(s, "identity", "merge_shows", "show", keep_id, {"dropped": drop_id, "reason": reason})
    s.flush()


def find_show(s: Session, *, urls: list[str], podcast_guid: str | None = None, podcastindex_id: str | None = None,
              itunes_id: str | None = None, title: str | None = None, episode_guids: list[str] | None = None) -> tuple[str | None, list[str]]:
    """Return (show_id or None, all other matching root ids that are duplicates to merge).
    Order: podcast:guid, podcastindex id, itunes id, URL key; finally (title + >=50% episode-guid overlap)."""
    hits: list[str] = []

    def add(kind: str, val: str | None) -> None:
        if val:
            sid = alias_lookup(s, kind, val)
            if sid:
                r = resolve_root(s, sid)
                if r not in hits:
                    hits.append(r)

    add("guid", podcast_guid)
    add("podcastindex_id", podcastindex_id)
    add("itunes_id", itunes_id)
    for u in urls:
        add("rss_url", url_key(u))
    if not hits and title and episode_guids and len(episode_guids) >= 3:
        tkey = re.sub(r"\W+", "", title.lower())
        wanted = set(episode_guids)
        for sh in s.scalars(select(Show).where(Show.merged_into.is_(None))):
            if re.sub(r"\W+", "", (sh.title or "").lower()) != tkey:
                continue
            have = set(s.scalars(select(Episode.guid).where(Episode.show_id == sh.id).limit(500)))
            if have and len(have & wanted) / min(len(have), len(wanted)) >= 0.5:
                hits.append(sh.id)
                break
    if not hits:
        return None, []
    keep = min(hits, key=lambda i: s.get(Show, i).created_at)
    return keep, [h for h in hits if h != keep]
