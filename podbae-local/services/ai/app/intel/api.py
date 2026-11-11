"""/v1 HTTP API of the intelligence service. The Node API and the web app reach intelligence ONLY through this."""
from __future__ import annotations

import json
import time
from datetime import datetime
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text

from . import audience as aud
from . import profile as prof
from .config import get_settings
from .connectors.base import InvalidUrl, validate_url
from .db import get_engine, session_scope
from .models import ConnectorRun, Episode, Job, Provenance, Show, ShowClaim, now
from .normalize import find_show, resolve_root, url_key
from .trust import budget, jobs
from .understanding.providers import provider_status
from .vectors import embedder_status, similar
from .whisper_job import NotAllowed, check_allowed

router = APIRouter(prefix="/v1")


class IngestRss(BaseModel):
    rss_url: str
    user_id: str | None = None
    force: bool = False


class Discover(BaseModel):
    query: str | None = None
    category: str | None = None
    limit: int = Field(default=25, ge=1, le=100)


class CreatorProfile(BaseModel):
    user_id: str | None = None
    goals: list[str] | None = Field(default=None, max_length=10)
    collaboration_openness: str | None = Field(default=None, pattern="^(open|selective|closed)$")
    blocked_categories: list[str] | None = Field(default=None, max_length=20)


class Transcribe(BaseModel):
    user_id: str | None = None
    opt_in: bool = False


STAGES = ["feed", "directory", "transcripts", "enrich", "embed"]


def _job_view(j: Job) -> dict:
    done = [st for st in STAGES if (j.checkpoint or {}).get(st)]
    pct = 100 if j.status == "succeeded" else int(100 * len(done) / len(STAGES)) if j.type in ("ingest_rss", "refresh_show") else (0 if j.status == "queued" else 50)
    res = j.result or {}
    return {"id": j.id, "type": j.type, "status": j.status, "attempts": j.attempts, "max_attempts": j.max_attempts, "last_error": j.last_error,
            "stages_done": done, "stages": STAGES if j.type in ("ingest_rss", "refresh_show") else [], "percent": pct,
            "show_id": res.get("show_id") or (j.checkpoint or {}).get("_result", {}).get("show_id"),
            "result": j.result, "created_at": j.created_at.isoformat() + "Z", "updated_at": j.updated_at.isoformat() + "Z"}


