"""Human review of sponsorship detections + brand administration (merge / split / category correction, audited).

Review queue = every UNCERTAIN detection (excluded from sponsorship history until reviewed) + a STRATIFIED random sample of
auto-accepted detections per class (deterministic: events whose sample_bucket < k, so the sample is stable and unbiased).
Verdicts are stored per reviewer; an event's verification_status follows the latest verdict. Precision per class is
computed only from reviewed sample events (majority verdict when several reviewers rated the same event)."""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from itertools import combinations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..intel.labels import cohen_kappa
from ..intel.models import Episode, Show, now
from ..intel.trust.audit import audit
from ..opportunities.features import redact
from .models import EVIDENCE_CLASSES, Brand, BrandDomain, BrandRegistration, SponsorReview, SponsorshipEvent
from .resolve import refresh_stats, resolve, seeds

REVIEWER_RX = re.compile(r"^[\w .@'-]{1,80}$")
EXCLUDED_REVIEWERS = {"claude", "claude-draft"}
SAMPLE_CLASSES = [c for c in EVIDENCE_CLASSES if c != "uncertain"]


class ReviewError(ValueError):
    pass


def _event_view(s: Session, e: SponsorshipEvent, mine: dict[int, SponsorReview] | None = None) -> dict:
    ep = s.get(Episode, e.episode_id)
    sh = s.get(Show, e.show_id)
    r = (mine or {}).get(e.id)
    return {"event_id": e.id, "class": e.cls, "rule": e.rule, "show_id": e.show_id, "show": sh.title if sh else e.show_id,
            "episode_id": e.episode_id, "episode_title": redact(ep.title if ep else "")[:200], "date": e.episode_date.date().isoformat() if e.episode_date else None,
            "source": e.source, "snippet": redact(e.snippet), "url": e.url, "domain": e.domain, "brand_name": e.brand_name,
            "brand_id": e.brand_id, "promo_code": e.promo_code, "method": e.method, "verification_status": e.verification_status,
            "my_verdict": ({"verdict": r.verdict, "correct_class": r.correct_class} if r else None),
            "rules_vs_ai": _ai_view(e)}


def _llm_on() -> bool:
    from ..llm_refine import llm_active
    return llm_active()


def _ai_view(e: SponsorshipEvent) -> dict | None:
    """Phase 4: the LLM's second opinion next to the rule class (shown only while the LLM is active). Humans decide."""
    if not e.llm_task or not _llm_on():
        return None
    ai = e.llm_cls or e.llm_raw_cls
    return {"rule_class": e.cls, "ai_class": ai, "ai_said": e.llm_raw_cls, "ai_reason": redact(e.llm_reason or ""),
            "ai_quote": redact(e.llm_quote or ""), "task": e.llm_task, "version": e.llm_version, "flagged": bool(e.llm_flag),
            "disagree": bool(ai and ai != e.cls)}


def disagreement_filter():
    return SponsorshipEvent.llm_task.is_not(None) & ((SponsorshipEvent.llm_cls.is_not(None) & (SponsorshipEvent.llm_cls != SponsorshipEvent.cls))
                                                    | (SponsorshipEvent.llm_flag.is_(True)))


