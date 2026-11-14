"""Sponsor opportunities (type = sponsor) on the SHARED Layer 4 pipeline:

    candidates (brands seen on the member's lookalike shows / category) -> gates -> factors -> combine_rows (same Fit formula)
    -> evidence_confidence (same formula) + support adjustment -> readiness -> why-now -> rank (same thresholds / no padding)
    -> explain.build (same templates engine + faithfulness) -> engine.persist / list_for_member / events (same tables)

Only declared_sponsorship and likely_sponsorship (and human-reviewed ok) count as sponsorship history. Organic mentions,
self-promotion, affiliate links, podcast promos and ad-choices boilerplate never create a sponsor opportunity. No LLM."""
from __future__ import annotations

import copy
import hashlib
import json
import math
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..intel.db import session_scope
from ..intel.models import Episode, Show, now
from ..intel.normalize import resolve_root
from ..intel.trust import jobs
from ..intel.trust.audit import audit
from ..opportunities import engine, explain as ex, ranking
from ..opportunities.config import SPONSOR_DISMISS_REASONS, config_hash
from ..opportunities.confidence import evidence_confidence
from ..opportunities.factors import FactorResult, clip01, combine_rows
from ..opportunities.features import Corpus, ShowFeatures, days_between, redact
from ..opportunities.readiness import CONVERSION
from .detect import compact
from .models import Brand, BrandRegistration, SponsorshipEvent
from .resolve import effective_class, history_filter, seeds, display_name

CONFIG_PATH = Path(__file__).with_name("config.yaml")
FACTORS = ["lookalike_affinity", "momentum", "category_fit", "recency", "breadth", "audience_size_fit", "geo_fit"]
FIT_NOTE = "Vibe Logic draft — pending founder approval"
TIER_BY_CLASS = {"declared_sponsorship": ("verified", 0.9), "likely_sponsorship": ("estimated", 0.6)}


@lru_cache(maxsize=1)
def _cfg() -> dict:
    return yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))


def get_config() -> dict:
    return copy.deepcopy(_cfg())


# ───────────────────────── brand index (one load per run) ─────────────────────────
@dataclass
class Ev:
    id: int
    show_id: str
    episode_id: str
    date: datetime | None
    cls: str
    reviewed: bool
    snippet: str
    url: str | None
    episode_title: str = ""


@dataclass
class BrandIndex:
    brands: dict[str, Brand] = field(default_factory=dict)
    events: dict[str, list[Ev]] = field(default_factory=lambda: defaultdict(list))       # brand -> history events
    by_show: dict[str, dict[str, list[Ev]]] = field(default_factory=lambda: defaultdict(lambda: defaultdict(list)))
    registrations: dict[str, list[BrandRegistration]] = field(default_factory=lambda: defaultdict(list))
    titles: dict[str, str] = field(default_factory=dict)

    @classmethod
    def load(cls, s: Session) -> "BrandIndex":
        idx = cls()
        idx.brands = {b.id: b for b in s.scalars(select(Brand).where(Brand.merged_into.is_(None)))}
        rows = s.execute(select(SponsorshipEvent, Episode.title).join(Episode, Episode.id == SponsorshipEvent.episode_id, isouter=True)
                         .where(SponsorshipEvent.brand_id.is_not(None), history_filter()).order_by(SponsorshipEvent.id)).all()
        for e, title in rows:
            ce = effective_class(e)
            if ce not in TIER_BY_CLASS or e.brand_id not in idx.brands:
                continue
            ev = Ev(e.id, e.show_id, e.episode_id, e.episode_date, ce, e.verification_status == "reviewed_ok", e.snippet, e.url,
                    redact(title or "")[:160])
            idx.events[e.brand_id].append(ev)
            idx.by_show[e.show_id][e.brand_id].append(ev)
        for r in s.scalars(select(BrandRegistration)):
            idx.registrations[r.brand_id].append(r)
        idx.titles = {sh.id: sh.title for sh in s.scalars(select(Show))}
        return idx


