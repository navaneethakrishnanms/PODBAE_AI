"""The deliverable: the Podcast Intelligence Profile. Every field carries value, data_tier, source, fetched_at,
freshness, confidence and evidence refs. Missing data is reported as missing; nothing is invented."""
from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import Episode, Evidence, Provenance, Show, Source, now
from .normalize import resolve_root
from .trust import jobs
from .trust.provenance import freshness, live_rows, resolve

# (field, group, weight, label)
FIELDS: list[tuple[str, str, int, str]] = [
    ("title", "identity", 4, "Title"), ("description", "identity", 4, "Description"), ("language", "identity", 3, "Language"),
    ("categories", "identity", 3, "Categories"), ("explicit", "identity", 1, "Explicit flag"), ("hosts", "identity", 3, "Hosts"),
    ("episode_count", "activity", 3, "Episode count"), ("last_published", "activity", 4, "Last published"),
    ("cadence_days", "activity", 4, "Publishing cadence (days)"), ("avg_episode_minutes", "activity", 3, "Average episode length (min)"),
    ("activity_status", "activity", 3, "Activity status"), ("guests_present", "activity", 3, "Guests present"),
    ("transcripts_available", "activity", 2, "Transcripts available"),
    ("topics", "content", 6, "Topics"), ("vibe", "content", 6, "Vibe scores"), ("tone", "content", 3, "Tone"),
    ("conversational_style", "content", 3, "Conversational style"), ("values", "content", 3, "Values"),
    ("guest_friendliness", "content", 2, "Guest-friendliness"), ("brand_safety_flags", "content", 3, "Brand-safety flags"),
    ("likely_audience", "content", 2, "Likely audience (interests only)"),
    ("audience.totals", "audience", 7, "Audience totals (creator analytics)"), ("audience.top_countries", "audience", 6, "Top countries"),
    ("audience.top_cities", "audience", 4, "Top cities"), ("audience.age_bands", "audience", 6, "Age bands"),
    ("creator.goals", "creator", 4, "Creator goals"), ("creator.collaboration_openness", "creator", 3, "Collaboration openness"),
    ("creator.blocked_categories", "creator", 2, "Blocked categories"),
]
TOTAL_WEIGHT = sum(w for _, _, w, _ in FIELDS)
TIER_LABEL = {"verified": "Verified", "creator_provided": "Creator-provided", "estimated": "Estimated", "inferred": "AI-inferred"}
LOW_CONF = 0.35


def _evidence(s: Session, show_id: str, field: str) -> list[dict]:
    rows = s.scalars(select(Evidence).where(Evidence.entity_type == "show", Evidence.entity_id == show_id, Evidence.kind == field).limit(5))
    return [{"id": e.id, "snippet": e.snippet, "locator": e.locator} for e in rows]


def _iso(d) -> str | None:
    return d.isoformat() + "Z" if d else None


def field_view(s: Session, show_id: str, field: str, sources: dict[int, Source]) -> dict | None:
    rows = live_rows(s, "show", show_id, field)
    win, others = resolve(s, rows)
    if win is None:
        return None
    src = sources[win.source_id]
    fr = freshness(win)
    return {
        "value": win.value_json, "data_tier": win.data_tier, "tier_label": TIER_LABEL[win.data_tier],
        "source": {"name": src.name, "kind": src.kind}, "source_ref": win.source_ref, "method": win.method,
        "model_version": win.model_version, "fetched_at": _iso(win.fetched_at), "expires_at": _iso(win.expires_at),
        "freshness": fr, "confidence": win.confidence, "low_confidence": win.confidence < LOW_CONF,
        "evidence": _evidence(s, show_id, field),
        "alternatives": [{"value": o.value_json, "data_tier": o.data_tier, "source": sources[o.source_id].name,
                          "fetched_at": _iso(o.fetched_at)} for o in others],
        "conflict": any(o.value_json != win.value_json for o in others),
        "provenance_id": win.id,
    }


