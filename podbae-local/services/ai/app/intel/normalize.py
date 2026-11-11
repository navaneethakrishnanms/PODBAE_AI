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


_WEAK_GUID = re.compile(r"^\s*(?:ep(?:isode)?|e|show|item|post)?[\s#._-]*\d{1,6}\s*$", re.I)


def is_strong_guid(g: str) -> bool:
    """Episode GUIDs like '12', 'ep-3' or 'episode 7' collide across unrelated shows. Only distinctive GUIDs
    (URLs, UUIDs, long opaque ids) count as identity evidence."""
    g = (g or "").strip()
    return len(g) >= 16 and not _WEAK_GUID.match(g)


def title_key(title: str | None) -> str:
    return re.sub(r"\W+", "", (title or "").lower())


def artwork_key(image_url: str | None) -> str | None:
    """Hash of the normalised artwork URL (no download). Mirrors of one show reference the same artwork file."""
    if not image_url:
        return None
    import hashlib
    return hashlib.sha256(url_key(image_url).encode()).hexdigest()[:32]


def _live_fact(s: Session, show_id: str, field: str):
    from .models import Provenance
    return s.scalar(select(Provenance.value_json).where(Provenance.entity_type == "show", Provenance.entity_id == show_id,
                                                         Provenance.field == field, Provenance.superseded_by.is_(None)).limit(1))


def same_title_signals(s: Session, cand_id: str, *, podcast_guid: str | None, itunes_id: str | None, podcastindex_id: str | None,
                       owner_hash: str | None, artwork: str | None, episode_guids: list[str]) -> tuple[list[str], bool]:
    """Strong signals that a same-title candidate is the SAME show. Returns (agreeing signals, hard_conflict).
    A hard conflict (two different podcast:guids / directory ids) forbids a merge whatever else agrees."""
    signals: list[str] = []
    conflict = False
    cand_aliases: dict[str, set[str]] = {}
    for kind, value in s.execute(select(ShowAlias.kind, ShowAlias.value).where(ShowAlias.show_id == cand_id)).all():
        cand_aliases.setdefault(kind, set()).add(value)
    for kind, mine, label in (("guid", podcast_guid, "same podcast:guid"), ("itunes_id", itunes_id, "same iTunes id"),
                              ("podcastindex_id", podcastindex_id, "same Podcast Index id")):
        theirs = cand_aliases.get(kind)
        if mine and theirs:
            if mine in theirs:
                signals.append(label)
            else:
                conflict = True
    oh = _live_fact(s, cand_id, "owner_email_hash")
    if owner_hash and oh and owner_hash == oh:
        signals.append("same owner (hashed e-mail)")
    art = _live_fact(s, cand_id, "artwork_key")
    if artwork and art and artwork == art:
        signals.append("same artwork")
    mine_strong = {g for g in episode_guids if is_strong_guid(g)}
    if len(mine_strong) >= 3:
        have = {g for g in s.scalars(select(Episode.guid).where(Episode.show_id == cand_id).limit(500)) if is_strong_guid(g)}
        if have:
            shared = len(have & mine_strong)
            if shared >= 3 and shared / min(len(have), len(mine_strong)) >= 0.5:
                signals.append(f"{shared} shared distinctive episode guids")
    return signals, conflict


def find_show(s: Session, *, urls: list[str], podcast_guid: str | None = None, podcastindex_id: str | None = None,
              itunes_id: str | None = None, title: str | None = None, episode_guids: list[str] | None = None,
              owner_hash: str | None = None, artwork: str | None = None) -> tuple[str | None, list[str]]:
    """Return (show_id or None, all other matching root ids that are duplicates to merge).
    Exact identifiers first (podcast:guid, Podcast Index id, iTunes id, URL key). Then the same-title rule: a show with
    the same normalised title is merged ONLY if a strong signal agrees (same podcast:guid / directory id, same owner
    hash, same artwork, or >=50% shared DISTINCTIVE episode guids) and no identifier conflicts."""
    hits: list[str] = []
    reasons: dict[str, str] = {}

    def add(kind: str, val: str | None) -> None:
        if val:
            sid = alias_lookup(s, kind, val)
            if sid:
                r = resolve_root(s, sid)
                if r not in hits:
                    hits.append(r)
                    reasons[r] = kind

    add("guid", podcast_guid)
    add("podcastindex_id", podcastindex_id)
    add("itunes_id", itunes_id)
    for u in urls:
        add("rss_url", url_key(u))
    if not hits and title:
        tkey = title_key(title)
        for sh in s.scalars(select(Show).where(Show.merged_into.is_(None))):
            if title_key(sh.title) != tkey:
                continue
            sig, conflict = same_title_signals(s, sh.id, podcast_guid=podcast_guid, itunes_id=itunes_id, podcastindex_id=podcastindex_id,
                                               owner_hash=owner_hash, artwork=artwork, episode_guids=episode_guids or [])
            if sig and not conflict:
                hits.append(sh.id)
                reasons[sh.id] = "same title + " + ", ".join(sig)
                break
            audit(s, "identity", "same_title_kept_separate", "show", sh.id,
                  {"reason": "identifier conflict" if conflict else "no strong signal agreed"})
    if not hits:
        return None, []
    keep = min(hits, key=lambda i: s.get(Show, i).created_at)
    s.info.setdefault("merge_reasons", {}).update(reasons)
    return keep, [h for h in hits if h != keep]