# ───────────────────────── helpers ─────────────────────────
def _member_groups(m: ShowFeatures) -> set[str]:
    out = {str(x) for x in (m.val("category_group") or [])} | {str(x) for x in (m.val("declared_topics") or [])}
    out |= {t["id"] for t in (m.val("topics") or []) if isinstance(t, dict) and t.get("id")}
    return out


def _norm_set(vals) -> set[str]:
    return {compact(str(v)) for v in (vals or []) if str(v).strip()}


def _brand_cats(b: Brand) -> list[dict]:
    from .resolve import effective_categories
    return [c for c in effective_categories(b) if isinstance(c, dict) and c.get("id")]


def _ev_source(ev: Ev, factor_field: str) -> dict:
    tier, conf = ("verified", 1.0) if ev.reviewed else TIER_BY_CLASS[ev.cls]
    return {"field": factor_field, "side": "candidate", "tier": tier, "confidence": conf, "fresh": True, "method": "rule", "event_id": ev.id}


def _iso_d(d: datetime | None) -> str | None:
    return d.date().isoformat() if d else None


# ───────────────────────── candidates ─────────────────────────
def neighbours(corpus: Corpus, member_id: str, cfg: dict) -> dict[str, float]:
    """member's k nearest shows (content) + shows sharing a declared topic / category group -> similarity in [0,1]."""
    cc = cfg["candidates"]
    m = corpus.shows[member_id]
    sims = corpus.content_sims(member_id)
    out: dict[str, float] = {}

    def sim01(sid: str) -> float:
        c = corpus.cos(member_id, sid)
        z = corpus.z(c) if c is not None else None
        return 0.0 if z is None else round(clip01(z / 3.0), 4)
    for sid, _ in sorted(((k, v) for k, v in sims.items() if k != member_id), key=lambda kv: (-round(kv[1], 9), kv[0]))[: int(cc["k_neighbours"])]:
        out[sid] = sim01(sid)
    dm, gm = set(m.val("declared_topics") or []), set(m.val("category_group") or [])
    meta = []
    for sid in corpus.ids:
        if sid == member_id or sid in out:
            continue
        o = corpus.shows[sid]
        sc = 2 * len(dm & set(o.val("declared_topics") or [])) + len(gm & set(o.val("category_group") or []))
        if sc:
            meta.append((sid, sc))
    for sid, _ in sorted(meta, key=lambda kv: (-kv[1], kv[0]))[: int(cc["shared_metadata_max"])]:
        out[sid] = sim01(sid)
    return out


def candidates(idx: BrandIndex, nb: dict[str, float], cfg: dict) -> list[str]:
    seen: dict[str, float] = {}
    for sid, sim in nb.items():
        for bid in idx.by_show.get(sid, {}):
            seen[bid] = max(seen.get(bid, 0.0), sim)
    return [b for b, _ in sorted(seen.items(), key=lambda kv: (-kv[1], kv[0]))][: int(cfg["candidates"]["cap"])]


# ───────────────────────── gates (before scoring) ─────────────────────────
GATE_REASONS = ("inactive_brand", "already_sponsors_member", "blocked_brand", "blocked_brand_category", "sensitive_category_default",
                "competitor_exclusivity", "dismissed_recently", "contacted_recently", "already_partnered", "no_sponsorship_evidence",
                "insufficient_evidence")