def build_profile(s: Session, show_id: str, *, enqueue_refresh: bool = True) -> dict | None:
    show_id = resolve_root(s, show_id)
    show = s.get(Show, show_id)
    if show is None:
        return None
    sources = {x.id: x for x in s.scalars(select(Source))}
    fields: dict[str, dict] = {}
    missing: list[dict] = []
    credit = 0.0
    stale: list[str] = []
    for f, group, weight, label in FIELDS:
        v = field_view(s, show_id, f, sources)
        if v is None:
            missing.append({"field": f, "label": label, "group": group})
            continue
        v["label"], v["group"] = label, group
        fields[f] = v
        part = 0.5 if v["freshness"] == "stale" else 1.0
        part *= 0.6 if v["low_confidence"] else 1.0
        credit += weight * part
        if v["freshness"] == "stale":
            stale.append(f)
    n_eps = s.scalar(select(func.count()).select_from(Episode).where(Episode.show_id == show_id, Episode.removed.is_(False))) or 0
    preliminary = n_eps < 3
    completeness = round(100 * credit / TOTAL_WEIGHT, 1)

    warnings: list[dict] = []
    if show.last_fetch_ok is False:
        warnings.append({"code": "feed_unreachable", "message": f"The RSS feed could not be fetched ({show.last_fetch_error}). "
                         f"Showing the last cached data from {_iso(show.last_fetch_at)}.", "severity": "warning"})
    if stale:
        warnings.append({"code": "stale_fields", "message": f"{len(stale)} field(s) are past their freshness window and are flagged as stale: "
                         + ", ".join(stale[:8]), "severity": "info", "fields": stale})
    if preliminary:
        warnings.append({"code": "preliminary", "message": f"Only {n_eps} episode(s) so far: this profile is preliminary and will change as episodes are added.",
                         "severity": "info"})
    if show.activity in ("slowing", "inactive"):
        warnings.append({"code": f"show_{show.activity}", "message": f"This show looks {show.activity} based on its publishing gaps.", "severity": "info"})
    low = [f for f, v in fields.items() if v["low_confidence"]]
    if low:
        warnings.append({"code": "low_confidence", "message": "Low-confidence fields: " + ", ".join(low[:8]), "severity": "info", "fields": low})

    improve: list[dict] = []
    has_aud = any(k.startswith("audience.") for k in fields)
    if not has_aud:
        improve.append({"code": "upload_audience", "gain_points": 23, "action": "Upload audience analytics",
                        "detail": "A CSV export (countries, cities, age bands, totals) is the only way to get VERIFIED audience data. We never guess it."})
    if "creator.goals" not in fields:
        improve.append({"code": "declare_goals", "gain_points": 6, "action": "Declare your goals and collaboration openness",
                        "detail": "Self-declared fields are stored as creator-provided."})
    tr = (fields.get("transcripts_available") or {}).get("value") or {}
    if not tr.get("episodes_with_transcript"):
        improve.append({"code": "add_transcript_feed", "gain_points": 3, "action": "Add a transcript feed",
                        "detail": "Publish <podcast:transcript> links in your RSS so topic and tone can be backed by quotes from your episodes."})
    if preliminary:
        improve.append({"code": "add_episodes", "gain_points": 4, "action": "Publish more episodes", "detail": "Three or more episodes make the profile reliable."})
    if "hosts" not in fields:
        improve.append({"code": "add_person_tags", "gain_points": 3, "action": "Add <podcast:person> tags for hosts and guests",
                        "detail": "Lets us verify who hosts and who appears as a guest."})
    if show.last_fetch_ok is False:
        improve.append({"code": "fix_feed", "gain_points": 5, "action": "Check your RSS feed URL", "detail": "We could not reach the feed on the last refresh."})
    if stale:
        improve.append({"code": "refresh", "gain_points": 2, "action": "Refresh stale data", "detail": "A refresh job has been queued automatically."})

    refresh_job = None
    if stale and enqueue_refresh:
        j = jobs.enqueue(s, "refresh_show", f"refresh:{show_id}:{now().date().isoformat()}", {"show_id": show_id})
        refresh_job = {"id": j.id, "status": j.status}

    sec = {g: round(100 * sum(w for f, gg, w, _ in FIELDS if gg == g and f in fields) / max(1, sum(w for _, gg, w, _ in FIELDS if gg == g)))
           for g in ("identity", "activity", "content", "audience", "creator")}
    return {
        "show_id": show_id, "title": show.title, "feed_url": show.canonical_feed_url,
        "status": "preliminary" if preliminary else "complete" if completeness >= 80 else "partial",
        "completeness": {"score": completeness, "by_group": sec, "max": 100},
        "fields": fields, "missing": missing, "improve": sorted(improve, key=lambda x: -x["gain_points"]),
        "warnings": warnings, "refresh_job": refresh_job,
        "feed": {"last_fetch_at": _iso(show.last_fetch_at), "last_fetch_ok": show.last_fetch_ok, "last_error": show.last_fetch_error},
        "generated_at": _iso(now()),
        "trust_note": "Verified = read directly from the publisher's RSS or analytics you uploaded. AI-inferred values are model guesses with "
                      "quotes as evidence and are never used for audience facts.",
    }


def summary_row(s: Session, show: Show, prov: dict[str, Any]) -> dict:
    g = lambda f: prov.get(f)  # noqa: E731
    return {"id": show.id, "title": show.title, "language": show.language, "activity": show.activity,
            "categories": g("categories") or g("directory_categories") or [], "episode_count": g("episode_count"),
            "last_published": g("last_published"), "description": (g("description") or "")[:240], "feed_url": show.canonical_feed_url,
            "data_tier": "verified", "source": "rss", "last_fetch_at": _iso(show.last_fetch_at), "last_fetch_ok": show.last_fetch_ok}
