"""Ingestion pipeline (jobs: ingest_rss, refresh_show, discover). Stages are idempotent and checkpointed so a job that
dies mid-run resumes where it stopped:  feed -> directory -> transcripts -> enrich -> embed."""
from __future__ import annotations

import hashlib
import time
from collections.abc import Callable
from datetime import datetime
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .connectors import directory as dirs
from .connectors import rss as rsslib
from .connectors.base import ConnectorResult, InvalidUrl, fetch_bytes, log_run, make_client, validate_url
from .db import session_scope
from .models import Episode, Provenance, Show, ShowClaim, Transcript, now
from .normalize import (add_alias, alias_lookup, artwork_key, detect_language, find_show, merge_shows, resolve_root, short_lang,
                        url_key)
from .trust import budget
from .trust.audit import audit
from .trust.jobs import JobContext, register
from .trust.provenance import get_source, live_rows, record, ttl_for
from .understanding.pipeline import understand_show   # Phase 1: rules + local models, no LLM
from .understanding.quality import transcript_quality
from .understanding.rules import compute_facts
from .vectors import upsert_embedding

# test seams ---------------------------------------------------------------------------------------------------
_client_factory: Callable[[], httpx.Client] = make_client
STAGE_HOOK: Callable[[str], None] | None = None      # tests raise SimulatedCrash here to kill a job mid-run


class SimulatedCrash(BaseException):
    """Not an Exception on purpose: it escapes the worker's retry handling exactly like a process kill would."""


def set_client_factory(f: Callable[[], httpx.Client]) -> None:
    global _client_factory
    _client_factory = f


def _stage_done(ctx: JobContext | None, name: str) -> None:
    if ctx is not None:
        ctx.mark(name)
    if STAGE_HOOK:
        STAGE_HOOK(name)


def _skip(ctx: JobContext | None, name: str) -> bool:
    return bool(ctx and ctx.done(name))


# ───────────────────────────── feed stage ─────────────────────────────
def _touch_fresh(s: Session, show_id: str, source_id: int) -> None:
    t = now()
    for r in s.scalars(select(Provenance).where(Provenance.entity_type == "show", Provenance.entity_id == show_id,
                                                Provenance.source_id == source_id, Provenance.superseded_by.is_(None))):
        r.fetched_at = t
        life = ttl_for(r.field)
        r.expires_at = (t + life) if life else None


def _upsert_episodes(s: Session, show: Show, pf: rsslib.ParsedFeed) -> dict:
    cfg = get_settings()
    existing = {e.guid: e for e in s.scalars(select(Episode).where(Episode.show_id == show.id))}
    t = now()
    added = changed = revived = 0
    seen: set[str] = set()
    for idx, pe in enumerate(pf.episodes):
        seen.add(pe.guid)
        h = pe.content_hash()
        ep = existing.get(pe.guid)
        lang = None
        if idx < cfg.deep_episodes and (ep is None or ep.content_hash != h):
            lang = detect_language(f"{pe.title}. {pe.description}")[0]
        if ep is None:
            s.add(Episode(show_id=show.id, guid=pe.guid, title=pe.title, description=pe.description, published_at=pe.published_at,
                          duration_sec=pe.duration_sec, explicit=pe.explicit, language=lang, audio_url=pe.audio_url,
                          transcript_url=pe.transcript_url, persons=pe.persons, content_hash=h))
            added += 1
        else:
            if ep.removed:
                ep.removed, ep.removed_at = False, None
                revived += 1
            if ep.content_hash != h:
                ep.title, ep.description, ep.published_at, ep.duration_sec = pe.title, pe.description, pe.published_at, pe.duration_sec
                ep.explicit, ep.audio_url, ep.transcript_url, ep.persons, ep.content_hash = pe.explicit, pe.audio_url, pe.transcript_url, pe.persons, h
                ep.language = lang or ep.language
                changed += 1
            ep.last_seen_at = t
    # deleted-from-feed episodes are marked removed (never hard-deleted), but only inside the window we can see
    dated = [e.published_at for e in pf.episodes if e.published_at]
    cutoff = min(dated) if dated else None
    removed = 0
    for guid, ep in existing.items():
        if guid in seen or ep.removed:
            continue
        if ep.published_at is None or cutoff is None or ep.published_at >= cutoff:
            ep.removed, ep.removed_at = True, t
            removed += 1
    s.flush()
    return {"added": added, "changed": changed, "removed": removed, "revived": revived, "in_feed": pf.total_items_in_feed,
            "stored_window": len(pf.episodes)}