def gate(m: ShowFeatures, b: Brand, idx: BrandIndex, cfg: dict, history: dict, as_of: datetime) -> tuple[str | None, dict]:
    g = cfg["gates"]
    evs = idx.events.get(b.id, [])
    if not evs:
        return "no_sponsorship_evidence", {"note": "only organic / self / affiliate / promo evidence"}
    if b.status != "active":
        return "inactive_brand", {"last_seen": _iso_d(b.last_seen), "status": b.status}
    if b.id in idx.by_show.get(m.show_id, {}):
        return "already_sponsors_member", {}
    blocked = _norm_set(m.val("creator.blocked_brands"))
    if blocked and ({compact(b.name), compact(b.primary_domain or "")} | {compact(a) for a in b.aliases or []}) & blocked:
        return "blocked_brand", {}
    cats = _brand_cats(b)
    bc = _norm_set(m.val("creator.blocked_brand_categories")) | _norm_set(m.val("creator.blocked_categories"))
    hit = [c["id"] for c in cats if compact(c["id"]) in bc or compact(c.get("label", "")) in bc]
    if hit:
        return "blocked_brand_category", {"categories": hit}
    groups = set(m.val("category_group") or []) | {t["id"] for t in (m.val("topics") or []) if isinstance(t, dict)} | set(m.val("declared_topics") or [])
    kids = groups & (set(g["sensitive_blocked_for_groups"]) | set(g["sensitive_blocked_for_topics"]))
    sens = [c["id"] for c in cats if c.get("sensitive")]
    if sens and kids:
        return "sensitive_category_default", {"categories": sens, "because": sorted(kids)}
    excl = _norm_set(m.val("creator.exclusive_categories"))
    if excl:
        mine = [idx.brands[x] for x in idx.by_show.get(m.show_id, {}) if x in idx.brands and x != b.id]
        held = {compact(c["id"]) for mb in mine for c in _brand_cats(mb)} & excl
        clash = [c["id"] for c in cats if compact(c["id"]) in held]
        if clash:
            return "competitor_exclusivity", {"categories": clash}
    from ..opportunities.gates import COOLDOWN_REASON
    cool = g.get("cooldown_days") or {}
    for etype, ts in sorted(history.get(b.id, []), key=lambda x: x[1], reverse=True):
        if etype in cool and days_between(as_of, ts) < float(cool[etype]):
            return COOLDOWN_REASON.get(etype, f"cooldown_{etype}"), {"event": etype, "days_ago": round(days_between(as_of, ts), 1)}
    if len(evs) < int(g["min_history_events"]) and all(e.cls == "likely_sponsorship" and not e.reviewed for e in evs):
        return "insufficient_evidence", {"events": len(evs), "only": "likely_sponsorship"}
    return None, {}


# ───────────────────────── factors ─────────────────────────
def f_lookalike(b: Brand, idx: BrandIndex, nb: dict[str, float], cfg: dict, as_of: datetime) -> FactorResult:
    c, cw = cfg["factors"]["lookalike_affinity"], cfg["class_weight"]
    raw, support, srcs = 0.0, [], []
    for sid, sim in sorted(nb.items(), key=lambda kv: (-kv[1], kv[0])):
        evs = idx.by_show.get(sid, {}).get(b.id)
        if not evs or sim <= 0:
            continue
        best = max(evs, key=lambda e: (float(cw[e.cls]) * (0.5 ** (max(0.0, days_between(as_of, e.date)) / float(c["half_life_days"])) if e.date else 0.0), e.id))
        w = float(cw[best.cls]) * (0.5 ** (max(0.0, days_between(as_of, best.date)) / float(c["half_life_days"])) if best.date else 0.0)
        raw += sim * w
        support.append({"show_id": sid, "show": idx.titles.get(sid, sid), "similarity": sim, "class": best.cls, "date": _iso_d(best.date),
                        "episode_title": best.episode_title, "snippet": redact(best.snippet)[:200], "event_id": best.id})
        srcs.append(_ev_source(best, "sponsorship_events"))
    if not support:
        return FactorResult("lookalike_affinity", "missing", None, {}, [], "brand not seen on the member's lookalike shows")
    return FactorResult("lookalike_affinity", "used", clip01(1.0 - math.exp(-raw / float(c["scale"]))),
                        {"supporting_shows": support[:5], "n_supporting_shows": len(support), "raw": round(raw, 4)}, srcs[:8])


def f_momentum(b: Brand, idx: BrandIndex, as_of: datetime) -> FactorResult:
    evs = [e for e in idx.events.get(b.id, []) if e.date]
    if not evs:
        return FactorResult("momentum", "missing", None, {}, [], "no dated sponsorship events")
    r = sum(1 for e in evs if 0 <= days_between(as_of, e.date) <= 90)
    p = sum(1 for e in evs if 90 < days_between(as_of, e.date) <= 180)
    return FactorResult("momentum", "used", (r + 1) / (r + p + 2), {"recent_90d": r, "prior_90d": p, "window_days": 90},
                        [_ev_source(e, "sponsorship_events") for e in evs[-3:]])


