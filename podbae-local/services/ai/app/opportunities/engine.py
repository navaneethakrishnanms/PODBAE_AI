"""Opportunity Engine, podcast partners only. Pipeline per member show:

    candidates -> eligibility gates -> compatibility (Fit) -> evidence confidence -> commercial readiness -> why-now
    -> rank (thresholds, MMR, no padding) -> explanation -> stored opportunities

`compute()` is pure (reads the store, writes nothing): same store contents + same scoring version + same as_of ->
identical scores, order and explanations. `generate()` = compute + persist. `list_for_member()` applies the per-user,
time-dependent parts (dismiss / cooldown suppression, seen-suppression, expiry) at read time. No LLM is called anywhere."""
from __future__ import annotations

import hashlib
import json
import time
from collections import Counter
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..intel.db import session_scope
from ..intel.models import CorpusStat, Embedding, Provenance, Show, ShowClaim, now
from ..intel.normalize import resolve_root
from ..intel.trust import jobs
from ..intel.trust.audit import audit
from . import candidates as cand
from . import explain as ex
from . import gates, ranking, whynow
from .config import DISMISS_REASONS, EVENT_TYPES, config_hash, get_config, scoring_version
from .confidence import apply_adjustments, evidence_confidence
from .factors import score_pair
from .features import Corpus, FieldVal, ShowFeatures, finite, redact
from .models import Opportunity, OpportunityEvent, OpportunityRejection, OpportunityRun
from .readiness import CONVERSION, readiness, website_url

FIT_NOTE = "Vibe Logic draft — pending founder approval"
ENGAGED = ("save", "open", "contact", "reply", "meeting", "partnership")


class NotFound(LookupError):
    pass


class EventError(ValueError):
    pass


def _h(x: Any) -> str:
    return hashlib.sha256(json.dumps(x, sort_keys=True, default=str).encode()).hexdigest()


def _iso(d: datetime | None) -> str | None:
    return d.isoformat() + "Z" if d else None


# ───────────────────────── interaction history (single source of truth: opportunity_events) ─────────────────────────
def load_history(s: Session, member_id: str, cfg: dict) -> dict[str, list[tuple[str, datetime]]]:
    types = list((cfg["gates"].get("cooldown_days") or {}).keys())
    out: dict[str, list[tuple[str, datetime]]] = {}
    for e in s.scalars(select(OpportunityEvent).where(OpportunityEvent.member_show_id == member_id, OpportunityEvent.type.in_(types))
                       .order_by(OpportunityEvent.ts, OpportunityEvent.id)):
        out.setdefault(e.target_show_id, []).append((e.type, e.ts))
    return out


def seen_days(s: Session, member_id: str, as_of: datetime, cfg: dict) -> tuple[dict[str, int], set[str]]:
    """(distinct days each target was shown in the seen window, targets the member engaged with in that window)."""
    since = as_of - timedelta(days=float(cfg["ranking"]["seen_window_days"]))
    days: dict[str, set] = {}
    engaged: set[str] = set()
    for e in s.scalars(select(OpportunityEvent).where(OpportunityEvent.member_show_id == member_id, OpportunityEvent.ts >= since)):
        if e.type == "impression":
            days.setdefault(e.target_show_id, set()).add(e.ts.date())
        elif e.type in ENGAGED:
            engaged.add(e.target_show_id)
    return {k: len(v) for k, v in days.items()}, engaged


def opp_type(m: ShowFeatures, c: ShowFeatures, cfg: dict) -> tuple[str, str]:
    mapping = cfg["types"]["goal_to_type"]
    for g in m.val("creator.goals") or []:
        key = str(g).strip().lower().replace(" ", "_").replace("-", "_")
        if key in mapping:
            return mapping[key], f"your goal: {str(g).strip()}"
    gs = float(cfg["types"]["guest_share_for_guest_swap"])
    gm, gc = finite(m.val("guest_friendliness")), finite(c.val("guest_friendliness"))
    if gm is not None and gc is not None and gm >= gs and gc >= gs:
        return "guest_swap", "both shows regularly run guest episodes"
    return "cross_promo", "default format (no goal set; not both guest-led)"