def public_website(link: str | None) -> str | None:
    """A plain public http(s) URL from the feed's <link>, or None. Anything carrying an '@' (mailto, credentials) is dropped."""
    from urllib.parse import urlparse
    if not isinstance(link, str) or "@" in link:
        return None
    u = link.strip()
    p = urlparse(u)
    return u[:300] if p.scheme in ("http", "https") and p.netloc else None


def _write_feed_facts(s: Session, show: Show, pf: rsslib.ParsedFeed, ref: str) -> dict:
    rss = get_source(s, "rss", "rss", "Publisher RSS feed; public, fetched with conditional GET")
    lang_src = get_source(s, "langdetect", "local_model", "Local language detector; estimate only")
    rec = lambda f, v, tier="verified", method="parsed", src=rss, conf=1.0: record(  # noqa: E731
        s, "show", show.id, f, v, source=src, tier=tier, method=method, confidence=conf, source_ref=ref)
    rec("title", pf.title)
    rec("description", pf.description)
    if pf.categories:
        rec("categories", pf.categories)
    if pf.explicit is not None:
        rec("explicit", pf.explicit)
    if pf.author:
        rec("author", pf.author)
    site = public_website(pf.link)
    if site:   # Phase 2: the show's public website from <channel><link> (Layer 4 readiness). http(s) only, never mailto.
        rec("website", site)
    if pf.language:
        rec("language", short_lang(pf.language))
    live = list(s.scalars(select(Episode).where(Episode.show_id == show.id, Episode.removed.is_(False)).order_by(Episode.published_at.desc())))
    # language: declared tag verified; detected = estimated (kept side by side, resolver records any conflict)
    sample = f"{pf.title}. {pf.description} " + " ".join(e.title for e in live[:8])
    lang, prob = detect_language(sample)
    if lang:
        record(s, "show", show.id, "language", lang, source=lang_src, tier="estimated", method="model", confidence=round(prob, 2),
               source_ref="langdetect", model_version="langdetect-1.0")
    show.language = short_lang(pf.language) or lang
    persons = list(pf.persons)
    facts = compute_facts([e.published_at for e in live], [e.duration_sec for e in live], [e.title for e in live],
                          [e.persons for e in live], persons, pf.explicit)
    for f in ("episode_count", "last_published", "cadence_days", "avg_episode_minutes"):
        if facts[f] is not None:
            rec(f, facts[f], method="rule")
    if facts["hosts"]:
        rec("hosts", facts["hosts"])
    if facts["activity_status"]:
        rec("activity_status", facts["activity_status"], tier="estimated", method="rule", conf=0.8)
        show.activity = facts["activity_status"]
    gp = facts["guests_present"]
    if gp:
        person_based = gp["basis"].startswith("podcast:person")
        rec("guests_present", gp, tier="verified" if person_based else "inferred", method="parsed" if person_based else "rule",
            conf=1.0 if person_based else 0.5)
    n_tr = sum(1 for e in live if e.transcript_url)
    rec("transcripts_available", {"episodes_with_transcript": n_tr, "of": len(live)})
    rec("episodes", {"stored": len(live), "latest_guid": live[0].guid if live else None})
    return facts


