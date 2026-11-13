"""Engine/session factory. SQLite (WAL) locally, Postgres in production: same models, config-only switch."""
from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from .config import get_settings

_lock = threading.Lock()
_engine: Engine | None = None
_Session: sessionmaker[Session] | None = None


def _is_sqlite(url: str) -> bool:
    return url.startswith("sqlite")


def make_engine(url: str) -> Engine:
    if not _is_sqlite(url):
        return create_engine(url, pool_pre_ping=True)
    if ":memory:" in url or url == "sqlite://":
        eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    else:
        path = url.replace("sqlite:///", "", 1)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        eng = create_engine(url, connect_args={"check_same_thread": False, "timeout": 30})

    @event.listens_for(eng, "connect")
    def _on_connect(dbapi: sqlite3.Connection, _rec) -> None:  # noqa: ANN001
        cur = dbapi.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA busy_timeout=30000")
        cur.close()
        try:  # sqlite-vec is optional at import time; the VectorIndex reports if it is missing
            import sqlite_vec

            dbapi.enable_load_extension(True)
            sqlite_vec.load(dbapi)
            dbapi.enable_load_extension(False)
        except Exception:  # pragma: no cover - depends on platform build
            pass

    return eng


def init_engine(url: str | None = None) -> Engine:
    global _engine, _Session
    with _lock:
        if _engine is not None:
            _engine.dispose()
        _engine = make_engine(url or get_settings().database_url)
        _Session = sessionmaker(_engine, expire_on_commit=False)
        return _engine


def get_engine() -> Engine:
    if _engine is None:
        init_engine()
    assert _engine is not None
    return _engine


def create_all() -> None:
    """Dev/test convenience. Real deployments use `alembic upgrade head`."""
    from ..opportunities import models as _opp_models  # noqa: F401  (registers the Layer 4 tables on the same Base)
    from ..sponsors import models as _sp_models  # noqa: F401  (Layer 2 sponsor tables)
    from .models import Base

    Base.metadata.create_all(get_engine())


def migrate() -> None:
    """Apply Alembic migrations to head against the configured URL (used at service start)."""
    from alembic import command
    from alembic.config import Config

    ai_root = Path(__file__).resolve().parents[2]
    cfg = Config(str(ai_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(ai_root / "alembic"))
    cfg.attributes["configured"] = True
    cfg.set_main_option("sqlalchemy.url", get_settings().database_url.replace("%", "%%"))
    command.upgrade(cfg, "head")


@contextmanager
def session_scope() -> Iterator[Session]:
    get_engine()
    assert _Session is not None
    s = _Session()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()
