"""/v1 routes for Layer 2 (sponsor intelligence) and sponsor opportunities. All behind X-Service-Token."""
from __future__ import annotations


from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from ..auth import require_service_token
from ..intel.db import session_scope
from ..intel.models import Job
from ..intel.normalize import resolve_root
from ..intel.trust import jobs
from ..opportunities import engine
from ..opportunities.api import safe
from . import opportunities as sp
from . import review as rv
from .connectors import rephonic
from .metrics import sponsor_metrics
from .stats import corpus_stats

router = APIRouter(prefix="/v1", dependencies=[Depends(require_service_token)])


class GenerateIn(BaseModel):
    member_show_id: str
    force: bool = False


class ReviewIn(BaseModel):
    reviewer: str = Field(min_length=1, max_length=80)
    verdict: str
    correct_class: str | None = None
    note: str | None = Field(default=None, max_length=300)


class MergeIn(BaseModel):
    source_id: str
    target_id: str
    actor: str = Field(default="admin", max_length=80)


class SplitIn(BaseModel):
    domain: str
    actor: str = Field(default="admin", max_length=80)


class CategoriesIn(BaseModel):
    categories: list[str] = Field(max_length=6)
    actor: str = Field(default="admin", max_length=80)


class Advertiser(BaseModel):
    advertiser_ref: str
    domain: str | None = None
    active_campaign: bool = False
    campaign_categories: list[str] = Field(default_factory=list)
    campaign_started_at: str | None = None


class RegistrationsIn(BaseModel):
    advertisers: list[Advertiser] = Field(max_length=500)


class LinkIn(Advertiser):
    actor: str = Field(default="admin", max_length=80)


def _err(exc: Exception, code: int = 422):
    raise HTTPException(code, str(exc)) from exc


# ── sponsor opportunities (shared engine) ──
@router.post("/sponsor-opportunities/generate", status_code=202)
def generate(body: GenerateIn) -> JSONResponse:
    with session_scope() as s:
        try:
            j = sp.enqueue(s, body.member_show_id, force=body.force)
        except engine.NotFound as exc:
            _err(exc, 404)
        return safe({"job_id": j.id, "status": j.status, "member_show_id": j.payload.get("member_show_id")}, 202)


@router.get("/sponsor-opportunities")
def list_opps(member_show_id: str, limit: int = Query(50, ge=1, le=200), user_id: str | None = None) -> JSONResponse:
    with session_scope() as s:
        try:
            return safe(sp.list_for_member(s, member_show_id, user_id=user_id, limit=limit))
        except engine.NotFound as exc:
            _err(exc, 404)


@router.get("/admin/engine/sponsor-metrics")
def metrics() -> JSONResponse:
    with session_scope() as s:
        out = sponsor_metrics(s)
        out["jobs"] = dict(s.execute(select(Job.status, func.count()).where(Job.type == "sponsor_opportunities_generate").group_by(Job.status)).all())
        return safe(out)


# ── public "sponsors seen" (declared / reviewed only) ──
@router.get("/shows/{show_id}/sponsors")
def show_sponsors(show_id: str) -> JSONResponse:
    with session_scope() as s:
        return safe(rv.show_sponsors(s, resolve_root(s, show_id)))


# ── admin: scan, stats, review, brands, registrations ──
@router.post("/admin/sponsors/scan", status_code=202)
def scan() -> JSONResponse:
    import time
    with session_scope() as s:
        j = jobs.enqueue(s, "sponsors_scan", f"sponsors_scan:{int(time.time() // 600)}", {})
        return safe({"job_id": j.id, "status": j.status}, 202)


@router.get("/admin/sponsors/stats")
def stats() -> JSONResponse:
    with session_scope() as s:
        out = corpus_stats(s)
        out["review"] = rv.precision(s)
        out["connectors"] = {"rephonic": rephonic.status()}
        return safe(out)


@router.get("/admin/sponsors/review/queue")
def review_queue(reviewer: str | None = None, filter: str | None = Query(None, pattern="^disagree$")) -> JSONResponse:
    with session_scope() as s:
        return safe(rv.queue(s, reviewer, filter=filter))


@router.put("/admin/sponsors/review/{event_id}")
def review_save(event_id: int, body: ReviewIn) -> JSONResponse:
    with session_scope() as s:
        try:
            return safe(rv.save(s, event_id, body.reviewer, body.verdict, body.correct_class, body.note))
        except rv.ReviewError as exc:
            _err(exc)


@router.get("/admin/sponsors/review/precision")
def review_precision() -> JSONResponse:
    with session_scope() as s:
        return safe(rv.precision(s))


@router.get("/admin/sponsors/brands")
def brands(q: str | None = None, status: str | None = None, limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0),
           filter: str | None = Query(None, pattern="^disagree$")) -> JSONResponse:
    with session_scope() as s:
        return safe(rv.list_brands(s, q, status, limit, offset, filter=filter))


class NameDecisionIn(BaseModel):
    action: str = Field(pattern="^(approve|reject)$")
    actor: str = Field(default="admin", max_length=80)


@router.post("/admin/sponsors/brands/{brand_id}/name")
def brand_name_decision(brand_id: str, body: NameDecisionIn) -> JSONResponse:
    with session_scope() as s:
        try:
            return safe(rv.name_decision(s, brand_id, body.action, body.actor))
        except rv.ReviewError as exc:
            _err(exc)


@router.get("/admin/sponsors/brands/{brand_id}")
def brand(brand_id: str) -> JSONResponse:
    from .models import Brand
    with session_scope() as s:
        b = s.get(Brand, brand_id)
        if b is None:
            raise HTTPException(404, "brand not found")
        return safe(rv.brand_view(s, b, events=25))


@router.post("/admin/sponsors/brands/merge")
def brand_merge(body: MergeIn) -> JSONResponse:
    with session_scope() as s:
        try:
            return safe(rv.merge(s, body.source_id, body.target_id, body.actor))
        except rv.ReviewError as exc:
            _err(exc)


@router.post("/admin/sponsors/brands/{brand_id}/split")
def brand_split(brand_id: str, body: SplitIn) -> JSONResponse:
    with session_scope() as s:
        try:
            return safe(rv.split(s, brand_id, body.domain, body.actor))
        except rv.ReviewError as exc:
            _err(exc)


@router.put("/admin/sponsors/brands/{brand_id}/categories")
def brand_categories(brand_id: str, body: CategoriesIn) -> JSONResponse:
    with session_scope() as s:
        try:
            return safe(rv.set_categories(s, brand_id, body.categories, body.actor))
        except rv.ReviewError as exc:
            _err(exc)


@router.post("/sponsors/registrations")
def registrations(body: RegistrationsIn) -> JSONResponse:
    with session_scope() as s:
        return safe(rv.sync_registrations(s, [a.model_dump() for a in body.advertisers]))


@router.post("/admin/sponsors/brands/{brand_id}/registration")
def brand_link(brand_id: str, body: LinkIn) -> JSONResponse:
    from ..intel.trust.audit import audit
    from .models import Brand
    with session_scope() as s:
        if s.get(Brand, brand_id) is None:
            raise HTTPException(404, "brand not found")
        r = rv.link(s, brand_id, body.model_dump(), "admin")
        audit(s, f"admin:{body.actor}", "brand_registration_link", "brand", brand_id, {"advertiser_ref": body.advertiser_ref})
        return safe({"brand_id": brand_id, "advertiser_ref": r.advertiser_ref, "active_campaign": r.active_campaign})


