"""Compact the intelligence store (Phase 3 storage fix). Since Phase 3 the engine stores only QUALIFIED opportunities in full;
this removes what older runs left behind and reclaims the space:
  * opportunities that are below threshold, superseded, withdrawn or expired AND referenced by no event
  * gate rejections of every run except the latest per (member, kind)
then VACUUM. Run with the AI service stopped.      python scripts/compact_store.py"""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

DB = Path(__file__).resolve().parents[3] / "data" / "intel.db"


def mb(p: Path) -> float:
    return sum(f.stat().st_size for f in p.parent.glob(p.name + "*")) / 1e6


def main() -> int:
    if not DB.exists():
        print("no store at", DB)
        return 1
    before = mb(DB)
    c = sqlite3.connect(DB, timeout=60)
    n_opp = c.execute("""DELETE FROM opportunities WHERE (qualified = 0 OR status IN ('superseded','withdrawn','expired'))
                         AND id NOT IN (SELECT DISTINCT opportunity_id FROM opportunity_events)""").rowcount
    n_rej = c.execute("""DELETE FROM opportunity_rejections WHERE run_id NOT IN (
                           SELECT id FROM (SELECT id, ROW_NUMBER() OVER (PARTITION BY member_show_id, kind ORDER BY created_at DESC, id DESC) rn
                                           FROM opportunity_runs) WHERE rn = 1)""").rowcount
    c.commit()
    c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    c.execute("VACUUM")
    c.close()
    after = mb(DB)
    print(f"removed {n_opp} opportunity rows, {n_rej} old gate rejections; intel.db {before:.0f} MB -> {after:.0f} MB "
          f"(freed {before - after:.0f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
