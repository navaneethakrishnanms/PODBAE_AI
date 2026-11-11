"""Cost ledger + budgets. Every external call / LLM call / GPU job is logged with an estimated cost and is
subject to a budget. Callers do:

    decision = check(s, estimate_usd, podcast_id=..., user_id=...)
    if not decision.ok: log skip + degrade gracefully
    else: do the work, then charge(...) with the real units.

Cache hits are logged too (cost 0, cache_hit=True) so the hit rate is measurable.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import Budget, CostLedger, now
from .audit import audit

PERIOD = {"day": timedelta(days=1), "month": timedelta(days=30)}


@dataclass
class Decision:
    ok: bool
    reason: str | None = None


def ensure_default_budgets(s: Session) -> None:
    cfg = get_settings()
    defaults = [("global", "*", "month", cfg.budget_global_monthly), ("podcast", "*", "month", cfg.budget_podcast_monthly)]
    for scope, key, period, limit in defaults:
        if s.scalar(select(Budget.id).where(Budget.scope == scope, Budget.key == key, Budget.period == period)) is None:
            s.add(Budget(scope=scope, key=key, period=period, limit_usd=limit, used_usd=0, period_start=now()))
    s.flush()


def _applicable(s: Session, podcast_id: str | None, user_id: str | None, tier: str | None) -> list[Budget]:
    ensure_default_budgets(s)
    wanted = [("global", "*"), ("global", "all")]
    if podcast_id:
        wanted += [("podcast", podcast_id), ("podcast", "*")]
    if user_id:
        wanted += [("user", user_id), ("user", "*")]
    if tier:
        wanted += [("tier", tier)]
    rows = [b for b in s.scalars(select(Budget)) if (b.scope, b.key) in wanted]
    t = now()
    for b in rows:  # roll the period over
        if t - b.period_start >= PERIOD.get(b.period, timedelta(days=30)):
            b.period_start, b.used_usd = t, 0.0
    return rows


def _used(s: Session, b: Budget, podcast_id: str | None, user_id: str | None) -> float:
    """'*' budgets apply per key: sum that key's ledger rows in the period instead of the shared counter."""
    if b.key != "*" or b.scope == "global":
        return b.used_usd
    col = CostLedger.podcast_id if b.scope == "podcast" else CostLedger.user_id
    key = podcast_id if b.scope == "podcast" else user_id
    if key is None:
        return 0.0
    return float(s.scalar(select(func.coalesce(func.sum(CostLedger.cost_estimate_usd), 0.0)).where(
        col == key, CostLedger.ts >= b.period_start)) or 0.0)


def check(s: Session, estimate_usd: float, *, podcast_id: str | None = None, user_id: str | None = None,
          tier: str | None = None) -> Decision:
    for b in _applicable(s, podcast_id, user_id, tier):
        if _used(s, b, podcast_id, user_id) + estimate_usd > b.limit_usd + 1e-12:
            return Decision(False, f"budget exceeded: {b.scope}:{b.key}/{b.period} limit ${b.limit_usd:.4f}")
    return Decision(True)


def charge(s: Session, operation: str, provider: str, units: float, unit_cost: float, *, podcast_id: str | None = None,
           user_id: str | None = None, cache_hit: bool = False, note: str | None = None) -> CostLedger:
    cost = 0.0 if cache_hit else units * unit_cost
    row = CostLedger(operation=operation, provider=provider, units=units, unit_cost_estimate=unit_cost,
                     cost_estimate_usd=cost, podcast_id=podcast_id, user_id=user_id, cache_hit=cache_hit, note=note)
    s.add(row)
    if cost and not cache_hit:
        for b in _applicable(s, podcast_id, user_id, None):
            if b.key != "*" or b.scope == "global":
                b.used_usd += cost
    s.flush()
    return row


def skip(s: Session, operation: str, provider: str, reason: str, podcast_id: str | None = None) -> None:
    """Budget refusal: logged in the ledger (0 cost) and the audit log; caller degrades gracefully."""
    s.add(CostLedger(operation=operation, provider=provider, units=0, unit_cost_estimate=0, cost_estimate_usd=0,
                     podcast_id=podcast_id, cache_hit=False, note=f"SKIPPED: {reason}"[:200]))
    audit(s, "budget", "skipped", "show" if podcast_id else None, podcast_id, {"operation": operation, "reason": reason})


def summary(s: Session, since: datetime | None = None) -> dict:
    q = select(CostLedger)
    if since:
        q = q.where(CostLedger.ts >= since)
    rows = list(s.scalars(q))
    by_op: dict[str, dict] = {}
    for r in rows:
        d = by_op.setdefault(r.operation, {"calls": 0, "cache_hits": 0, "skipped": 0, "usd": 0.0})
        d["calls"] += 1
        d["cache_hits"] += int(r.cache_hit)
        d["skipped"] += int((r.note or "").startswith("SKIPPED"))
        d["usd"] += r.cost_estimate_usd
    per_show: dict[str, float] = {}
    for r in rows:
        if r.podcast_id:
            per_show[r.podcast_id] = per_show.get(r.podcast_id, 0.0) + r.cost_estimate_usd
    vals = sorted(per_show.values())
    p95 = vals[min(len(vals) - 1, int(0.95 * len(vals)))] if vals else 0.0
    hits = sum(int(r.cache_hit) for r in rows)
    lookups = [r for r in rows if r.operation in ("llm_extract", "embed")]
    lh = sum(int(r.cache_hit) for r in lookups)
    return {
        "total_usd": round(sum(r.cost_estimate_usd for r in rows), 6),
        "by_operation": {k: {**v, "usd": round(v["usd"], 6)} for k, v in by_op.items()},
        "shows_costed": len(per_show),
        "avg_usd_per_show": round(sum(vals) / len(vals), 6) if vals else 0.0,
        "p95_usd_per_show": round(p95, 6),
        "cache_hit_rate_enrichment": round(lh / len(lookups), 3) if lookups else None,
        "cache_hits_total": hits,
        "budgets": [{"scope": b.scope, "key": b.key, "period": b.period, "limit_usd": b.limit_usd,
                     "used_usd": round(b.used_usd, 6)} for b in s.scalars(select(Budget))],
    }
