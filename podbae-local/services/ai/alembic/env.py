from __future__ import annotations

import os
import sys
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.intel.models import Base  # noqa: E402

config = context.config
target_metadata = Base.metadata


def run() -> None:
    # programmatic runs (app startup / tests) pass the URL explicitly; the CLI falls back to the env var
    url = config.get_main_option("sqlalchemy.url") if config.attributes.get("configured") else \
        (os.environ.get("INTEL_DATABASE_URL") or config.get_main_option("sqlalchemy.url"))
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    if context.is_offline_mode():
        context.configure(url=url, target_metadata=target_metadata, literal_binds=True, render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()
        return
    if url.startswith("sqlite") and ":memory:" not in url:
        Path(url.replace("sqlite:///", "", 1)).parent.mkdir(parents=True, exist_ok=True)
    engine = engine_from_config(config.get_section(config.config_ini_section) or {}, prefix="sqlalchemy.",
                                poolclass=pool.NullPool)
    with engine.connect() as conn:
        context.configure(connection=conn, target_metadata=target_metadata, render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()


run()