@router.post("/ingest/rss", status_code=202)
def ingest_rss(body: IngestRss) -> dict:
    try:
        url = validate_url(body.rss_url)
    except InvalidUrl as exc:
        raise HTTPException(422, f"invalid rss_url: {exc}") from exc
    bucket = int(time.time() // 600)  # dedupe rapid repeats per canonical feed; later re-runs are allowed
    with session_scope() as s:
        sid, _ = find_show(s, urls=[url])
        ident = f"show:{sid}" if sid else f"url:{url_key(url)}"
        j = jobs.enqueue(s, "ingest_rss", f"ingest_rss:{ident}:{'force' if body.force else ''}:{bucket}",
                         {"rss_url": url, "user_id": body.user_id, "force": body.force})
        return {"job_id": j.id, "status": j.status, "show_id": sid}


@router.post("/ingest/discover", status_code=202)
def ingest_discover(body: Discover) -> dict:
    if not (body.query or body.category):
        raise HTTPException(422, "provide query or category")
    key = f"discover:{(body.query or body.category or '').lower()}:{body.limit}:{now().date().isoformat()}"
    with session_scope() as s:
        j = jobs.enqueue(s, "discover", key, body.model_dump())
        return {"job_id": j.id, "status": j.status}


@router.get("/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    with session_scope() as s:
        j = s.get(Job, job_id)
        if j is None:
            raise HTTPException(404, "job not found")
        return _job_view(j)


def _prov_map(s, fields: list[str]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for r in s.scalars(select(Provenance).where(Provenance.entity_type == "show", Provenance.field.in_(fields), Provenance.superseded_by.is_(None))):
        out.setdefault(r.entity_id, {}).setdefault(r.field, r.value_json)
    return out


@router.get("/shows")
def list_shows(q: str | None = None, category: str | None = None, language: str | None = None, activity: str | None = None,
               limit: int = Query(24, ge=1, le=100), offset: int = Query(0, ge=0)) -> dict:
    with session_scope() as s:
        query = select(Show).where(Show.merged_into.is_(None))
        if language:
            query = query.where(Show.language == language.lower())
        if activity:
            query = query.where(Show.activity == activity)
        if q:
            query = query.where(func.lower(Show.title).contains(q.lower()))
        shows = list(s.scalars(query.order_by(Show.title)))
        pm = _prov_map(s, ["categories", "directory_categories", "episode_count", "last_published", "description"])
        rows = [prof.summary_row(s, sh, pm.get(sh.id, {})) for sh in shows]
        if category:
            c = category.lower()
            rows = [r for r in rows if any(c in str(x).lower() for x in r["categories"])]
        if q:  # also match description text
            ql = q.lower()
            seen = {r["id"] for r in rows}
            rows += [prof.summary_row(s, sh, pm.get(sh.id, {})) for sh in shows if sh.id not in seen and ql in (pm.get(sh.id, {}).get("description") or "").lower()
                     and (not category or True)]
        total = len(rows)
        return {"total": total, "limit": limit, "offset": offset, "shows": rows[offset: offset + limit]}


@router.get("/shows/by-feed")
def show_by_feed(url: str) -> dict:
    with session_scope() as s:
        sid, _ = find_show(s, urls=[url])
        if not sid:
            raise HTTPException(404, "no show ingested for that feed")
        return {"show_id": sid}


def _require_show(s, show_id: str) -> str:
    root = resolve_root(s, show_id)
    if s.get(Show, root) is None:
        raise HTTPException(404, "show not found")
    return root


@router.get("/shows/{show_id}/profile")
def show_profile(show_id: str, refresh: bool = True) -> dict:
    with session_scope() as s:
        root = _require_show(s, show_id)
        return prof.build_profile(s, root, enqueue_refresh=refresh)  # type: ignore[return-value]


@router.get("/shows/{show_id}/episodes")
def show_episodes(show_id: str, include_removed: bool = False, limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)) -> dict:
    with session_scope() as s:
        root = _require_show(s, show_id)
        q = select(Episode).where(Episode.show_id == root)
        if not include_removed:
            q = q.where(Episode.removed.is_(False))
        total = s.scalar(select(func.count()).select_from(q.subquery()))
        eps = s.scalars(q.order_by(Episode.published_at.desc()).limit(limit).offset(offset))
        return {"show_id": root, "total": total, "episodes": [{
            "id": e.id, "guid": e.guid, "title": e.title, "description": e.description[:500], "published_at": e.published_at.isoformat() + "Z" if e.published_at else None,
            "duration_sec": e.duration_sec, "language": e.language, "explicit": e.explicit, "has_transcript": bool(e.transcript_url),
            "persons": e.persons, "removed": e.removed, "data_tier": "verified", "source": "rss"} for e in eps]}


@router.get("/shows/{show_id}/similar")
def show_similar(show_id: str, space: str = Query("content", pattern="^(content|style)$"), limit: int = Query(5, ge=1, le=20)) -> dict:
    with session_scope() as s:
        root = _require_show(s, show_id)
        hits = similar(s, "show", root, space, limit)
        if not hits and not s.execute(text("SELECT 1 FROM embeddings WHERE entity_id = :i AND space = :sp"), {"i": root, "sp": space}).first():
            raise HTTPException(404, f"no {space} embedding for this show yet")
        pm = _prov_map(s, ["categories", "vibe", "topics", "tone", "conversational_style"])
        base = pm.get(root, {})
        out = []
        for sid, sim in hits:
            sh = s.get(Show, sid)
            o = pm.get(sid, {})
            reason: dict[str, Any] = {}
            shared_cat = sorted(set(base.get("categories") or []) & set(o.get("categories") or []))
            if shared_cat:
                reason["shared_categories"] = shared_cat
            top = lambda p: {k for k, v in sorted((p.get("vibe") or {}).items(), key=lambda kv: -kv[1])[:3] if v > 0}  # noqa: E731
            if top(base) & top(o):
                reason["shared_top_vibes"] = sorted(top(base) & top(o))
            if base.get("conversational_style") and base.get("conversational_style") == o.get("conversational_style"):
                reason["same_conversational_style"] = o["conversational_style"]
            bt, ot = {t["name"].lower() for t in base.get("topics") or []}, {t["name"].lower() for t in o.get("topics") or []}
            if bt & ot:
                reason["shared_topics"] = sorted(bt & ot)
            out.append({"show_id": sid, "title": sh.title, "similarity": round(sim, 4), "space": space, "reason_fields": reason,
                        "language": sh.language})
        return {"show_id": root, "space": space, "neighbours": out}


@router.post("/shows/{show_id}/refresh", status_code=202)
def refresh_show(show_id: str, force: bool = True, user_id: str | None = None) -> dict:
    with session_scope() as s:
        root = _require_show(s, show_id)
        j = jobs.enqueue(s, "refresh_show", f"refresh:{root}:{'f' if force else ''}:{int(time.time() // 60)}", {"show_id": root, "force": force, "user_id": user_id})
        return {"job_id": j.id, "status": j.status, "show_id": root}


@router.post("/shows/{show_id}/audience-upload")
async def audience_upload(show_id: str, file: UploadFile = File(...), mapping: str | None = Form(None), user_id: str | None = Form(None)) -> dict:
    raw = await file.read()
    with session_scope() as s:
        root = _require_show(s, show_id)
        try:
            cols, rows = aud.read_csv(raw)
            if not mapping:
                return {"status": "needs_mapping", "columns": cols, "suggested_mapping": aud.suggest_mapping(cols), "sample_rows": rows[:5],
                        "kinds": sorted(aud.KINDS), "stored": False}
            try:
                m = json.loads(mapping)
            except ValueError as exc:
                raise aud.UploadError("mapping must be valid JSON") from exc
            missing = [c for c in [m.get("label_col"), m.get("value_col"), m.get("percent_col"), *(m.get("columns") or {}).values()] if c and c not in cols]
            if missing:
                raise aud.UploadError(f"mapping refers to columns not in the file: {missing}")
            res = aud.store_upload(s, root, user_id, file.filename or "upload.csv", raw, m)
            return {"status": "stored", **res}
        except aud.UploadError as exc:
            raise HTTPException(422, str(exc)) from exc


@router.put("/shows/{show_id}/creator-profile")
def creator_profile(show_id: str, body: CreatorProfile) -> dict:
    with session_scope() as s:
        root = _require_show(s, show_id)
        fields = aud.save_creator_profile(s, root, body.user_id, body.goals, body.collaboration_openness, body.blocked_categories)
        return {"stored": fields, "data_tier": "creator_provided"}


@router.post("/shows/{show_id}/claim")
def claim_show(show_id: str, user_id: str) -> dict:
    with session_scope() as s:
        root = _require_show(s, show_id)
        if not s.scalar(select(ShowClaim.id).where(ShowClaim.show_id == root, ShowClaim.user_id == user_id)):
            s.add(ShowClaim(show_id=root, user_id=user_id))
        return {"show_id": root, "user_id": user_id}


@router.post("/shows/{show_id}/transcribe", status_code=202)
def transcribe(show_id: str, body: Transcribe) -> dict:
    with session_scope() as s:
        root = _require_show(s, show_id)
    try:
        check_allowed(root, body.user_id, body.opt_in)
    except NotAllowed as exc:
        raise HTTPException(403, str(exc)) from exc
    with session_scope() as s:
        j = jobs.enqueue(s, "transcribe", f"transcribe:{root}:{now().date().isoformat()}", {"show_id": root, "user_id": body.user_id, "opt_in": True})
        return {"job_id": j.id, "status": j.status}


# ───────────────────────────── admin ─────────────────────────────
@router.get("/admin/coverage")
def admin_coverage() -> dict:
    """Measured data-feasibility matrix: per connector, % of shows where each field was actually returned."""
    with session_scope() as s:
        latest: dict[tuple[str, str], ConnectorRun] = {}
        for r in s.scalars(select(ConnectorRun).order_by(ConnectorRun.id)):
            if r.show_id:
                latest[(r.connector, r.show_id)] = r
        agg: dict[str, dict] = {}
        for (conn, _sid), r in latest.items():
            a = agg.setdefault(conn, {"shows": 0, "ok": 0, "expected": r.fields_expected, "counts": {}})
            a["shows"] += 1
            if r.ok:
                a["ok"] += 1
                for f in r.fields_returned:
                    a["counts"][f] = a["counts"].get(f, 0) + 1
        out = {}
        for conn, a in agg.items():
            ok = max(1, a["ok"])
            out[conn] = {"shows_attempted": a["shows"], "shows_ok": a["ok"], "ok_rate": round(a["ok"] / a["shows"], 3),
                         "fields": {f: {"count": a["counts"].get(f, 0), "pct": round(100 * a["counts"].get(f, 0) / ok, 1)} for f in a["expected"]}}
        return {"generated_at": now().isoformat() + "Z", "connectors": out,
                "note": "pct = share of successfully fetched shows where the connector actually returned the field. Connectors with no keys do not appear."}


@router.get("/admin/costs")
def admin_costs(days: int | None = None) -> dict:
    from datetime import timedelta
    with session_scope() as s:
        return budget.summary(s, now() - timedelta(days=days) if days else None)


@router.get("/admin/jobs")
def admin_jobs(status: str | None = None, limit: int = Query(50, ge=1, le=500)) -> dict:
    with session_scope() as s:
        q = select(Job).order_by(Job.created_at.desc()).limit(limit)
        if status:
            q = q.where(Job.status == status)
        counts = dict(s.execute(select(Job.status, func.count()).group_by(Job.status)).all())
        return {"counts": counts, "jobs": [_job_view(j) for j in s.scalars(q)]}


@router.get("/health")
def health() -> dict:
    cfg = get_settings()
    info: dict[str, Any] = {"status": "ok", "service": "podbae-intel", "store": {"backend": "sqlite" if cfg.database_url.startswith("sqlite") else "postgres"},
                            "vector_backend": cfg.vector_backend, "llm": provider_status(), "embeddings": embedder_status(),
                            "providers": {"podcastindex": bool(cfg.pi_key and cfg.pi_secret), "taddy": bool(cfg.taddy_enabled and cfg.taddy_key),
                                          "itunes_search": True},
                            "whisper_enabled": cfg.whisper_enabled, "worker": cfg.worker_enabled}
    try:
        with get_engine().connect() as c:
            c.execute(text("SELECT 1"))
            if cfg.vector_backend == "sqlite-vec":
                info["store"]["vec_version"] = c.execute(text("SELECT vec_version()")).scalar()
    except Exception as exc:  # noqa: BLE001
        info["status"] = "degraded"
        info["store"]["error"] = f"{type(exc).__name__}: {exc}"[:200]
    return info