def _inputs_map(sf: ShowFeatures) -> dict[str, int]:
    return {f: fv.provenance_id for f, fv in sorted(sf.fields.items()) if not f.startswith("owner_")}


def target_summary(c: ShowFeatures) -> dict:
    return {"show_id": c.show_id, "title": c.title, "image": website_url(c.val("image")), "category_group": c.val("category_group") or [],
            "language": c.val("language"), "activity": c.val("activity_status") or c.activity,
            "description": redact(str(c.val("description") or ""))[:220],
            "website": None if c.is_member else website_url(c.val("website")),
            "contact_url": None if c.is_member else (readiness(c).get("contact_url")),
            "is_member": c.is_member, "member_user_id": c.member_user_id if c.is_member else None, "demo_member": c.demo_member}


# ───────────────────────── compute (pure) ─────────────────────────
def compute(s: Session, corpus: Corpus, member_id: str, cfg: dict | None = None,
            history: dict | None = None, seen: dict[str, int] | None = None) -> dict:
    cfg = cfg or get_config()
    if member_id not in corpus.shows:
        raise NotFound(f"show {member_id} not in the store")
    m = corpus.shows[member_id]
    history = history or {}
    cands = cand.generate(corpus, member_id, cfg)
    rejections: list[dict] = []
    scored: list[dict] = []
    for cd in cands:
        c = corpus.shows[cd["show_id"]]
        g = gates.check(m, c, cfg, history, corpus.as_of)
        if not g.passed:
            rejections.append({"candidate_show_id": c.show_id, "reason": g.reason, "detail": g.detail})
            continue
        fit, rows = score_pair(m, c, corpus, cfg)
        conf = apply_adjustments(evidence_confidence(rows, cfg), g.detail, cfg)
        typ, why_type = opp_type(m, c, cfg)
        scored.append({
            "target_show_id": c.show_id, "target_title": c.title, "target": target_summary(c), "type": typ, "type_reason": why_type,
            "fit": fit, "factors": rows, "confidence": conf, "readiness": readiness(c), "conversion": CONVERSION,
            "why_now": [], "candidate_sources": cd["sources"], "gate": g.detail,
            "snapshot": {"as_of": _iso(corpus.as_of), "scoring_version": cfg["scoring_version"], "config_hash": config_hash(cfg),
                         "corpus": {"n_shows": len(corpus.ids), "pair_mean": round(corpus.pair_mean or 0, 6), "pair_std": round(corpus.pair_std or 0, 6)},
                         "member_inputs": _inputs_map(m), "candidate_inputs": _inputs_map(c)},
        })
    qualified = [r for r in scored if ranking.qualifies(r, cfg)]
    for r in qualified:
        c = corpus.shows[r["target_show_id"]]
        shared = next(f for f in r["factors"] if f["name"] == "topic_alignment")["inputs"].get("shared_topics", [])
        r["why_now"] = whynow.triggers(s, corpus, m, c, shared, cfg)
    ranked = ranking.mmr(qualified, corpus, cfg, seen)
    for i, r in enumerate(ranked):
        r["rank"], r["qualified"] = i + 1, True
    below = sorted((r for r in scored if not ranking.qualifies(r, cfg)), key=lambda r: ranking.base_key(r, seen or {}))
    for r in below:
        r["rank"], r["qualified"] = None, False
    for r in ranked + below:
        r["explanation"] = ex.build(r)
        r["explanation"]["faithfulness_problems"] = ex.faithfulness(r["explanation"], r)
        r["evidence_ids"] = sorted({e["episode_id"] for t in r["why_now"] for e in t.get("evidence", [])})
        r["inputs_hash"] = _h({k: r[k] for k in ("target_show_id", "type", "fit", "factors", "confidence", "readiness", "why_now", "rank")})
    gate_counts = dict(Counter(x["reason"] for x in rejections))
    return {"member_show_id": member_id, "as_of": corpus.as_of, "candidates": len(cands), "rejections": rejections,
            "scored": ranked + below, "qualified": ranked, "gate_counts": gate_counts,
            "state": ranking.state(ranked, m, gate_counts, cfg),
            "result_hash": _h([(r["target_show_id"], r["fit"], r["confidence"]["value"], r["rank"]) for r in ranked + below])}