def f_category(b: Brand, m: ShowFeatures) -> FactorResult:
    cats = _brand_cats(b)
    if not cats:
        return FactorResult("category_fit", "missing", None, {}, [], "no brand categories")
    groups = _member_groups(m)
    defs = seeds()["categories"]
    best, match = 0.0, None
    for c in cats:
        rel = set(defs.get(c["id"], {}).get("related") or [])
        if rel & groups and 1.0 > best:
            best, match = 1.0, c
    manual = any(c.get("tier") == "manual" for c in cats)
    src = [{"field": "brand.categories", "side": "candidate", "tier": "creator_provided" if manual else "inferred",
            "confidence": 1.0 if manual else float(cats[0].get("confidence", 0.35)), "fresh": True, "method": cats[0].get("method", "model")}]
    return FactorResult("category_fit", "used", best, {"brand_categories": [c["label"] for c in cats],
                                                      "matched_category": match["label"] if match else None}, src)


def f_recency(b: Brand, cfg: dict, as_of: datetime) -> FactorResult:
    if not b.last_seen:
        return FactorResult("recency", "missing", None, {}, [], "never seen sponsoring")
    d = max(0.0, days_between(as_of, b.last_seen))
    return FactorResult("recency", "used", 0.5 ** (d / float(cfg["factors"]["recency"]["half_life_days"])),
                        {"days_since_last": int(d), "last_seen": _iso_d(b.last_seen)},
                        [{"field": "brand.last_seen", "side": "candidate", "tier": "verified", "confidence": 0.9, "fresh": True, "method": "rule"}])


def f_breadth(b: Brand, idx: BrandIndex, cfg: dict) -> FactorResult:
    n = len({e.show_id for e in idx.events.get(b.id, [])})
    if not n:
        return FactorResult("breadth", "missing", None, {}, [], "no sponsored shows")
    return FactorResult("breadth", "used", 1.0 - math.exp(-n / float(cfg["factors"]["breadth"]["scale"])), {"n_shows": n},
                        [{"field": "sponsorship_events", "side": "candidate", "tier": "verified", "confidence": 0.9, "fresh": True, "method": "rule"}])


def f_disabled(name: str) -> FactorResult:
    return FactorResult(name, "disabled", None, {}, [], "no audience data for the member and the brand's shows (needs creator analytics)")


# ───────────────────────── readiness, why-now, explanation ─────────────────────────
def readiness(b: Brand, idx: BrandIndex, m: ShowFeatures, cfg: dict, as_of: datetime) -> tuple[dict, dict]:
    rc = cfg["readiness"]
    groups = {compact(x) for x in _member_groups(m)}
    regs = [r for r in idx.registrations.get(b.id, []) if r.active_campaign]
    match = [r for r in regs if {compact(x) for x in (r.campaign_categories or [])} & groups]
    contact = ({"status": "registered", "label": "Registered on PodBae"} if regs else
               {"status": "website_only", "label": "Official website only (not a verified contact)", "website": f"https://{b.primary_domain}",
                "domain_verified": bool(b.domain_verified)} if b.primary_domain else
               {"status": "none", "label": "No contact known"})
    if match:
        return {"level": "verified", "label": "Verified", "reason": "Registered PodBae advertiser with an active campaign matching your show."}, contact
    declared = [e for e in idx.events.get(b.id, []) if e.cls == "declared_sponsorship" or e.reviewed]
    recent = b.last_seen and days_between(as_of, b.last_seen) <= float(rc["potential_recent_days"])
    if recent and len(declared) >= int(rc["potential_min_declared"]):
        return {"level": "potential_lead", "label": "Potential lead",
                "reason": f"Active podcast sponsor in the last {rc['potential_recent_days']} days with {len(declared)} declared sponsorships."}, contact
    return {"level": "discovery_lead", "label": "Discovery lead", "reason": "Seen sponsoring podcasts, but not recently enough / not declared often enough to count as a lead."}, contact