def queue(s: Session, reviewer: str | None, per_class: int = 8, max_uncertain: int = 60, filter: str | None = None) -> dict:
    if filter == "disagree":     # Phase 4: "Rules vs AI disagree" first; AI is never a reviewer, a human decides each one
        mine = {r.event_id: r for r in s.scalars(select(SponsorReview).where(SponsorReview.reviewer == reviewer))} if reviewer else {}
        dis = [] if not _llm_on() else list(s.scalars(select(SponsorshipEvent).where(disagreement_filter())
                                                     .order_by(SponsorshipEvent.llm_flag.desc(), SponsorshipEvent.sample_bucket, SponsorshipEvent.id).limit(120)))
        items = [dict(_event_view(s, e, mine), queue="disagree") for e in dis]
        return {"items": items, "classes": list(EVIDENCE_CLASSES), "done": sum(1 for i in items if i["my_verdict"]), "total": len(items),
                "filter": "disagree", "instructions": "Rules and AI disagree on these. Your verdict is the ground truth: ok = the RULE "
                "class is right (or pick the right class); reject = not evidence. The AI's answer is shown only to help you look."}
    mine = {r.event_id: r for r in s.scalars(select(SponsorReview).where(SponsorReview.reviewer == reviewer))} if reviewer else {}
    unc = list(s.scalars(select(SponsorshipEvent).where(SponsorshipEvent.cls == "uncertain").order_by(SponsorshipEvent.sample_bucket,
                                                                                                         SponsorshipEvent.id).limit(max_uncertain)))
    sample = []
    for c in SAMPLE_CLASSES:
        sample += list(s.scalars(select(SponsorshipEvent).where(SponsorshipEvent.cls == c).order_by(SponsorshipEvent.sample_bucket,
                                                                                                     SponsorshipEvent.id).limit(per_class)))
    items = [dict(_event_view(s, e, mine), queue="uncertain") for e in unc] + [dict(_event_view(s, e, mine), queue="sample") for e in sample]
    return {"items": items, "classes": list(EVIDENCE_CLASSES), "done": sum(1 for i in items if i["my_verdict"]), "total": len(items),
            "filter": None, "instructions": "Is this detection classified correctly? ok = the class is right (for 'uncertain', pick the right class); "
                            "reject = not evidence of anything. Only declared / likely sponsorship counts as sponsorship history."}


def save(s: Session, event_id: int, reviewer: str, verdict: str, correct_class: str | None = None, note: str | None = None) -> dict:
    rv = (reviewer or "").strip()
    if not REVIEWER_RX.match(rv) or rv.lower() in EXCLUDED_REVIEWERS:
        raise ReviewError("invalid reviewer name (machine-written reviews are not accepted)")
    if verdict not in ("ok", "reject"):
        raise ReviewError("verdict must be ok or reject")
    e = s.get(SponsorshipEvent, event_id)
    if e is None:
        raise ReviewError("detection not found")
    cc = correct_class or (e.cls if verdict == "ok" else None)
    if verdict == "ok" and cc not in EVIDENCE_CLASSES:
        raise ReviewError("pick the correct class")
    if verdict == "ok" and cc == "uncertain":
        raise ReviewError("an 'ok' review must name a definite class")
    r = s.scalar(select(SponsorReview).where(SponsorReview.event_id == event_id, SponsorReview.reviewer == rv))
    if r is None:
        r = SponsorReview(event_id=event_id, reviewer=rv, verdict=verdict, correct_class=cc, original_class=e.cls, note=note)
        s.add(r)
    else:
        r.verdict, r.correct_class, r.note, r.updated_at = verdict, cc, note, now()
    if verdict == "reject":
        e.verification_status, e.reviewed_class = "reviewed_rejected", None
    else:
        e.verification_status, e.reviewed_class = "reviewed_ok", cc
    s.flush()
    resolve(s)                       # a reviewed-ok uncertain detection may now create / extend a brand
    audit(s, f"reviewer:{rv}", "sponsor_review", "sponsorship_event", str(event_id), {"verdict": verdict, "class": cc, "was": e.cls})
    return {"event_id": event_id, "reviewer": rv, "verdict": verdict, "correct_class": cc, "verification_status": e.verification_status}