# ───────────────────────── fingerprint: "have the inputs changed since the last run?" ─────────────────────────
def fingerprint(s: Session, member_id: str, cfg: dict | None = None) -> str:
    cfg = cfg or get_config()
    types = list((cfg["gates"].get("cooldown_days") or {}).keys())
    return _h([cfg["scoring_version"], config_hash(cfg), s.scalar(select(func.max(Provenance.id))),
               s.scalar(select(func.count()).select_from(Show).where(Show.merged_into.is_(None))),
               s.scalar(select(func.max(ShowClaim.id))), s.scalar(select(func.count()).select_from(ShowClaim)),
               str(s.scalar(select(func.max(CorpusStat.updated_at)))), s.scalar(select(func.count()).select_from(Embedding)),
               s.scalar(select(func.count()).select_from(OpportunityEvent).where(OpportunityEvent.member_show_id == member_id,
                                                                                 OpportunityEvent.type.in_(types)))])


# ───────────────────────── persist ─────────────────────────
def kind_filter(kind: str):
    """partner and sponsor opportunities share the table; the type separates them."""
    return Opportunity.type == "sponsor" if kind == "sponsor" else Opportunity.type != "sponsor"


def run_stats(scored: list[dict]) -> dict:
    """Compact distribution of EVERY scored candidate (qualified or not): what the admin metrics need, without storing a
    full row per below-threshold candidate (that used ~8 KB x 200 candidates x every member x every run)."""
    fit_hist, conf_hist = [0] * 10, [0] * 10
    fac: dict[str, dict[str, int]] = {}
    for r in scored:
        fit_hist[min(9, int(r["fit"] // 10))] += 1
        conf_hist[min(9, int(r["confidence"]["value"] * 10))] += 1
        for f in r["factors"]:
            d = fac.setdefault(f["name"], {})
            d[f["status"]] = d.get(f["status"], 0) + 1
    return {"n_scored": len(scored), "fit_hist": fit_hist, "confidence_hist": conf_hist, "factor_status": fac}


def _has_events(s: Session, opp_id: str) -> bool:
    return bool(s.scalar(select(OpportunityEvent.id).where(OpportunityEvent.opportunity_id == opp_id).limit(1)))


def persist(s: Session, res: dict, cfg: dict, fp: str, duration_ms: int, kind: str = "partner") -> OpportunityRun:
    """Stores ONLY qualified opportunities in full (what members can see, explain and act on). Below-threshold candidates
    are summarised in run.stats. Rows that drop out are deleted unless an event references them (then kept as history)."""
    sv, as_of = cfg["scoring_version"], res["as_of"]
    member = res["member_show_id"]
    run = OpportunityRun(member_show_id=member, kind=kind, scoring_version=sv, config_hash=config_hash(cfg), inputs_fingerprint=fp,
                         as_of=as_of, n_candidates=res["candidates"], n_rejected=len(res["rejections"]), n_scored=len(res["scored"]),
                         n_qualified=len(res["qualified"]), duration_ms=duration_ms, result_hash=res["result_hash"],
                         stats={**run_stats(res["scored"]), "gate_counts": res["gate_counts"]})
    s.add(run)
    s.flush()
    old_runs = [r.id for r in s.scalars(select(OpportunityRun).where(OpportunityRun.member_show_id == member, OpportunityRun.kind == kind,
                                                                     OpportunityRun.id != run.id))]
    if old_runs:                      # only the latest run's gate rejections are kept (counts stay in each run's stats)
        s.query(OpportunityRejection).filter(OpportunityRejection.run_id.in_(old_runs)).delete(synchronize_session=False)
    for rj in res["rejections"]:
        s.add(OpportunityRejection(run_id=run.id, member_show_id=member, candidate_show_id=rj["candidate_show_id"], reason=rj["reason"],
                                   detail=rj["detail"]))
    existing = {o.target_show_id: o for o in s.scalars(select(Opportunity).where(Opportunity.member_show_id == member,
                                                                                  Opportunity.status == "active", kind_filter(kind)))}
    expires = as_of + timedelta(days=float(cfg["ranking"]["expiry_days"]))

    def retire(o: Opportunity, status: str) -> None:
        if _has_events(s, o.id):
            o.status = status
        else:
            s.delete(o)
    for r in res["qualified"]:
        o = existing.pop(r["target_show_id"], None)
        if o is not None and o.scoring_version == sv and o.inputs_hash == r["inputs_hash"]:
            o.run_id, o.expires_at, o.rank, o.qualified = run.id, expires, r["rank"], True
            continue
        if o is not None:
            retire(o, "superseded")
        s.add(Opportunity(
            member_show_id=member, type=r["type"], target_show_id=r["target_show_id"], fit=r["fit"],
            breakdown_json={"factors": r["factors"], "target": r["target"], "type_reason": r["type_reason"], "readiness": r["readiness"],
                            "candidate_sources": r["candidate_sources"], "gate": r["gate"], "confidence_detail": r["confidence"],
                            **({"evidence": r["evidence"]} if r.get("evidence") else {}),
                            **({"contact_status": r["contact_status"]} if r.get("contact_status") else {})},
            confidence=r["confidence"]["value"], confidence_level=r["confidence"]["level"], readiness=r["readiness"]["level"],
            conversion_status=CONVERSION["status"], why_now_json=r["why_now"], evidence_ids=r["evidence_ids"],
            explanation_json=r["explanation"], scoring_version=sv, feature_snapshot_json=r["snapshot"], inputs_hash=r["inputs_hash"],
            qualified=True, rank=r["rank"], status="active", run_id=run.id, expires_at=expires, created_at=as_of))
    for o in existing.values():
        retire(o, "withdrawn")     # below threshold now / gated out (dismissed, blocked) / no longer a candidate
    s.flush()
    return run


def generate(member_show_id: str, *, as_of: datetime | None = None, cfg: dict | None = None) -> dict:
    cfg = cfg or get_config()
    t0 = time.perf_counter()
    with session_scope() as s:
        member = resolve_root(s, member_show_id)
        if s.get(Show, member) is None:
            raise NotFound(f"show {member_show_id} not found")
        at = as_of or now()
        fp = fingerprint(s, member, cfg)
        corpus = Corpus.load(s, at)
        sd, _eng = seen_days(s, member, at, cfg)
        res = compute(s, corpus, member, cfg, load_history(s, member, cfg), sd)
        run = persist(s, res, cfg, fp, int((time.perf_counter() - t0) * 1000), kind="partner")
        audit(s, "engine", "opportunities_generated", "show", member,
              {"run_id": run.id, "qualified": run.n_qualified, "scored": run.n_scored, "rejected": run.n_rejected, "scoring_version": run.scoring_version})
        return {"run_id": run.id, "member_show_id": member, "scoring_version": run.scoring_version, "candidates": run.n_candidates,
                "rejected": run.n_rejected, "scored": run.n_scored, "qualified": run.n_qualified, "state": res["state"]["state"],
                "duration_ms": run.duration_ms, "gate_counts": res["gate_counts"]}


@jobs.register("opportunities_generate")
def _generate_job(ctx: jobs.JobContext) -> dict:
    return generate(ctx.payload["member_show_id"])


def enqueue_generate(s: Session, member_show_id: str, *, force: bool = False) -> Any:
    """Idempotent per show + scoring version + inputs fingerprint (force adds a time bucket: admin 'regenerate')."""
    cfg = get_config()
    member = resolve_root(s, member_show_id)
    if s.get(Show, member) is None:
        raise NotFound(f"show {member_show_id} not found")
    key = f"opp_generate:{member}:{cfg['scoring_version']}:{fingerprint(s, member, cfg)[:16]}" + (f":force:{int(time.time())}" if force else "")
    return jobs.enqueue(s, "opportunities_generate", key, {"member_show_id": member})


# ───────────────────────── read side ─────────────────────────
def _member_features(s: Session, show_id: str, as_of: datetime) -> ShowFeatures:
    sh = s.get(Show, show_id)
    sf = ShowFeatures(show_id, sh.title if sh else "", sh.activity if sh else None)
    rows = s.scalars(select(Provenance).where(Provenance.entity_type == "show", Provenance.entity_id == show_id,
                                              Provenance.superseded_by.is_(None)).order_by(Provenance.id))
    from ..intel.trust.provenance import TIER_RANK
    for p in rows:
        cur = sf.fields.get(p.field)
        if cur is None or TIER_RANK[p.data_tier] <= TIER_RANK[cur.tier]:
            sf.fields[p.field] = FieldVal(p.value_json, p.data_tier, p.confidence, p.expires_at is None or p.expires_at > as_of, p.method, "", p.id)
    return sf


def saved_targets(s: Session, member_id: str) -> set[str]:
    state: dict[str, bool] = {}
    for e in s.scalars(select(OpportunityEvent).where(OpportunityEvent.member_show_id == member_id, OpportunityEvent.type.in_(("save", "unsave")))
                       .order_by(OpportunityEvent.ts, OpportunityEvent.id)):
        state[e.target_show_id] = e.type == "save"
    return {k for k, v in state.items() if v}


def view(o: Opportunity, seen: dict[str, int] | None = None, today: set[str] | None = None, saved: set[str] | None = None) -> dict:
    b = o.breakdown_json or {}
    factors = b.get("factors") or []
    cd = b.get("confidence_detail") or {}
    st = {k: [f["name"] for f in factors if f["status"] == k] for k in ("used", "missing", "disabled")}
    shared = next((f["inputs"].get("shared_topics", []) for f in factors if f["name"] == "topic_alignment"), [])
    return {
        "id": o.id, "member_show_id": o.member_show_id, "type": o.type, "type_label": ex.TYPE_LABEL.get(o.type, o.type),
        "type_reason": b.get("type_reason"), "target": b.get("target") or {"show_id": o.target_show_id},
        "fit": {"value": round(o.fit, 1), "note": FIT_NOTE, "scoring_version": o.scoring_version},
        "confidence": {"value": o.confidence, "level": o.confidence_level, "coverage": cd.get("coverage"),
                       "input_quality": cd.get("input_quality"), "missing_factors": cd.get("missing_factors", []),
                       "disabled_factors": cd.get("disabled_factors", []), "formula": cd.get("formula"),
                       "adjustments": cd.get("adjustments", [])},
        "readiness": _readiness_view(o, b), "conversion": dict(CONVERSION),
        "why_now": o.why_now_json or [],
        "evidence": b.get("evidence") or {"shared_topics": [t["name"] for t in shared][:5], "episode_ids": o.evidence_ids or []},
        **({"contact_status": b["contact_status"]} if b.get("contact_status") else {}),
        "explanation": {"text": (o.explanation_json or {}).get("text"), "parts": (o.explanation_json or {}).get("parts", []),
                        "method": (o.explanation_json or {}).get("method", "template")},
        "breakdown": {"factors": factors, "used": st["used"], "missing": st["missing"], "disabled": st["disabled"]},
        "qualified": o.qualified, "rank": o.rank, "status": o.status, "scoring_version": o.scoring_version,
        "created_at": _iso(o.created_at), "expires_at": _iso(o.expires_at),
        "seen_days": (seen or {}).get(o.target_show_id, 0), "impressed_today": o.target_show_id in (today or set()),
        "saved": o.target_show_id in (saved or set()),
    }


def _readiness_view(o: Opportunity, b: dict) -> dict:
    if b.get("readiness"):
        return dict(b["readiness"])
    t = b.get("target") or {}
    from .readiness import LABELS
    lvl = o.readiness
    out = {"level": lvl, "label": LABELS.get(lvl, lvl)}
    if t.get("is_member"):
        out["contact_route"] = "in_app"
    elif t.get("website"):
        out["contact_route"], out["website"] = "website", t["website"]
    else:
        out["contact_route"] = "none"
    return out


def list_for_member(s: Session, member_show_id: str, *, user_id: str | None = None, limit: int = 50,
                    as_of: datetime | None = None, auto_generate: bool = True, kind: str = "partner", cfg: dict | None = None,
                    enqueue_fn=None, fingerprint_fn=None, state_fn=None, generating_message: str = "Finding partners for your show\u2026") -> dict:
    """Shared read side for every opportunity kind. kind='sponsor' passes its own enqueue / fingerprint / no-match-state hooks."""
    cfg = cfg or get_config()
    enqueue_fn = enqueue_fn or enqueue_generate
    fingerprint_fn = fingerprint_fn or (lambda s_, m_: fingerprint(s_, m_, cfg))
    at = as_of or now()
    member = resolve_root(s, member_show_id)
    if s.get(Show, member) is None:
        raise NotFound(f"show {member_show_id} not found")
    sv = cfg["scoring_version"]
    base = {"member_show_id": member, "scoring_version": sv, "status": cfg["status"], "fit_note": FIT_NOTE,
            "thresholds": {"min_fit": cfg["ranking"]["min_fit"], "min_confidence": cfg["ranking"]["min_confidence"]}}
    run = s.scalar(select(OpportunityRun).where(OpportunityRun.member_show_id == member, OpportunityRun.scoring_version == sv,
                                                OpportunityRun.kind == kind)
                   .order_by(OpportunityRun.created_at.desc(), OpportunityRun.id.desc()).limit(1))
    job = None
    if run is None:
        if auto_generate:
            job = enqueue_fn(s, member)
        return {**base, "kind": kind, "state": "generating", "items": [], "message": generating_message, "suggestions": [],
                "job": {"id": job.id, "status": job.status} if job else None, "generated_at": None, "stale": False,
                "shown_today_target_ids": [], "total_qualified": 0}
    stale = fingerprint_fn(s, member) != run.inputs_fingerprint
    for o in s.scalars(select(Opportunity).where(Opportunity.member_show_id == member, Opportunity.status == "active",
                                                 Opportunity.expires_at <= at, kind_filter(kind))):
        o.status = "expired"
    rows = list(s.scalars(select(Opportunity).where(Opportunity.member_show_id == member, Opportunity.status == "active",
                                                    Opportunity.qualified.is_(True), Opportunity.scoring_version == sv, kind_filter(kind))
                          .order_by(Opportunity.rank, Opportunity.target_show_id)))
    expired_all = not rows and s.scalar(select(func.count()).select_from(Opportunity).where(
        Opportunity.member_show_id == member, Opportunity.status == "expired", Opportunity.run_id == run.id))
    if (stale or expired_all) and auto_generate:
        job = enqueue_fn(s, member)
    history = load_history(s, member, cfg)
    cool = cfg["gates"].get("cooldown_days") or {}
    suppressed = {t for t, evs in history.items() for typ, ts in evs if typ in cool and (at - ts).total_seconds() / 86400 < float(cool[typ])}
    sd, engaged = seen_days(s, member, at, cfg)
    max_days = int(cfg["ranking"]["seen_max_days"])
    seen_supp = {t for t, n in sd.items() if n >= max_days and t not in engaged}
    today = {e.target_show_id for e in s.scalars(select(OpportunityEvent).where(
        OpportunityEvent.member_show_id == member, OpportunityEvent.type == "impression",
        OpportunityEvent.ts >= datetime(at.year, at.month, at.day),
        *( [OpportunityEvent.user_id == user_id] if user_id else [] )))}
    visible = [o for o in rows if o.target_show_id not in suppressed and (o.target_show_id not in seen_supp or o.target_show_id in today)]
    saved = saved_targets(s, member)
    items = [view(o, sd, today, saved) for o in visible[: int(limit)]]
    from ..llm_refine.phraser import attach      # Phase 4: cached AI phrasing if any (no provider call here); template otherwise
    items = attach(s, items)
    m = _member_features(s, member, at)
    gate_counts = dict(s.execute(select(OpportunityRejection.reason, func.count()).where(OpportunityRejection.run_id == run.id)
                                 .group_by(OpportunityRejection.reason)).all())
    st = (state_fn or ranking.state)([{"x": 1}] * len(visible), m, gate_counts, cfg)
    return {**base, **st, "kind": kind, "items": items, "total_qualified": len(visible), "generated_at": _iso(run.created_at), "run_id": run.id,
            "stale": stale, "job": {"id": job.id, "status": job.status} if job else None,
            "suppressed": {"dismissed_or_contacted": len(suppressed & {o.target_show_id for o in rows}),
                           "seen_too_often": len(seen_supp & {o.target_show_id for o in rows} - today)},
            "shown_today_target_ids": sorted(today)}


def get_opportunity(s: Session, opp_id: str) -> Opportunity:
    o = s.get(Opportunity, opp_id)
    if o is None:
        raise NotFound("opportunity not found")
    return o


def explain_view(s: Session, opp_id: str) -> dict:
    o = get_opportunity(s, opp_id)
    b = o.breakdown_json or {}
    rec = {"target_title": (b.get("target") or {}).get("title", ""), "type": o.type, "fit": o.fit,
           "confidence": {"level": o.confidence_level}, "factors": b.get("factors") or [], "why_now": o.why_now_json or []}
    e = o.explanation_json or {}
    return {"opportunity_id": o.id, "explanation": e, "faithfulness_problems": ex.faithfulness(e, rec) if e.get("parts") else ["no explanation"],
            "breakdown": b.get("factors") or [], "why_now": o.why_now_json or [], "confidence": b.get("confidence_detail"),
            "scoring_version": o.scoring_version, "status": "draft-unapproved-by-founder", "method": e.get("method", "template")}


# ───────────────────────── events ─────────────────────────
def record_events(s: Session, events: list[dict]) -> list[dict]:
    out = []
    for ev in events:
        typ = ev.get("type")
        if typ not in EVENT_TYPES:
            raise EventError(f"unknown event type {typ!r}")
        if typ == "dismiss" and ev.get("reason") not in DISMISS_REASONS:
            raise EventError(f"dismiss needs a reason, one of {list(DISMISS_REASONS)}")
        if typ == "impression" and not (isinstance(ev.get("position"), int) and ev["position"] >= 1):
            raise EventError("impression needs a 1-based position")
        key = ev.get("idempotency_key")
        if key:
            prior = s.scalar(select(OpportunityEvent).where(OpportunityEvent.idempotency_key == key))
            if prior is not None:
                out.append({"id": prior.id, "type": prior.type, "deduplicated": True})
                continue
        o = get_opportunity(s, ev["opportunity_id"])
        e = OpportunityEvent(opportunity_id=o.id, member_show_id=o.member_show_id, target_show_id=o.target_show_id,
                             user_id=(str(ev["user_id"]) if ev.get("user_id") is not None else None), type=typ,
                             position=ev.get("position"), reason=ev.get("reason"), note=(ev.get("note") or None),
                             scoring_version=o.scoring_version, idempotency_key=key, ts=now())
        s.add(e)
        s.flush()
        out.append({"id": e.id, "type": typ, "deduplicated": False})
    shown = sorted({ev["opportunity_id"] for ev in events if ev.get("type") == "impression"})
    if shown:   # Phase 4: phrase (lazily, budgeted, in a job) only the cards the app actually SHOWED
        from ..llm_refine import phraser
        if phraser.enabled():
            from ..llm_refine.jobs import enqueue_phrasing
            enqueue_phrasing(s, shown)
    return out