def why_now(s: Session, b: Brand, idx: BrandIndex, nb: dict[str, float], m: ShowFeatures, cfg: dict, as_of: datetime) -> list[dict]:
    w = cfg["why_now"]
    out = []
    for win in w["similar_windows"]:
        hits = {}
        for sid in nb:
            for e in idx.by_show.get(sid, {}).get(b.id, []):
                if e.date and 0 <= days_between(as_of, e.date) <= win and (sid not in hits or e.date > hits[sid].date):
                    hits[sid] = e
        if hits:
            ev = sorted(hits.values(), key=lambda e: (e.date, e.id), reverse=True)
            out.append({"code": "sponsor_similar_recent", "label": "Sponsoring shows like yours right now",
                        "evidence": [{"episode_id": e.episode_id, "date": _iso_d(e.date), "title": e.episode_title, "show": idx.titles.get(e.show_id, "")} for e in ev[:3]],
                        "detail": {"n_shows": len(hits), "window_days": win}})
            break
    mg = set(m.val("category_group") or [])
    if mg:
        from .resolve import _groups
        firsts = {}
        for e in idx.events.get(b.id, []):
            if not e.date:
                continue
            for g in set(_groups(s, e.show_id) or []) & mg:
                if g not in firsts or e.date < firsts[g].date:
                    firsts[g] = e
        for g, e in sorted(firsts.items()):
            if 0 <= days_between(as_of, e.date) <= float(w["category_start_days"]):
                out.append({"code": "sponsor_category_start", "label": "Started sponsoring your category",
                            "evidence": [{"episode_id": e.episode_id, "date": _iso_d(e.date), "title": e.episode_title, "show": idx.titles.get(e.show_id, "")}],
                            "detail": {"group": g}})
                break
    evs = [e for e in idx.events.get(b.id, []) if e.date]
    r = sum(1 for e in evs if 0 <= days_between(as_of, e.date) <= 90)
    p = sum(1 for e in evs if 90 < days_between(as_of, e.date) <= 180)
    if r >= int(w["rising_min_recent"]) and r >= float(w["rising_ratio"]) * max(p, 1):
        out.append({"code": "sponsor_rising", "label": "Activity rising", "evidence": [], "detail": {"recent_90d": r, "prior_90d": p, "window_days": 90}})
    for reg in idx.registrations.get(b.id, []):
        if reg.active_campaign and reg.campaign_started_at and 0 <= days_between(as_of, reg.campaign_started_at) <= float(w["campaign_days"]):
            out.append({"code": "sponsor_campaign", "label": "PodBae campaign just launched", "evidence": [],
                        "detail": {"started_on": _iso_d(reg.campaign_started_at)}})
            break
    return out


def factor_part(f: dict, target: str) -> dict | None:
    i = f["inputs"]
    n = f["name"]
    if n == "lookalike_affinity" and i.get("supporting_shows"):
        k = i["n_supporting_shows"]
        return ex.part("sponsor.lookalike.one" if k == 1 else "sponsor.lookalike", target=target, n=k,
                       shows=[x["show"] for x in i["supporting_shows"][:2]])
    if n == "momentum" and i.get("recent_90d", 0) > i.get("prior_90d", 0):
        return ex.part("sponsor.momentum", recent=i["recent_90d"], prior=i["prior_90d"], window=i["window_days"])
    if n == "category_fit" and i.get("matched_category"):
        return ex.part("sponsor.category", category=i["matched_category"])
    if n == "breadth":
        return ex.part("sponsor.breadth.one" if i["n_shows"] == 1 else "sponsor.breadth", n=i["n_shows"])
    if n == "recency":
        return ex.part("sponsor.recency", days=i["days_since_last"])
    return None