def _write_identity_facts(s: Session, show: Show, pf: rsslib.ParsedFeed, directory: dict) -> None:
    """Identity helpers used by dedupe (never shown in the profile): artwork key, hashed owner e-mail, show type,
    plus the discovery directory's genres (estimated tier: a directory's classification, not the publisher's)."""
    rss = get_source(s, "rss", "rss", "Publisher RSS feed; public, fetched with conditional GET")
    if pf.image:
        record(s, "show", show.id, "image", pf.image, source=rss, tier="verified", method="parsed")
        record(s, "show", show.id, "artwork_key", artwork_key(pf.image), source=rss, tier="verified", method="parsed")
    if pf.owner_hash:
        record(s, "show", show.id, "owner_email_hash", pf.owner_hash, source=rss, tier="verified", method="parsed",
               source_ref="sha256(salt|owner e-mail); raw e-mail not stored")
    if pf.show_type:
        record(s, "show", show.id, "show_type", pf.show_type, source=rss, tier="verified", method="parsed")
    if directory.get("genres"):
        it = get_source(s, "itunes_search", "itunes", "Apple iTunes Search API (no key); directory metadata")
        record(s, "show", show.id, "directory_categories", [g for g in directory["genres"] if g != "Podcasts"], source=it,
               tier="estimated", method="api", confidence=0.8, source_ref=f"itunes:{directory.get('itunes_id')}")


def stage_feed(s: Session, url: str, user_id: str | None, *, force: bool = False, directory: dict | None = None) -> dict:
    """`directory` = optional metadata from the discovery source (iTunes Search): itunes_id, genres, artist."""
    directory = directory or {}
    itunes_id = str(directory["itunes_id"]) if directory.get("itunes_id") else None
    validate_url(url)
    rss = get_source(s, "rss", "rss", "Publisher RSS feed; public, fetched with conditional GET")
    existing_id, _ = find_show(s, urls=[url], itunes_id=itunes_id)
    show = s.get(Show, existing_id) if existing_id else None
    with _client_factory() as client:
        out = rsslib.fetch_feed(client, url, etag=None if force or show is None else show.etag,
                                last_modified=None if force or show is None else show.last_modified)
    if out.status == "error":
        if show is None:
            # committed in its own transaction: the caller's session rolls back when we raise, and the failure reason
            # must survive (it feeds the feed-failure table)
            with session_scope() as s2:
                log_run(s2, out.result, rsslib.EXPECTED_FIELDS, None)
            raise RuntimeError(f"could not fetch feed: {out.result.error}")
        log_run(s, out.result, rsslib.EXPECTED_FIELDS, show.id)
        show.last_fetch_at, show.last_fetch_ok, show.last_fetch_error = now(), False, out.result.error
        audit(s, "ingest", "fetch_failed_serving_cached", "show", show.id, {"error": out.result.error})
        return {"status": "offline_serving_cached", "show_id": show.id, "error": out.result.error}
    if out.status == "not_modified":
        assert show is not None
        log_run(s, out.result, rsslib.EXPECTED_FIELDS, show.id)
        show.last_fetch_at, show.last_fetch_ok, show.last_fetch_error = now(), True, None
        _touch_fresh(s, show.id, rss.id)
        budget.charge(s, "rss_fetch", "rss", 0, 0, podcast_id=show.id, cache_hit=True, note="304 not modified")
        return {"status": "not_modified", "show_id": show.id}

    pf = out.feed
    assert pf is not None
    urls = [u for u in (url, out.final_url, out.permanent_redirect_to, pf.new_feed_url) if u]
    keep, dups = find_show(s, urls=urls, podcast_guid=pf.podcast_guid, itunes_id=itunes_id, title=pf.title,
                           episode_guids=[e.guid for e in pf.episodes[:50]], owner_hash=pf.owner_hash, artwork=artwork_key(pf.image))
    if keep is None:
        canonical = pf.new_feed_url or out.permanent_redirect_to or out.final_url or url
        show = Show(canonical_feed_url=canonical, title=pf.title)
        s.add(show)
        s.flush()
        created = True
    else:
        show = s.get(Show, keep)
        created = False
        why = (s.info.get("merge_reasons") or {})
        for d in dups:
            merge_shows(s, keep, d, why.get(d) or why.get(keep) or "same feed identity")
        if pf.new_feed_url and url_key(pf.new_feed_url) != url_key(show.canonical_feed_url):
            audit(s, "identity", "feed_url_changed", "show", show.id, {"from": show.canonical_feed_url, "to": pf.new_feed_url})
            show.canonical_feed_url = pf.new_feed_url
        elif out.permanent_redirect_to and url_key(out.permanent_redirect_to) != url_key(show.canonical_feed_url):
            show.canonical_feed_url = out.final_url or out.permanent_redirect_to
    for u in urls:
        add_alias(s, show.id, "rss_url", url_key(u))
    add_alias(s, show.id, "guid", pf.podcast_guid)
    if itunes_id:
        add_alias(s, show.id, "itunes_id", itunes_id)
    show.title = pf.title or show.title
    show.etag, show.last_modified, show.content_hash = out.etag, out.last_modified, out.body_hash
    show.last_fetch_at, show.last_fetch_ok, show.last_fetch_error = now(), True, None
    ep_stats = _upsert_episodes(s, show, pf)
    facts = _write_feed_facts(s, show, pf, ref=show.canonical_feed_url)
    _write_identity_facts(s, show, pf, directory)
    log_run(s, out.result, rsslib.EXPECTED_FIELDS, show.id)
    budget.charge(s, "rss_fetch", "rss", 1, 0.0, podcast_id=show.id, note=f"{out.result.duration_ms}ms")
    if user_id and not s.scalar(select(ShowClaim.id).where(ShowClaim.show_id == show.id, ShowClaim.user_id == user_id)):
        s.add(ShowClaim(show_id=show.id, user_id=user_id))
    audit(s, "ingest", "show_created" if created else "show_updated", "show", show.id, {"episodes": ep_stats})
    return {"status": "ok", "show_id": show.id, "created": created, "episodes": ep_stats, "malformed_xml": pf.malformed,
            "activity": facts["activity_status"]}


