"""Phase 4: run the LLM refiners over the store (resumable: answers are cached by content hash, a rate limit pauses).
Usage: npm run llm:refine -- --tasks style,guests,topics,uncertain,organic,categories,names [--limit N] [--shows id,id]"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

import torch  # noqa: F401  (safe native import order: torch -> sentence_transformers before lxml)
import sentence_transformers  # noqa: F401

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.envfile import load_env  # noqa: E402

load_env()
from app.intel import startup  # noqa: E402
from app.llm_refine import llm_active  # noqa: E402
from app.llm_refine.client import Paused  # noqa: E402
from app.llm_refine.jobs import LAYER1, SPONSOR, run_layer1, run_sponsor  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", default=",".join(LAYER1 + SPONSOR))
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--shows", default=None)
    ap.add_argument("--pause", type=int, default=120)
    a = ap.parse_args()
    startup(use_alembic=True, start_worker=False)
    if not llm_active():
        print("LLM is OFF (LLM_PROVIDER=mock or INTEL_LLM_REFINE=false): nothing to do. Run npm run llm:check.")
        return 1
    tasks = [t.strip() for t in a.tasks.split(",") if t.strip()]
    t0 = time.time()
    out: dict = {}

    def prog(i, n, sid, res):
        if i % 10 == 0 or i == n:
            print(f"  layer1 {i}/{n} ({time.time() - t0:.0f}s)", flush=True)

    while True:
        try:
            l1 = [t for t in tasks if t in LAYER1]
            if l1:
                out["layer1"] = run_layer1(l1, a.shows.split(",") if a.shows else None, a.limit, prog)
            sp = [t for t in tasks if t in SPONSOR]
            if sp:
                out["sponsors"] = run_sponsor(sp, a.limit)
            break
        except Paused as exc:      # rate limited: wait and resume (cached answers are not re-sent)
            print(f"paused: {exc}; resuming in {a.pause}s", flush=True)
            time.sleep(a.pause)
    out["seconds"] = round(time.time() - t0, 1)
    print(json.dumps(out, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