def why_part(t: dict) -> dict | None:
    d, e0 = t.get("detail") or {}, (t.get("evidence") or [{}])[0] if t.get("evidence") else {}
    if t["code"] == "sponsor_similar_recent":
        return ex.part("why.sponsor_similar_recent.one" if d["n_shows"] == 1 else "why.sponsor_similar_recent", n=d["n_shows"], days=d["window_days"])
    if t["code"] == "sponsor_category_start":
        return ex.part("why.sponsor_category_start", group=d["group"], date=e0["date"])
    if t["code"] == "sponsor_rising":
        return ex.part("why.sponsor_rising", recent=d["recent_90d"], prior=d["prior_90d"], window=d["window_days"])
    if t["code"] == "sponsor_campaign":
        return ex.part("why.sponsor_campaign", date=d["started_on"])
    return None


def build_explanation(rec: dict) -> dict:
    e = ex.build(rec, factor_part_fn=factor_part, why_part_fn=why_part, max_reasons=3)
    la = next((f for f in rec["factors"] if f["name"] == "lookalike_affinity" and f["status"] == "used"), None)
    if la and la["inputs"]["supporting_shows"]:
        s0 = la["inputs"]["supporting_shows"][0]
        if s0.get("snippet") and s0.get("date"):
            q = ex.part("sponsor.quote", snippet=s0["snippet"], show=s0["show"], date=s0["date"])
            parts = e["parts"][:-1] + [q] + e["parts"][-1:] if any(p["id"].startswith("why.") for p in e["parts"]) else e["parts"] + [q]
            e["parts"] = parts
            e["text"] = " ".join(p["text"] for p in parts)
    return e