# ───────────────────────────── directory stage (Podcast Index / Taddy) ─────────────────────────────
def stage_directory(s: Session, show_id: str) -> dict:
    cfg = get_settings()
    show = s.get(Show, show_id)
    out: dict[str, Any] = {}
    with _client_factory() as client:
        pi = dirs.PodcastIndex(client)
        if pi.available:
            dec = budget.check(s, 0.0, podcast_id=show_id)
            if dec.ok:
                res = pi.lookup(feed_url=show.canonical_feed_url)
                log_run(s, res, dirs.PodcastIndex.expected_fields, show_id)
                budget.charge(s, "podcastindex_call", "podcastindex", 1, 0.0, podcast_id=show_id, note="free tier")
                f = res.fields
                if f:
                    src = get_source(s, "podcastindex", "podcastindex", "Podcast Index API; free key, attribute")
                    for kind, key in (("podcastindex_id", "podcastindex_id"), ("itunes_id", "itunes_id"), ("guid", "podcast_guid")):
                        if f.get(key):
                            other = alias_lookup(s, kind, str(f[key]))
                            other = resolve_root(s, other) if other else None
                            if other and other != show_id:  # directory proves two feeds are one show: collapse into the older
                                a, b = s.get(Show, show_id), s.get(Show, other)
                                keep, drop = (a, b) if a.created_at <= b.created_at else (b, a)
                                merge_shows(s, keep.id, drop.id, f"directory {kind} match")
                                show_id = keep.id
                            add_alias(s, show_id, kind, str(f[key]))
                    out["show_id"] = show_id
                    if f.get("categories"):
                        record(s, "show", show_id, "directory_categories", f["categories"], source=src, tier="estimated", method="api",
                               confidence=0.7, source_ref="podcastindex")
                    out["podcastindex"] = res.fields_returned
            else:
                budget.skip(s, "podcastindex_call", "podcastindex", dec.reason or "budget", show_id)
        tad = dirs.Taddy(client)
        if tad.available:
            dec = budget.check(s, cfg.cost_taddy_request, podcast_id=show_id)
            if dec.ok:
                res = tad.lookup(show.canonical_feed_url)
                log_run(s, res, dirs.Taddy.expected_fields, show_id)
                budget.charge(s, "taddy_call", "taddy", 1, cfg.cost_taddy_request, podcast_id=show_id, note="estimate")
                out["taddy"] = res.fields_returned
            else:
                budget.skip(s, "taddy_call", "taddy", dec.reason or "budget", show_id)
    return out


