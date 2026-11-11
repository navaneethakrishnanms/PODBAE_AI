"""Jobs: the `jobs` table is the queue's source of truth (swap the worker for a real queue in production).

- idempotent: `enqueue(idempotency_key=...)` returns the existing job (a failed/cancelled one is re-queued).
- resumable: handlers receive a `JobContext` and mark finished stages in `job.checkpoint`; after a crash the
  stale `running` job is recovered to `queued` and the handler skips completed stages.
- retried with exponential backoff up to `max_attempts`, then `failed` with `last_error`.
"""
from __future__ import annotations

import threading
import time
import traceback
from datetime import timedelta
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import session_scope
from ..models import Job, now
from .audit import audit

Handler = Callable[["JobContext"], dict | None]
_HANDLERS: dict[str, Handler] = {}


class JobCancelled(Exception):
    pass


def register(job_type: str) -> Callable[[Handler], Handler]:
    def deco(fn: Handler) -> Handler:
        _HANDLERS[job_type] = fn
        return fn
    return deco


class JobContext:
    def __init__(self, job_id: str, payload: dict, checkpoint: dict, attempt: int):
        self.job_id, self.payload, self.attempt = job_id, payload, attempt
        self.checkpoint = dict(checkpoint)

    def done(self, stage: str) -> bool:
        return bool(self.checkpoint.get(stage))

    def mark(self, stage: str, info: Any = True) -> None:
        """Persist stage completion immediately (so a crash right after resumes past it)."""
        self.checkpoint[stage] = info
        with session_scope() as s:
            j = s.get(Job, self.job_id)
            if j is not None:
                j.checkpoint = dict(self.checkpoint)
                j.heartbeat_at = now()


def enqueue(s: Session, job_type: str, idempotency_key: str, payload: dict | None = None, max_attempts: int | None = None) -> Job:
    job = s.scalar(select(Job).where(Job.idempotency_key == idempotency_key))
    if job is not None:
        if job.status in ("failed", "cancelled"):
            job.status, job.attempts, job.last_error, job.run_after = "queued", 0, None, now()
            audit(s, "jobs", "requeued", None, job.id, {"type": job_type})
        return job
    job = Job(type=job_type, idempotency_key=idempotency_key, payload=payload or {},
              max_attempts=max_attempts or get_settings().max_attempts)
    s.add(job)
    s.flush()
    return job


def recover_stale(lease_seconds: int | None = None) -> int:
    """Running jobs whose heartbeat is older than the lease (crashed worker) go back to the queue."""
    lease = timedelta(seconds=lease_seconds if lease_seconds is not None else get_settings().job_lease_seconds)
    n = 0
    with session_scope() as s:
        for j in s.scalars(select(Job).where(Job.status == "running")):
            beat = j.heartbeat_at or j.updated_at
            if now() - beat >= lease:
                j.status, j.run_after = "queued", now()
                audit(s, "jobs", "recovered", None, j.id, {"type": j.type, "attempts": j.attempts})
                n += 1
    return n


def _claim() -> JobContext | None:
    with session_scope() as s:
        j = s.scalar(select(Job).where(Job.status == "queued", Job.run_after <= now()).order_by(Job.created_at).limit(1))
        if j is None:
            return None
        j.status, j.attempts, j.heartbeat_at = "running", j.attempts + 1, now()
        return JobContext(j.id, dict(j.payload), dict(j.checkpoint or {}), j.attempts)


def run_one() -> bool:
    ctx = _claim()
    if ctx is None:
        return False
    with session_scope() as s:
        j = s.get(Job, ctx.job_id)
        jtype, max_attempts = j.type, j.max_attempts
    handler = _HANDLERS.get(jtype)
    try:
        if handler is None:
            raise RuntimeError(f"no handler for job type {jtype!r}")
        result = handler(ctx) or {}
        with session_scope() as s:
            j = s.get(Job, ctx.job_id)
            j.status, j.result, j.last_error, j.checkpoint = "succeeded", result, None, dict(ctx.checkpoint)
    except JobCancelled:
        with session_scope() as s:
            s.get(Job, ctx.job_id).status = "cancelled"
    except Exception as exc:  # noqa: BLE001 - boundary: every failure is recorded
        err = f"{type(exc).__name__}: {exc}"[:1000]
        with session_scope() as s:
            j = s.get(Job, ctx.job_id)
            j.last_error = err
            if ctx.attempt >= max_attempts:
                j.status = "failed"
                audit(s, "jobs", "failed", None, j.id, {"type": jtype, "error": err, "trace": traceback.format_exc()[-1500:]})
            else:
                j.status = "queued"
                j.run_after = now() + timedelta(seconds=get_settings().backoff_base_seconds * (2 ** (ctx.attempt - 1)))
    return True


def run_pending(limit: int = 1000) -> int:
    n = 0
    while n < limit and run_one():
        n += 1
    return n


class Worker:
    """In-process polling worker (one thread). Production: replace with a real queue consuming the same table."""

    def __init__(self, poll: float = 0.5):
        self.poll, self._stop, self._t = poll, threading.Event(), None

    def start(self) -> None:
        if self._t and self._t.is_alive():
            return
        recover_stale(lease_seconds=0)  # at boot, nothing of ours is still running
        self._stop.clear()
        self._t = threading.Thread(target=self._loop, name="intel-worker", daemon=True)
        self._t.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                if not run_one():
                    time.sleep(self.poll)
            except Exception:  # noqa: BLE001
                time.sleep(self.poll)