def precision(s: Session) -> dict:
    by_event: dict[int, list[SponsorReview]] = defaultdict(list)
    for r in s.scalars(select(SponsorReview)):
        if r.reviewer.lower() not in EXCLUDED_REVIEWERS:
            by_event[r.event_id].append(r)
    per = {}
    for c in EVIDENCE_CLASSES:
        ok = n = 0
        for eid, rs in by_event.items():
            if rs[0].original_class != c:
                continue
            votes = Counter("ok" if (r.verdict == "ok" and r.correct_class == c) else "no" for r in rs)
            n += 1
            ok += votes["ok"] > votes["no"]
        per[c] = {"reviewed": n, "correct": ok, "precision": round(ok / n, 3) if n else None}
    reviewers = sorted({r.reviewer for rs in by_event.values() for r in rs})
    pairs = []
    for a, b in combinations(reviewers, 2):
        both = [(next(x for x in rs if x.reviewer == a), next(x for x in rs if x.reviewer == b)) for rs in by_event.values()
                if {a, b} <= {x.reviewer for x in rs}]
        if both:
            va = [f"{x.verdict}:{x.correct_class}" for x, _ in both]
            vb = [f"{y.verdict}:{y.correct_class}" for _, y in both]
            pairs.append({"a": a, "b": b, "shared": len(both), "agreement": round(sum(x == y for x, y in zip(va, vb)) / len(both), 3),
                          "kappa": cohen_kappa(va, vb)})
    return {"per_class": per, "reviewers": reviewers, "reviewed_events": len(by_event), "agreement": pairs,
            "note": None if by_event else "No human reviews yet: per-class precision is UNMEASURED."}


# ───────────────────────── brands admin ─────────────────────────
def brand_view(s: Session, b: Brand, events: int = 0) -> dict:
    doms = [{"domain": d.domain, "source": d.source} for d in s.scalars(select(BrandDomain).where(BrandDomain.brand_id == b.id))]
    out = {"id": b.id, "name": b.name, "primary_domain": b.primary_domain, "identity": b.identity, "domains": doms, "aliases": b.aliases or [],
           "parent_brand_id": b.parent_brand_id, "status": b.status, "categories": b.categories or [], "category_method": b.category_method,
           "domain_verified": b.domain_verified, "first_seen": b.first_seen.isoformat() + "Z" if b.first_seen else None,
           "last_seen": b.last_seen.isoformat() + "Z" if b.last_seen else None, "n_shows": b.n_shows, "n_events": b.n_events,
           "registered": bool(s.scalar(select(BrandRegistration.id).where(BrandRegistration.brand_id == b.id).limit(1)))}
    from .resolve import display_name, effective_categories
    out["display_name"] = display_name(b)
    out["effective_categories"] = effective_categories(b)
    out["rules_vs_ai"] = _brand_ai(b)
    if events:
        evs = s.scalars(select(SponsorshipEvent).where(SponsorshipEvent.brand_id == b.id).order_by(SponsorshipEvent.episode_date.desc()).limit(events))
        out["events"] = [_event_view(s, e) for e in evs]
    return out


def _brand_ai(b: Brand) -> dict | None:
    if not _llm_on() or not (b.llm_categories_version or b.name_suggestion_status):
        return None
    rule_ids = sorted(c.get("id") for c in (b.categories or []))
    ai_ids = sorted(c.get("id") for c in (b.llm_categories or []))
    return {"rule_categories": b.categories or [], "ai_categories": b.llm_categories or [], "ai_version": b.llm_categories_version,
            "categories_disagree": bool(b.llm_categories) and rule_ids != ai_ids and b.category_method not in ("manual", "override"),
            "name_suggestion": b.name_suggestion, "name_status": b.name_suggestion_status, "name_support": b.name_suggestion_support,
            "name_pending": b.name_suggestion_status == "pending"}


def name_decision(s: Session, brand_id: str, action: str, actor: str) -> dict:
    """Admin one-click approve / reject of a suggested display name (approved names apply even with the LLM off)."""
    b = s.get(Brand, brand_id)
    if b is None or not b.name_suggestion:
        raise ReviewError("no name suggestion for this brand")
    if action not in ("approve", "reject"):
        raise ReviewError("action must be approve or reject")
    b.name_suggestion_status = "approved" if action == "approve" else "rejected"
    audit(s, f"admin:{actor}", f"brand_name_{action}", "brand", b.id, {"name": b.name, "suggestion": b.name_suggestion})
    s.flush()
    return brand_view(s, b)