# ───────────────────────────── transcripts stage ─────────────────────────────
def stage_transcripts(s: Session, show_id: str) -> dict:
    """Provided transcripts only (podcast:transcript). Never generated here; Whisper is a separate opt-in job."""
    cfg = get_settings()
    eps = list(s.scalars(select(Episode).where(Episode.show_id == show_id, Episode.removed.is_(False), Episode.transcript_url.is_not(None))
                         .order_by(Episode.published_at.desc()).limit(cfg.transcript_episodes)))
    got = low = 0
    with _client_factory() as client:
        for ep in eps:
            cur = s.get(Transcript, ep.id)
            if cur is not None and cur.url == ep.transcript_url:
                continue
            try:
                resp, body = fetch_bytes(client, ep.transcript_url, max_bytes=cfg.max_transcript_bytes)
                if resp.status_code >= 400:
                    continue
                text_, fmt = rsslib.parse_transcript(body, resp.headers.get("content-type"), None)
            except (httpx.HTTPError, InvalidUrl, Exception):  # noqa: BLE001,B014 - transcripts are best-effort
                continue
            q = transcript_quality(text_, ep.duration_sec)
            s.merge(Transcript(episode_id=ep.id, url=ep.transcript_url, fmt=fmt, text=text_[:200_000], word_count=q["words"], quality=q,
                               origin="provided"))
            budget.charge(s, "transcript_fetch", "rss-transcript", len(body), 0.0, podcast_id=show_id)
            got += 1
            low += int(not q["usable"])
    return {"fetched": got, "low_quality": low}


# ───────────────────────────── embed stage ─────────────────────────────
def content_text(s: Session, show: Show) -> str:
    desc = live_rows(s, "show", show.id, "description")
    eps = list(s.scalars(select(Episode).where(Episode.show_id == show.id, Episode.removed.is_(False)).order_by(Episode.published_at.desc()).limit(15)))
    parts = [show.title or "", (desc[0].value_json if desc else "")[:1500], "Episodes: " + "; ".join(e.title for e in eps)]
    parts += [e.description[:200] for e in eps[:5]]
    return "\n".join(p for p in parts if p)


def style_text(s: Session, show_id: str) -> str | None:
    """LEGACY (Layer 1): short comma-joined vibe/tone/style labels that were text-embedded for style similarity.
    Kept only so the Phase 1 eval can measure the old method; no longer used by the pipeline (see Step 5)."""
    def val(f: str) -> Any:
        r = live_rows(s, "show", show_id, f)
        return r[0].value_json if r else None
    vibe, tone, style, values = val("vibe"), val("tone"), val("conversational_style"), val("values")
    if not vibe:
        return None
    # No boilerplate labels: a shared template makes every style vector near-identical (measured cosine 0.99 across unrelated shows).
    ranked = [k for k, v in sorted(vibe.items(), key=lambda kv: -kv[1]) if v > 0][:4]
    weighted = [t for k in ranked for t in [k] * (2 if vibe[k] >= 0.75 else 1)]
    parts = weighted + list(tone or []) + [(style or "mixed").replace("_", " ")] + [v.replace("_", " ") for v in (values or [])]
    return ", ".join(parts) or "unspecified"


