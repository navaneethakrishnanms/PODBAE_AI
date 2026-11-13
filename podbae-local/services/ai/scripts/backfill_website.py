"""Phase 2 one-off: store each show's public website (RSS <channel><link>) for Layer 4 commercial readiness.

Phase 1 parsed <link> but did not store it. New ingests now record it (field 'website', verified, http(s) only, never
mailto). This script re-reads each existing feed ONCE (plain GET through the same SSRF-checked fetcher, no conditional
headers so we get a body) and records ONLY the website field. Nothing else in the profile is touched; no LLM.
    python scripts/backfill_website.py [--workers 6]"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.envfile import load_env  # noqa: E402

load_env()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=6)
    a = ap.parse_args()
    from sqlalchemy import select
    from app import intel
    from app.intel.connectors.base import make_client
    from app.intel.connectors.rss import fetch_feed
    from app.intel.db import session_scope
    from app.intel.ingest import public_website
    from app.intel.models import Show
    from app.intel.trust.provenance import get_source, live_rows, record
    intel.startup(start_worker=False)
    with session_scope() as s:
        todo = [(sh.id, sh.canonical_feed_url) for sh in s.scalars(select(Show).where(Show.merged_into.is_(None)).order_by(Show.id))
                if not live_rows(s, "show", sh.id, "website")]
    print(f"{len(todo)} shows without a stored website", flush=True)
    t0 = time.perf_counter()

    def one(item):
        sid, url = item
        with make_client() as c:
            out = fetch_feed(c, url)
        if out.status != "ok" or out.feed is None:
            return sid, "fetch_" + (out.result.error_kind or "error"), None
        site = public_website(out.feed.link)
        return sid, ("ok" if site else "no_public_link"), site

    with ThreadPoolExecutor(a.workers) as ex:
        results = list(ex.map(one, todo))
    stats = Counter(r[1] for r in results)
    with session_scope() as s:
        rss = get_source(s, "rss", "rss")
        for sid, st, site in results:
            if site:
                record(s, "show", sid, "website", site, source=rss, tier="verified", method="parsed",
                       source_ref="RSS <channel><link> (Phase 2 website backfill)")
    summary = {"shows": len(todo), "outcomes": dict(stats), "seconds": round(time.perf_counter() - t0, 1)}
    print(json.dumps(summary, indent=1))
    (Path(__file__).resolve().parents[1] / "eval" / "website_backfill.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
