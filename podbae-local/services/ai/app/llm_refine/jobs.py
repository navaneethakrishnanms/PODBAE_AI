"""Phase 4 jobs. A provider rate limit PAUSES a job: it stops, schedules its own continuation for later and ends as
'succeeded' with {"paused": true}. Completed items are cached (content hash), so the continuation re-sends nothing that
already has an answer.

  llm_refine  payload {tasks: [...], show_ids?: [...], limit?: int}
              tasks: style, guests, topics (Layer 1, per show)  |  uncertain, organic, categories, names (sponsors)
  llm_phrase  payload {ids: [opportunity ids]}  (enqueued from impression events)"""
from __future__ import annotations

import hashlib
import time
from datetime import timedelta

from sqlalchemy import select

from ..intel.db import session_scope
from ..intel.models import Job, Show, now
from ..intel.trust import jobs
from . import layer1  # noqa: F401  (registers the Layer 1 refiners on the Phase 1 seam)
from .client import Paused

LAYER1 = ("style", "guests", "topics")
SPONSOR = ("uncertain", "organic", "categories", "names")
PAUSE_SECONDS = 120


def run_layer1(tasks: list[str], show_ids: list[str] | None = None, limit: int | None = None, progress=None) -> dict:
    from .layer1 import refine_show
    with session_scope() as s:
        ids = show_ids or [x for x in s.scalars(select(Show.id).where(Show.merged_into.is_(None)).order_by(Show.id))]
    ids = ids[: limit or None]
    tally: dict[str, dict] = {t: {} for t in tasks}
    for i, sid in enumerate(ids):
        with session_scope() as s:
            res = refine_show(s, sid, tasks)            # may raise Paused (the session rolls back only this show)
        for t, r in res.items():
            key = r.get("status", "?") + ("+applied" if r.get("applied") else "")
            tally[t][key] = tally[t].get(key, 0) + 1
        if progress:
            progress(i + 1, len(ids), sid, res)
    return {"shows": len(ids), "by_task": tally}


def run_sponsor(tasks: list[str], limit: int | None = None) -> dict:
    from . import sponsors as sp
    out: dict = {}
    with session_scope() as s:
        if "uncertain" in tasks:
            out["uncertain"] = sp.classify_uncertain(s, limit=limit)
        if "organic" in tasks:
            out["organic"] = sp.audit_organic(s, n=limit)
    if {"uncertain", "organic"} & set(tasks):         # promoted events can create / revive brands (LLM active only)
        from ..sponsors.resolve import resolve
        with session_scope() as s:
            out["brands"] = resolve(s)
    with session_scope() as s:
        if "categories" in tasks:
            out["categories"] = sp.categorize_brands(s, limit=limit)
        if "names" in tasks:
            out["names"] = sp.suggest_names(s, limit=limit)
    return out


def _continue_later(ctx: jobs.JobContext, jtype: str, payload: dict, why: str) -> dict:
    with session_scope() as s:
        j = s.get(Job, ctx.job_id)
        base = (j.idempotency_key if j else jtype).split(":resume")[0]
        n = int(ctx.checkpoint.get("resumes", 0)) + 1
        nj = jobs.enqueue(s, jtype, f"{base}:resume{n}", payload)
        nj.run_after = now() + timedelta(seconds=PAUSE_SECONDS)
        return {"paused": True, "reason": why, "resume_job": nj.id, "resume_after_seconds": PAUSE_SECONDS}


@jobs.register("llm_refine")
def _refine_job(ctx: jobs.JobContext) -> dict:
    p = ctx.payload
    tasks = p.get("tasks") or list(LAYER1 + SPONSOR)
    out: dict = {}
    try:
        l1 = [t for t in tasks if t in LAYER1]
        if l1:
            out["layer1"] = run_layer1(l1, p.get("show_ids"), p.get("limit"))
        sp = [t for t in tasks if t in SPONSOR]
        if sp:
            out["sponsors"] = run_sponsor(sp, p.get("limit"))
    except Paused as exc:
        out.update(_continue_later(ctx, "llm_refine", p, str(exc)))
    return out


def enqueue_phrasing(s, opp_ids: list[str]) -> None:
    day = time.strftime("%Y-%m-%d")
    key = "llm_phrase:" + hashlib.sha1(("|".join(sorted(opp_ids)) + day).encode()).hexdigest()[:20]
    jobs.enqueue(s, "llm_phrase", key, {"ids": sorted(opp_ids)})


@jobs.register("llm_phrase")
def _phrase_job(ctx: jobs.JobContext) -> dict:
    from ..opportunities.models import Opportunity
    from ..opportunities import explain as ex
    from .phraser import phrase
    done: dict[str, str] = {}
    try:
        for oid in ctx.payload.get("ids") or []:
            with session_scope() as s:
                o = s.get(Opportunity, oid)
                if o is None or not (o.explanation_json or {}).get("parts"):
                    continue
                _txt, st = phrase(s, o.explanation_json, entity=("opportunity", oid), type_label=ex.TYPE_LABEL.get(o.type, o.type))
                done[oid] = st
                if st == "daily_budget":
                    break
    except Paused as exc:
        return {**_continue_later(ctx, "llm_phrase", ctx.payload, str(exc)), "done": done}
    return {"phrased": done}