# ───────────────────────── compute (pure) ─────────────────────────
def compute(s: Session, corpus: Corpus, idx: BrandIndex, member_id: str, cfg: dict | None = None, history: dict | None = None,
            seen: dict[str, int] | None = None) -> dict:
    cfg = cfg or get_config()
    if member_id not in corpus.shows:
        raise engine.NotFound(f"show {member_id} not in the store")
    m = corpus.shows[member_id]
    at = corpus.as_of
    nb = neighbours(corpus, member_id, cfg)
    cands = candidates(idx, nb, cfg)
    rejections, scored = [], []
    fc = cfg["factors"]
    for bid in cands:
        b = idx.brands[bid]
        reason, detail = gate(m, b, idx, cfg, history or {}, at)
        if reason:
            rejections.append({"candidate_show_id": bid, "reason": reason, "detail": detail})
            continue
        results = [(f_lookalike(b, idx, nb, cfg, at), fc["lookalike_affinity"]["weight"]), (f_momentum(b, idx, at), fc["momentum"]["weight"]),
                   (f_category(b, m), fc["category_fit"]["weight"]), (f_recency(b, cfg, at), fc["recency"]["weight"]),
                   (f_breadth(b, idx, cfg), fc["breadth"]["weight"]), (f_disabled("audience_size_fit"), fc["audience_size_fit"]["weight"]),
                   (f_disabled("geo_fit"), fc["geo_fit"]["weight"])]
        fit, rows = combine_rows([(r, float(w)) for r, w in results])
        conf = evidence_confidence(rows, cfg)
        nsup = next((f["inputs"].get("n_supporting_shows", 0) for f in rows if f["name"] == "lookalike_affinity"), 0)
        factor = round(min(1.0, 0.6 + 0.1 * nsup), 3)
        if factor < 1.0:
            v = round(conf["value"] * factor, 3)
            lv = cfg["confidence"]["levels"]
            conf = dict(conf, value=v, level="High" if v >= lv["high"] else "Medium" if v >= lv["medium"] else "Low",
                        adjustments=[{"code": "few_supporting_shows", "factor": factor, "detail": f"{nsup} supporting lookalike show(s)"}])
        rd, contact = readiness(b, idx, m, cfg, at)
        evs = sorted(idx.events.get(bid, []), key=lambda e: (e.date or datetime.min, e.id), reverse=True)
        scored.append({
            "target_show_id": bid, "target_title": display_name(b), "type": "sponsor", "type_reason": "brand seen sponsoring shows like yours",
            "target": {"brand_id": bid, "target_id": bid, "name": display_name(b), "title": display_name(b), "domain": b.primary_domain, "categories": [c["label"] for c in _brand_cats(b)],
                       "status": b.status, "is_member": False, "registered": bool(idx.registrations.get(bid))},
            "fit": fit, "factors": rows, "confidence": conf, "readiness": rd, "contact_status": contact, "conversion": CONVERSION,
            "why_now": [], "candidate_sources": ["lookalike_shows"], "gate": {},
            "evidence": {"events": [{"event_id": e.id, "class": e.cls, "reviewed": e.reviewed, "show_id": e.show_id, "show": idx.titles.get(e.show_id, ""),
                                     "episode_id": e.episode_id, "episode_title": e.episode_title, "date": _iso_d(e.date),
                                     "snippet": redact(e.snippet)[:220], "url": e.url} for e in evs[:6]],
                         "n_events": len(evs), "n_shows": len({e.show_id for e in evs})},
            "snapshot": {"as_of": at.isoformat() + "Z", "scoring_version": cfg["scoring_version"], "config_hash": config_hash(cfg),
                         "brand_events": len(evs), "brand_categories_method": b.category_method},
        })
    qualified = [r for r in scored if ranking.qualifies(r, cfg)]
    for r in qualified:
        r["why_now"] = why_now(s, idx.brands[r["target_show_id"]], idx, nb, m, cfg, at)
    ranked = sorted(qualified, key=lambda x: ranking.base_key(x, seen or {}))
    below = sorted((r for r in scored if not ranking.qualifies(r, cfg)), key=lambda x: ranking.base_key(x, seen or {}))
    for i, r in enumerate(ranked):
        r["rank"], r["qualified"] = i + 1, True
    for r in below:
        r["rank"], r["qualified"] = None, False
    for r in ranked + below:
        r["explanation"] = build_explanation(r)
        r["explanation"]["faithfulness_problems"] = ex.faithfulness(r["explanation"], r)
        r["evidence_ids"] = [e["episode_id"] for e in r["evidence"]["events"]]
        r["inputs_hash"] = hashlib.sha256(json.dumps({k: r[k] for k in ("target_show_id", "fit", "factors", "confidence", "readiness", "why_now", "rank")},
                                                     sort_keys=True, default=str).encode()).hexdigest()
    gate_counts: dict[str, int] = {}
    for x in rejections:
        gate_counts[x["reason"]] = gate_counts.get(x["reason"], 0) + 1
    return {"member_show_id": member_id, "as_of": at, "candidates": len(cands), "rejections": rejections, "scored": ranked + below,
            "qualified": ranked, "gate_counts": gate_counts, "state": state(ranked, m, gate_counts, cfg),
            "result_hash": hashlib.sha256(json.dumps([(r["target_show_id"], r["fit"], r["confidence"]["value"], r["rank"]) for r in ranked + below]).encode()).hexdigest()}


def state(qualified: list, m: ShowFeatures, gate_counts: dict, cfg: dict) -> dict:
    r = cfg["ranking"]
    if len(qualified) >= 3:
        return {"state": "ok", "message": None, "suggestions": []}
    why = (f"Only sponsors with Fit of at least {r['min_fit']} and evidence confidence of at least {r['min_confidence']} are shown; "
           "we never pad the list. We can only see sponsors that shows like yours name in their own show notes; dynamic ads "
           "inserted by hosting networks are invisible to us.")
    blocked = {k: v for k, v in gate_counts.items() if k in ("blocked_brand", "blocked_brand_category", "sensitive_category_default",
                                                            "competitor_exclusivity", "inactive_brand")}
    if blocked:
        why += " Excluded: " + ", ".join(f"{v} ({k.replace('_', ' ')})" for k, v in sorted(blocked.items())) + "."
    sugg = [{"code": "few_visible_sponsors", "action": "Few visible sponsors in your category",
             "detail": "Most shows like yours do not name their sponsors in show notes yet, so there is little evidence to match on."}]
    if not m.val("creator.blocked_brand_categories") and not m.val("creator.exclusive_categories"):
        sugg.append({"code": "set_sponsor_prefs", "action": "Set your sponsor preferences",
                     "detail": "Blocked brand categories and exclusive categories make the list more useful."})
    if not qualified:
        return {"state": "no_match", "message": "No good sponsor match yet. " + why, "suggestions": sugg}
    return {"state": "few", "message": f"Only {len(qualified)} strong sponsor match{'es' if len(qualified) > 1 else ''} right now. " + why,
            "suggestions": sugg}


