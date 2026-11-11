"""Step 2 diagnosis: why did only 91 of 279 feeds ingest in the Layer 1 seed run?

    python scripts/feed_diagnose.py [--input eval/seed_run.json] [--concurrency 16]

1. BEFORE: classify the stored Layer 1 error strings into the Phase 1 reason codes.
2. AFTER:  re-fetch exactly the same URLs with the Phase 1 fetcher (honest UA, gzip, connect timeout, retries,
           encoding repair; SSRF protection unchanged) and classify each outcome.
Fetch + parse only: nothing is written to the intelligence store. Writes eval/feed_diagnosis.json."""
from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.envfile import load_env  # noqa: E402

load_env()
from app.intel.connectors.base import classify_error, make_client  # noqa: E402
from app.intel.connectors.rss import fetch_feed  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default=str(ROOT / "eval" / "seed_run_layer1.json"))
    ap.add_argument("--concurrency", type=int, default=16)
    ap.add_argument("--out", default=str(ROOT / "eval" / "feed_diagnosis.json"))
    a = ap.parse_args()
    runs = json.loads(Path(a.input).read_text(encoding="utf-8"))["results"]
    before: dict[str, int] = {}
    for r in runs:
        k = "ok" if r["ok"] else classify_error(text=r["error"])
        before[k] = before.get(k, 0) + 1
    print(f"{len(runs)} feeds; BEFORE (Layer 1 run): {before}")

    t0 = time.perf_counter()
    after_rows = []

    def one(r: dict) -> dict:
        with make_client() as c:
            out = fetch_feed(c, r["url"])
        return {"url": r["url"], "category": r.get("category"), "before": "ok" if r["ok"] else classify_error(text=r["error"]),
                "after": "ok" if out.status == "ok" else out.result.error_kind or "other", "error": out.result.error,
                "ms": out.result.duration_ms,
                "active_90d": None if out.feed is None else _active(out.feed)}

    with ThreadPoolExecutor(a.concurrency) as ex:
        for i, f in enumerate(as_completed([ex.submit(one, r) for r in runs]), 1):
            after_rows.append(f.result())
            if i % 25 == 0:
                print(f"  {i}/{len(runs)} re-fetched, {time.perf_counter() - t0:.0f}s")
    after: dict[str, int] = {}
    for r in after_rows:
        after[r["after"]] = after.get(r["after"], 0) + 1
    moved = {}
    for r in after_rows:
        moved[f"{r['before']} -> {r['after']}"] = moved.get(f"{r['before']} -> {r['after']}", 0) + 1
    res = {"generated": time.strftime("%Y-%m-%d %H:%M:%S"), "feeds": len(runs), "before": before, "after": after, "transitions": moved,
           "ok_active_90d": sum(1 for r in after_rows if r["after"] == "ok" and r["active_90d"]),
           "seconds": round(time.perf_counter() - t0, 1), "rows": sorted(after_rows, key=lambda r: r["url"])}
    Path(a.out).write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(f"AFTER (Phase 1 fetcher): {after}")
    print(f"transitions: {moved}")
    print(f"ok and active in last 90 days: {res['ok_active_90d']}")
    return 0


def _active(pf) -> bool:
    from datetime import datetime, timedelta
    d = [e.published_at for e in pf.episodes if e.published_at]
    return bool(d) and max(d) >= datetime.utcnow() - timedelta(days=90)


if __name__ == "__main__":
    raise SystemExit(main())