def stage_embed(s: Session, show_id: str) -> dict:
    show = s.get(Show, show_id)
    res = {"content": upsert_embedding(s, "show", show_id, "content", content_text(s, show), podcast_id=show_id)}
    # style vectors are numeric now and written by the understanding stage (understanding/pipeline.py + calibration.py)
    n = 0
    for tr in s.scalars(select(Transcript).join(Episode, Episode.id == Transcript.episode_id).where(Episode.show_id == show_id)
                        .order_by(Episode.published_at.desc()).limit(3)):
        if not tr.quality.get("usable"):
            continue
        words = tr.text.split()
        for i in range(0, min(len(words), 2000), 200):
            upsert_embedding(s, "chunk", f"{tr.episode_id}:{i // 200}", "chunks", " ".join(words[i:i + 200]), podcast_id=show_id)
            n += 1
    res["chunks"] = n
    return res


# ───────────────────────────── orchestration ─────────────────────────────
def run_pipeline(url: str, user_id: str | None = None, ctx: JobContext | None = None, *, force: bool = False,
                 directory: dict | None = None) -> dict:
    t0 = time.perf_counter()
    result: dict[str, Any] = (ctx.checkpoint.get("_result") if ctx else None) or {}
    if not _skip(ctx, "feed"):
        with session_scope() as s:
            result["feed"] = stage_feed(s, url, user_id, force=force, directory=directory)
        result["show_id"] = result["feed"]["show_id"]
        if ctx:
            ctx.checkpoint["_result"] = result
        _stage_done(ctx, "feed")
    show_id = result["show_id"]
    for name, fn in (("directory", stage_directory), ("transcripts", stage_transcripts), ("enrich", understand_show), ("embed", stage_embed)):
        if _skip(ctx, name):
            continue
        with session_scope() as s:
            result[name] = fn(s, show_id)
        if isinstance(result[name], dict) and result[name].get("show_id"):
            show_id = result["show_id"] = result[name]["show_id"]
        if ctx:
            ctx.checkpoint["_result"] = result
        _stage_done(ctx, name)
    result["seconds"] = round(time.perf_counter() - t0, 3)
    return result


@register("ingest_rss")
def job_ingest_rss(ctx: JobContext) -> dict:
    return run_pipeline(ctx.payload["rss_url"], ctx.payload.get("user_id"), ctx, force=bool(ctx.payload.get("force")),
                        directory=ctx.payload.get("directory"))


@register("refresh_show")
def job_refresh(ctx: JobContext) -> dict:
    with session_scope() as s:
        show = s.get(Show, ctx.payload["show_id"])
        url = show.canonical_feed_url
    return run_pipeline(url, ctx.payload.get("user_id"), ctx, force=bool(ctx.payload.get("force")))


@register("discover")
def job_discover(ctx: JobContext) -> dict:
    """Find feeds via Podcast Index (if keyed) else iTunes Search, then enqueue one idempotent ingest job per feed."""
    from .trust.jobs import enqueue
    q, limit = ctx.payload.get("query") or ctx.payload.get("category"), int(ctx.payload.get("limit", 25))
    with session_scope() as s:
        with _client_factory() as client:
            pi = dirs.PodcastIndex(client)
            provider = "podcastindex" if pi.available else "itunes_search"
            dec = budget.check(s, 0.0)
            if not dec.ok:
                budget.skip(s, "discover", provider, dec.reason or "budget")
                return {"skipped": dec.reason}
            if pi.available:
                feeds = pi.search(q, limit)
            else:
                try:
                    feeds = dirs.ITunesSearch(client).search(q, limit)
                except httpx.HTTPError:           # iTunes unreachable (some networks block it): public gPodder directory instead
                    provider, feeds = "gpodder_search", dirs.GPodderSearch(client).search(q, limit)
            budget.charge(s, "discover", provider, 1, 0.0, note=f"q={q!r} -> {len(feeds)} feeds")
        queued = 0
        for f in feeds[:limit]:
            if f.get("feed_url"):
                directory = {"itunes_id": f.get("itunes_id"), "genres": f.get("categories") or [], "artist": f.get("author")} \
                    if provider == "itunes_search" else None
                enqueue(s, "ingest_rss", f"ingest_rss:{url_key(f['feed_url'])}", {"rss_url": f["feed_url"], "user_id": None,
                                                                                    "directory": directory})
                queued += 1
    return {"provider": provider, "found": len(feeds), "queued": queued}