def list_brands(s: Session, q: str | None = None, status: str | None = None, limit: int = 100, offset: int = 0,
                filter: str | None = None) -> dict:
    query = select(Brand).where(Brand.merged_into.is_(None), Brand.n_events > 0)
    if filter == "disagree":     # Phase 4: brands where AI categories differ from the rule ones, or a name awaits approval
        query = query.where((Brand.llm_categories.is_not(None)) | (Brand.name_suggestion_status == "pending")) if _llm_on() else query.where(False)
    if status:
        query = query.where(Brand.status == status)
    if q:
        query = query.where(func.lower(Brand.name).contains(q.lower()) | func.lower(Brand.primary_domain).contains(q.lower()))
    total = s.scalar(select(func.count()).select_from(query.subquery()))
    rows = list(s.scalars(query.order_by(Brand.n_shows.desc(), Brand.n_events.desc(), Brand.name).limit(limit).offset(offset)))
    cats = seeds()["categories"]
    views = [brand_view(s, b) for b in rows]
    if filter == "disagree":
        views = [v for v in views if v["rules_vs_ai"] and (v["rules_vs_ai"]["categories_disagree"] or v["rules_vs_ai"]["name_pending"])]
        total = len(views)
    return {"total": total, "brands": views, "filter": filter,
            "category_options": [{"id": k, "label": v["label"], "sensitive": bool(v.get("sensitive"))} for k, v in cats.items()]}


def merge(s: Session, source_id: str, target_id: str, actor: str) -> dict:
    src, tgt = s.get(Brand, source_id), s.get(Brand, target_id)
    if src is None or tgt is None or src.id == tgt.id:
        raise ReviewError("pick two different existing brands")
    s.query(BrandDomain).filter(BrandDomain.brand_id == src.id).update({BrandDomain.brand_id: tgt.id, BrandDomain.source: "manual"})
    s.query(SponsorshipEvent).filter(SponsorshipEvent.brand_id == src.id).update({SponsorshipEvent.brand_id: tgt.id})
    tgt.aliases = sorted(set(tgt.aliases or []) | set(src.aliases or []) | {src.name})
    if not tgt.primary_domain and src.primary_domain:
        tgt.primary_domain, src.primary_domain = src.primary_domain, None
        tgt.identity = "manual"
    src.merged_into, src.status = tgt.id, "unknown"
    s.flush()
    refresh_stats(s)
    audit(s, f"admin:{actor}", "brand_merge", "brand", tgt.id, {"source": source_id, "source_name": src.name})
    return brand_view(s, tgt)


def split(s: Session, brand_id: str, domain: str, actor: str) -> dict:
    b = s.get(Brand, brand_id)
    bd = s.scalar(select(BrandDomain).where(BrandDomain.domain == domain.lower(), BrandDomain.brand_id == brand_id))
    if b is None or bd is None:
        raise ReviewError("that domain does not belong to this brand")
    if b.primary_domain == bd.domain and s.scalar(select(func.count()).select_from(BrandDomain).where(BrandDomain.brand_id == brand_id)) == 1:
        raise ReviewError("cannot split the only domain off a brand")
    nb = Brand(name=bd.domain.split(".")[0].capitalize(), name_key=bd.domain.split(".")[0], primary_domain=None, identity="manual", aliases=[])
    s.add(nb)
    s.flush()
    if b.primary_domain == bd.domain:
        b.primary_domain = None
    nb.primary_domain = bd.domain
    bd.brand_id, bd.source = nb.id, "manual"
    s.query(SponsorshipEvent).filter(SponsorshipEvent.brand_id == brand_id, SponsorshipEvent.domain == bd.domain).update({SponsorshipEvent.brand_id: nb.id})
    s.flush()
    refresh_stats(s)
    audit(s, f"admin:{actor}", "brand_split", "brand", brand_id, {"domain": bd.domain, "new_brand": nb.id})
    return {"from": brand_view(s, b), "new": brand_view(s, nb)}


