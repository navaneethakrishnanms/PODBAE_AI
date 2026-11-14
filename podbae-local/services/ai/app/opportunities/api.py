"""/v1 routes of the Opportunity Engine. All behind X-Service-Token (same dependency as the rest of /v1)."""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from ..auth import require_service_token
from ..intel.db import session_scope
from ..intel.models import Job
from ..intel.understanding.signals import taxonomy
from . import engine, pairlabels
from ..sponsors.resolve import seeds as sponsor_seeds
from .config import DISMISS_REASONS, EVENT_TYPES, OPP_TYPES, SPONSOR_DISMISS_REASONS, get_config
from .features import EMAIL_RX
from .metrics import engine_metrics, showcase_show

router = APIRouter(prefix="/v1", dependencies=[Depends(require_service_token)])

GOAL_OPTIONS = ["cross_promo", "guest_swap", "feed_swap", "find_guests", "be_a_guest", "grow_audience"]
BRAND_SAFETY_FLAGS = ["profanity", "adult_themes", "violence", "politics", "religion", "health_claims", "conspiracy", "gambling",
                      "alcohol_drugs", "controversial_topics"]
CATEGORY_GROUPS = ["Arts", "Business", "Comedy", "Education", "Fiction", "Health & Fitness", "History", "Kids & Family", "Leisure", "Music",
                   "News", "Religion & Spirituality", "Science", "Society & Culture", "Sports", "Technology", "True Crime", "TV & Film"]


def safe(body: Any, status: int = 200) -> JSONResponse:
    """Final guard on every engine response: no e-mail address and no owner e-mail hash ever leaves this service."""
    txt = json.dumps(body, default=str)
    txt = EMAIL_RX.sub("[email removed]", txt)
    if "owner_email_hash" in txt:
        raise HTTPException(500, "refusing to emit an owner identity field")
    return JSONResponse(json.loads(txt), status_code=status)


class GenerateIn(BaseModel):
    member_show_id: str
    force: bool = False


class EventIn(BaseModel):
    opportunity_id: str
    type: str
    user_id: str | None = None
    position: int | None = Field(default=None, ge=1, le=1000)
    reason: str | None = None
    note: str | None = Field(default=None, max_length=300)
    idempotency_key: str | None = Field(default=None, max_length=200)


class EventsIn(BaseModel):
    events: list[EventIn] = Field(min_length=1, max_length=100)


class PairLabelIn(BaseModel):
    member_show_id: str
    candidate_show_id: str
    labeler: str = Field(min_length=1, max_length=80)
    rating: str
    note: str | None = Field(default=None, max_length=300)


class PairItemsIn(BaseModel):
    n: int = Field(default=20, ge=3, le=50)
    replace: bool = False


@router.post("/opportunities/generate", status_code=202)
def generate(body: GenerateIn) -> JSONResponse:
    with session_scope() as s:
        try:
            j = engine.enqueue_generate(s, body.member_show_id, force=body.force)
        except engine.NotFound as exc:
            raise HTTPException(404, str(exc)) from exc
        return safe({"job_id": j.id, "status": j.status, "member_show_id": j.payload.get("member_show_id")}, 202)


@router.get("/opportunities")
def list_opportunities(member_show_id: str, limit: int = Query(50, ge=1, le=200), user_id: str | None = None) -> JSONResponse:
    with session_scope() as s:
        try:
            return safe(engine.list_for_member(s, member_show_id, user_id=user_id, limit=limit))
        except engine.NotFound as exc:
            raise HTTPException(404, str(exc)) from exc


@router.get("/opportunities/options")
def options() -> JSONResponse:
    cfg = get_config()
    return safe({"goals": GOAL_OPTIONS, "collaboration_openness": ["open", "selective", "closed"], "brand_safety_flags": BRAND_SAFETY_FLAGS,
                 "category_groups": CATEGORY_GROUPS, "topics": [{"id": k, "label": v["label"], "group": v["group"]} for k, v in taxonomy().items()],
                 "dismiss_reasons": list(DISMISS_REASONS), "event_types": list(EVENT_TYPES), "types": list(OPP_TYPES),
                 "sponsor_dismiss_reasons": list(SPONSOR_DISMISS_REASONS),
                 "brand_categories": [{"id": k, "label": v["label"], "sensitive": bool(v.get("sensitive"))}
                                      for k, v in sponsor_seeds()["categories"].items()],
                 "scoring_version": cfg["scoring_version"], "status": cfg["status"]})


@router.get("/opportunities/{opp_id}")
def get_one(opp_id: str) -> JSONResponse:
    with session_scope() as s:
        try:
            return safe(engine.view(engine.get_opportunity(s, opp_id)))
        except engine.NotFound as exc:
            raise HTTPException(404, str(exc)) from exc


@router.get("/opportunities/{opp_id}/explain")
def explain(opp_id: str) -> JSONResponse:
    with session_scope() as s:
        try:
            return safe(engine.explain_view(s, opp_id))
        except engine.NotFound as exc:
            raise HTTPException(404, str(exc)) from exc


@router.post("/events")
def events(body: EventsIn) -> JSONResponse:
    with session_scope() as s:
        try:
            return safe({"recorded": engine.record_events(s, [e.model_dump() for e in body.events])})
        except engine.EventError as exc:
            raise HTTPException(422, str(exc)) from exc
        except engine.NotFound as exc:
            raise HTTPException(404, str(exc)) from exc


@router.get("/admin/engine/metrics")
def admin_metrics() -> JSONResponse:
    with session_scope() as s:
        out = engine_metrics(s)
        out["pair_labels"] = pairlabels.metrics(s)
        out["jobs"] = dict(s.execute(select(Job.status, func.count()).where(Job.type == "opportunities_generate").group_by(Job.status)).all())
        return safe(out)


@router.get("/admin/engine/showcase")
def admin_showcase(exclude: str = "") -> JSONResponse:
    with session_scope() as s:
        return safe({"showcase": showcase_show(s, {x for x in exclude.split(",") if x})})


# ───────────────────────── blind pair labels ─────────────────────────
@router.get("/labels/pairs/queue")
def pairs_queue(labeler: str | None = None) -> JSONResponse:
    with session_scope() as s:
        return safe(pairlabels.queue(s, labeler))


@router.put("/labels/pairs/rate")   # two segments: must not collide with Phase 1 PUT /v1/labels/{show_id}
def pairs_save(body: PairLabelIn) -> JSONResponse:
    with session_scope() as s:
        try:
            return safe(pairlabels.save(s, body.member_show_id, body.candidate_show_id, body.labeler, body.rating, body.note))
        except pairlabels.PairLabelError as exc:
            raise HTTPException(422, str(exc)) from exc


@router.post("/labels/pairs/items")
def pairs_items(body: PairItemsIn) -> JSONResponse:
    with session_scope() as s:
        ids = pairlabels.pick_items(s, body.n, replace=body.replace)
        return safe({"member_show_ids": ids, "count": len(ids)})


@router.get("/labels/pairs/agreement")
def pairs_agreement() -> JSONResponse:
    with session_scope() as s:
        return safe({**pairlabels.agreement(s), "metrics": pairlabels.metrics(s)})
