"""Phase 2 close-out: record declared contact / booking / guest routes for every stored show (Layer 4 readiness).
Reads ONLY text already in the store (show description, episode notes, website link, podcast:person href); no fetching,
no LLM, no e-mail addresses. New ingests do this automatically in the understanding stage.
    python scripts/backfill_contact_routes.py"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.envfile import load_env  # noqa: E402

load_env()


def main() -> int:
    from sqlalchemy import select
    from app.intel.contact_routes import record_routes
    from app.intel.db import init_engine, session_scope
    from app.intel.models import Show
    init_engine()
    with session_scope() as s:
        ids = [sh.id for sh in s.scalars(select(Show).where(Show.merged_into.is_(None)).order_by(Show.id))]
    kinds, found_in, with_route = Counter(), Counter(), 0
    for sid in ids:
        with session_scope() as s:
            routes = record_routes(s, sid)
        with_route += bool(routes)
        kinds.update(r["kind"] for r in routes)
        found_in.update(r["found_in"] for r in routes)
    out = {"shows": len(ids), "shows_with_declared_route": with_route, "routes_by_kind": dict(kinds), "routes_by_source": dict(found_in)}
    print(json.dumps(out, indent=1))
    (Path(__file__).resolve().parents[1] / "eval" / "contact_routes_backfill.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