def set_categories(s: Session, brand_id: str, category_ids: list[str], actor: str) -> dict:
    b = s.get(Brand, brand_id)
    cats = seeds()["categories"]
    bad = [c for c in category_ids if c not in cats]
    if b is None or bad:
        raise ReviewError(f"unknown brand or categories {bad}")
    before = [c["id"] for c in b.categories or []]
    b.categories = [{"id": c, "label": cats[c]["label"], "score": 1.0, "method": "manual", "tier": "manual",
                     "sensitive": bool(cats[c].get("sensitive"))} for c in category_ids]
    b.category_method = "manual"
    s.flush()
    audit(s, f"admin:{actor}", "brand_categories", "brand", brand_id, {"before": before, "after": category_ids})
    return brand_view(s, b)


def sync_registrations(s: Session, advertisers: list[dict]) -> dict:
    """Registered PodBae advertisers -> brands, by REGISTRABLE DOMAIN only (never by name). Unmatched ones are reported."""
    from .domains import registrable
    linked, unmatched = 0, []
    for a in advertisers:
        dom = registrable(a.get("domain") or "") if a.get("domain") else None
        bd = s.scalar(select(BrandDomain).where(BrandDomain.domain == dom)) if dom else None
        if bd is None:
            unmatched.append(a.get("advertiser_ref"))
            continue
        link(s, bd.brand_id, a, "domain")
        linked += 1
    return {"linked": linked, "unmatched": unmatched}


def link(s: Session, brand_id: str, a: dict, linked_by: str) -> BrandRegistration:
    from datetime import datetime
    r = s.scalar(select(BrandRegistration).where(BrandRegistration.brand_id == brand_id, BrandRegistration.advertiser_ref == str(a["advertiser_ref"])))
    if r is None:
        r = BrandRegistration(brand_id=brand_id, advertiser_ref=str(a["advertiser_ref"]), linked_by=linked_by)
        s.add(r)
    r.active_campaign = bool(a.get("active_campaign"))
    r.campaign_categories = list(a.get("campaign_categories") or [])
    st = a.get("campaign_started_at")
    r.campaign_started_at = datetime.fromisoformat(st.replace("Z", "")) if isinstance(st, str) and st else None
    r.updated_at = now()
    s.flush()
    return r


def show_sponsors(s: Session, show_id: str) -> dict:
    """Public 'Sponsors seen': ONLY declared sponsorships (or human-reviewed ok). Likely / affiliate / organic never shown."""
    rows = list(s.scalars(select(SponsorshipEvent).where(SponsorshipEvent.show_id == show_id, SponsorshipEvent.brand_id.is_not(None),
                                                         ((SponsorshipEvent.cls == "declared_sponsorship") & (SponsorshipEvent.verification_status != "reviewed_rejected"))
                                                         | ((SponsorshipEvent.verification_status == "reviewed_ok") & (SponsorshipEvent.reviewed_class == "declared_sponsorship")))
                          .order_by(SponsorshipEvent.episode_date.desc())))
    by: dict[str, list[SponsorshipEvent]] = defaultdict(list)
    for e in rows:
        by[e.brand_id].append(e)
    out = []
    for bid, evs in by.items():
        b = s.get(Brand, bid)
        if b is None:
            continue
        out.append({"brand_id": bid, "name": b.name, "domain": b.primary_domain, "episodes": len(evs),
                    "last_seen": evs[0].episode_date.date().isoformat() if evs[0].episode_date else None,
                    "example": redact(evs[0].snippet)[:200], "reviewed": any(e.verification_status == "reviewed_ok" for e in evs)})
    out.sort(key=lambda x: (-x["episodes"], x["name"]))
    return {"show_id": show_id, "sponsors": out, "basis": "Declared in the show's own notes (explicit sponsor phrase or ad section), "
                                                        "or confirmed by a human reviewer. Dynamic ads inserted by hosting networks are not visible to us."}
