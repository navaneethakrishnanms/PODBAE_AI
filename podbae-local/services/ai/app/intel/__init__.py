"""PodBae Layer 1: Podcast Intelligence (+ Trust Spine). Owned by services/ai; the rest of the app uses its /v1 HTTP API."""
from __future__ import annotations

_worker = None


def startup(*, use_alembic: bool = True, start_worker: bool | None = None) -> None:
    from . import ingest, whisper_job  # noqa: F401  (registers job handlers)
    from ..opportunities import engine as _opp_engine  # noqa: F401  (registers the opportunities_generate job)
    from .config import get_settings
    from .db import create_all, init_engine, migrate, session_scope
    from .trust.budget import ensure_default_budgets
    from .trust.jobs import Worker

    cfg = get_settings()
    init_engine()
    if use_alembic and ":memory:" not in cfg.database_url and cfg.database_url.startswith(("sqlite", "postgres")):
        migrate()
    else:
        create_all()
    with session_scope() as s:
        ensure_default_budgets(s)
    global _worker
    if (cfg.worker_enabled if start_worker is None else start_worker) and _worker is None:
        _worker = Worker()
        _worker.start()


def shutdown() -> None:
    global _worker
    if _worker is not None:
        _worker.stop()
        _worker = None