# ───────────────────────── fingerprint / persist / job / list ─────────────────────────
def fingerprint(s: Session, member_id: str, cfg: dict | None = None) -> str:
    cfg = cfg or get_config()
    from ..opportunities.models import OpportunityEvent
    parts = [engine.fingerprint(s, member_id), cfg["scoring_version"], config_hash(cfg),
             s.scalar(select(func.max(SponsorshipEvent.id))), s.scalar(select(func.count()).select_from(SponsorshipEvent)),
             s.scalar(select(func.count()).select_from(Brand)), str(s.scalar(select(func.max(Brand.updated_at)))),
             str(s.scalar(select(func.max(BrandRegistration.updated_at)))),
             s.scalar(select(func.count()).select_from(OpportunityEvent).where(OpportunityEvent.member_show_id == member_id))]
    return hashlib.sha256(json.dumps(parts, default=str).encode()).hexdigest()


def generate(member_show_id: str, *, as_of: datetime | None = None, cfg: dict | None = None) -> dict:
    cfg = cfg or get_config()
    t0 = time.perf_counter()
    with session_scope() as s:
        member = resolve_root(s, member_show_id)
        if s.get(Show, member) is None:
            raise engine.NotFound(f"show {member_show_id} not found")
        at = as_of or now()
        fp = fingerprint(s, member, cfg)
        corpus = Corpus.load(s, at)
        idx = BrandIndex.load(s)
        res = compute(s, corpus, idx, member, cfg, engine.load_history(s, member, cfg), engine.seen_days(s, member, at, cfg)[0])
        run = engine.persist(s, res, cfg, fp, int((time.perf_counter() - t0) * 1000), kind="sponsor")
        audit(s, "engine", "sponsor_opportunities_generated", "show", member, {"run_id": run.id, "qualified": run.n_qualified})
        return {"run_id": run.id, "member_show_id": member, "kind": "sponsor", "scoring_version": run.scoring_version,
                "candidates": run.n_candidates, "rejected": run.n_rejected, "scored": run.n_scored, "qualified": run.n_qualified,
                "state": res["state"]["state"], "duration_ms": run.duration_ms, "gate_counts": res["gate_counts"]}


@jobs.register("sponsor_opportunities_generate")
def _job(ctx: jobs.JobContext) -> dict:
    return generate(ctx.payload["member_show_id"])


def enqueue(s: Session, member_show_id: str, *, force: bool = False) -> Any:
    cfg = get_config()
    member = resolve_root(s, member_show_id)
    if s.get(Show, member) is None:
        raise engine.NotFound(f"show {member_show_id} not found")
    key = f"sponsor_generate:{member}:{cfg['scoring_version']}:{fingerprint(s, member, cfg)[:16]}" + (f":force:{int(time.time())}" if force else "")
    return jobs.enqueue(s, "sponsor_opportunities_generate", key, {"member_show_id": member})


def list_for_member(s: Session, member_show_id: str, *, user_id: str | None = None, limit: int = 50, as_of: datetime | None = None,
                    auto_generate: bool = True) -> dict:
    cfg = get_config()
    out = engine.list_for_member(s, member_show_id, user_id=user_id, limit=limit, as_of=as_of, auto_generate=auto_generate, kind="sponsor",
                                 cfg=cfg, enqueue_fn=enqueue, fingerprint_fn=lambda s_, m_: fingerprint(s_, m_, cfg),
                                 state_fn=state, generating_message="Looking for sponsors seen on shows like yours…")
    out["fit_note"] = FIT_NOTE
    out["dismiss_reasons"] = list(SPONSOR_DISMISS_REASONS)
    return out
