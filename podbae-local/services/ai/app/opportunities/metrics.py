"""Admin metrics for the engine (latest run per member show)."""
from __future__ import annotations

from collections import Counter

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..intel.models import Show, ShowClaim
from .config import FACTORS, config_hash, get_config
from .models import Opportunity, OpportunityEvent, OpportunityRejection, OpportunityRun


def _hist(vals: list[float], edges: list[float]) -> list[dict]:
    out = []
    for lo, hi in zip(edges, edges[1:]):
        out.append({"from": lo, "to": hi, "n": sum(1 for v in vals if lo <= v < hi or (hi == edges[-1] and v == hi))})
    return out


def _latency(ms: list[int]) -> dict | None:
    if not ms:
        return None
    ms = sorted(ms)
    return {"median": ms[len(ms) // 2], "p95": ms[min(len(ms) - 1, int(0.95 * len(ms)))], "max": ms[-1], "runs": len(ms)}


def engine_metrics(s: Session) -> dict:
    cfg = get_config()
    sv = cfg["scoring_version"]
    latest: dict[str, OpportunityRun] = {}
    for r in s.scalars(select(OpportunityRun).where(OpportunityRun.scoring_version == sv).order_by(OpportunityRun.created_at, OpportunityRun.id)):
        latest[r.member_show_id] = r
    run_ids = [r.id for r in latest.values()]
    rej = Counter()
    if run_ids:
        rej.update(dict(s.execute(select(OpportunityRejection.reason, func.count()).where(OpportunityRejection.run_id.in_(run_ids))
                                  .group_by(OpportunityRejection.reason)).all()))
    active = list(s.scalars(select(Opportunity).where(Opportunity.status == "active", Opportunity.scoring_version == sv)))
    q = [o for o in active if o.qualified]
    cov = {f: Counter() for f in FACTORS}
    for o in active:
        for f in (o.breakdown_json or {}).get("factors") or []:
            cov[f["name"]][f["status"]] += 1
    n_act = len(active) or 1
    members = sorted({c.show_id for c in s.scalars(select(ShowClaim))})
    titles = {sh.id: sh.title for sh in s.scalars(select(Show).where(Show.id.in_(list(latest) + members)))} if (latest or members) else {}
    return {
        "scoring_version": sv, "status": cfg["status"], "config_hash": config_hash(cfg),
        "thresholds": {"min_fit": cfg["ranking"]["min_fit"], "min_confidence": cfg["ranking"]["min_confidence"]},
        "weights": {f: cfg["factors"][f]["weight"] for f in FACTORS},
        "counts": {"member_shows_with_runs": len(latest), "runs_total": s.scalar(select(func.count()).select_from(OpportunityRun)) or 0,
                   "opportunities_active": len(active), "opportunities_qualified": len(q),
                   "by_status": dict(s.execute(select(Opportunity.status, func.count()).group_by(Opportunity.status)).all()),
                   "by_readiness": dict(Counter(o.readiness for o in q)), "by_confidence_level": dict(Counter(o.confidence_level for o in q)),
                   "by_type": dict(Counter(o.type for o in q)),
                   "members_with_1_plus": sum(1 for r in latest.values() if r.n_qualified >= 1),
                   "members_with_3_plus": sum(1 for r in latest.values() if r.n_qualified >= 3),
                   "members_no_match": sum(1 for r in latest.values() if r.n_qualified == 0),
                   "events": dict(s.execute(select(OpportunityEvent.type, func.count()).group_by(OpportunityEvent.type)).all())},
        "gate_rejections": dict(rej.most_common()),
        "fit_distribution": _hist([o.fit for o in active], [0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100]),
        "confidence_distribution": _hist([o.confidence for o in active], [0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]),
        "factor_coverage": {f: {k: round(v / n_act, 3) for k, v in c.items()} for f, c in cov.items()},
        "latency_ms": _latency([r.duration_ms for r in latest.values()]),
        "runs": [{"member_show_id": m, "title": titles.get(m, m), "qualified": r.n_qualified, "scored": r.n_scored, "rejected": r.n_rejected,
                  "duration_ms": r.duration_ms, "created_at": r.created_at.isoformat() + "Z", "is_member": m in members}
                 for m, r in sorted(latest.items(), key=lambda kv: titles.get(kv[0], kv[0]))],
        "members": [{"show_id": m, "title": titles.get(m, m)} for m in members],
    }


def showcase_show(s: Session, exclude: set[str] | None = None, max_shows: int = 120) -> dict | None:
    """Demo helper: an English non-member show whose qualified list holds a Potential lead (declared contact route) and
    Discovery leads high up. member_suggestions = qualified Discovery leads the demo turns into members (-> Verified), always
    leaving one Discovery lead in place. Deterministic; scores at most max_shows shows."""
    from ..intel.models import now
    from .engine import compute
    from .features import Corpus
    cfg = get_config()
    c = Corpus.load(s, now())
    exclude = exclude or set()
    best = None
    tried = 0
    for sid in c.ids:
        sf = c.shows[sid]
        if sf.is_member or sid in exclude or sf.val("language") != "en":
            continue
        tried += 1
        if tried > max_shows:
            break
        q = compute(s, c, sid, cfg)["qualified"]
        lv = [x["readiness"]["level"] for x in q]
        if "potential_lead" not in lv or lv.count("discovery_lead") < 3:
            continue
        key = (lv.index("potential_lead"), -len(lv), sid)
        if best is None or key < best[0]:
            disc = [x["target_show_id"] for x in q if x["readiness"]["level"] == "discovery_lead"]
            best = (key, {"show_id": sid, "title": sf.title, "qualified": len(lv), "levels_top5": lv[:5], "member_suggestions": disc[1:3]})
    return best[1] if best else None
