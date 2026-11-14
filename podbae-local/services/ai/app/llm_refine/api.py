"""Phase 4 admin routes (same service token as every /v1 route). No route returns prompts, thinking text or user data."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ..auth import require_service_token
from ..intel.db import session_scope
from ..intel.trust import jobs
from ..opportunities.api import safe
from . import metrics as m

router = APIRouter(prefix="/v1", dependencies=[Depends(require_service_token)])
TASKS = ("style", "guests", "topics", "uncertain", "organic", "categories", "names")


class RunIn(BaseModel):
    tasks: list[str] = Field(default_factory=lambda: list(TASKS), max_length=7)
    limit: int | None = Field(default=None, ge=1, le=5000)


@router.get("/admin/llm/status")
def llm_status(check: bool = False) -> JSONResponse:
    out = m.status()
    if check and out["provider"] == "ollama":
        from .ollama import OllamaProvider
        out["check"] = OllamaProvider().check()
    return safe(out)


@router.get("/admin/llm/metrics")
def llm_metrics() -> JSONResponse:
    with session_scope() as s:
        return safe({**m.status(), "calls": m.call_metrics(s), "layer1": m.corpus_comparison(s)})


@router.post("/admin/llm/run")
def llm_run(body: RunIn) -> JSONResponse:
    tasks = [t for t in body.tasks if t in TASKS]
    import hashlib
    import time
    key = "llm_refine:" + hashlib.sha1(f"{sorted(tasks)}|{body.limit}|{time.strftime('%Y-%m-%d-%H')}".encode()).hexdigest()[:16]
    with session_scope() as s:
        j = jobs.enqueue(s, "llm_refine", key, {"tasks": tasks, "limit": body.limit})
        return safe({"job_id": j.id, "status": j.status, "tasks": tasks, "llm_active": m.status()["llm_active"]})


@router.get("/admin/llm/labels/disagreements")
def label_disagreements() -> JSONResponse:
    with session_scope() as s:
        return safe(m.label_disagreements(s))
