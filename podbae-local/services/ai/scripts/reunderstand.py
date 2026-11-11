"""Re-run ONLY the understanding stage (rules + local model, no LLM) for every show already in the store, then
recalibrate. Use after changing rules / taxonomy / boilerplate handling; feeds are not re-fetched.
    python scripts/reunderstand.py"""
from __future__ import annotations

try:  # load order: see app/intel/linalg.py
    import torch  # noqa: F401
except Exception:  # noqa: BLE001
    pass
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.envfile import load_env  # noqa: E402

load_env()


def main() -> int:
    from sqlalchemy import select
    from app import intel
    from app.intel.calibration import recalibrate
    from app.intel.db import session_scope
    from app.intel.models import Show
    from app.intel.understanding.pipeline import understand_show
    intel.startup(start_worker=False)
    with session_scope() as s:
        ids = [sh.id for sh in s.scalars(select(Show).where(Show.merged_into.is_(None)).order_by(Show.id))]
    t0, styles, fails = time.perf_counter(), {}, []
    for i, sid in enumerate(ids, 1):
        try:
            with session_scope() as s:
                r = understand_show(s, sid)
            styles[r.get("style")] = styles.get(r.get("style"), 0) + 1
        except Exception as exc:  # noqa: BLE001
            fails.append((sid, f"{type(exc).__name__}: {exc}"[:200]))
        if i % 50 == 0:
            print(f"  {i}/{len(ids)} {time.perf_counter() - t0:.0f}s", flush=True)
    with session_scope() as s:
        cal = recalibrate(s)
    print({"shows": len(ids), "styles": styles, "failures": fails, "calibration": cal, "seconds": round(time.perf_counter() - t0, 1)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
