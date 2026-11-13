"""Brand identity resolution + status + inferred categories. Deterministic; no LLM; no fetching.

Identity rules:
  * same registrable domain -> same brand (brand_domains.domain is unique)
  * a NAME joins a domain brand only via (a) the same sentence naming the domain's label ('BetterHelp' next to
    betterhelp.com: a domain match) or (b) the manual alias seed / an admin mapping. Never via name similarity.
  * a name with no domain match stays its own name-only brand (identity='name_only'), keyed by its exact normalised name.
  * denylisted platforms never become brands (detect.py drops them before any brand exists).
Status: active if a sponsorship event (declared / likely / reviewed-ok) in the last 180 days, else inactive.
Categories: e5 similarity of the brand's ad snippets to the fixed brand-category list (inferred, with evidence), plus the
co-occurring show category groups; the override file and admin edits win (method manual)."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import timedelta
from functools import lru_cache
from pathlib import Path

import numpy as np
import yaml
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..intel.linalg import mm
from ..intel.models import now
from ..intel.trust.provenance import live_rows
from .detect import compact
from .domains import label
from .models import Brand, BrandDomain, SponsorshipEvent

SEED = Path(__file__).with_name("seed")
ACTIVE_DAYS = 180
LIKELY_WEIGHT = 0.5


@lru_cache(maxsize=1)
def seeds() -> dict:
    a = yaml.safe_load((SEED / "brand_aliases.yaml").read_text(encoding="utf-8")) or {}
    o = yaml.safe_load((SEED / "category_overrides.yaml").read_text(encoding="utf-8")) or {}
    c = yaml.safe_load((SEED / "categories.yaml").read_text(encoding="utf-8")) or {}
    return {"aliases": {compact(k): v.lower() for k, v in (a.get("aliases") or {}).items()},
            "parents": {k.lower(): v.lower() for k, v in (a.get("parents") or {}).items() if k.lower() != v.lower()},
            "names": {k.lower(): v for k, v in (a.get("names") or {}).items()},
            "overrides": {k.lower(): v for k, v in (o.get("overrides") or {}).items()},
            "categories": c.get("categories") or {}, "categories_version": c.get("version")}


def history_filter():
    """SQL filter: events that count as sponsorship history."""
    return or_(SponsorshipEvent.cls.in_(("declared_sponsorship", "likely_sponsorship")) & (SponsorshipEvent.verification_status != "reviewed_rejected"),
               (SponsorshipEvent.verification_status == "reviewed_ok") & SponsorshipEvent.reviewed_class.in_(("declared_sponsorship", "likely_sponsorship")))


def effective_class(e: SponsorshipEvent) -> str | None:
    if e.verification_status == "reviewed_rejected":
        return None
    if e.verification_status == "reviewed_ok" and e.reviewed_class:
        return e.reviewed_class
    return e.cls


def _brand_for_domain(s: Session, domain: str, cache: dict) -> Brand:
    if domain in cache:
        return cache[domain]
    bd = s.scalar(select(BrandDomain).where(BrandDomain.domain == domain))
    if bd is not None:
        b = s.get(Brand, bd.brand_id)
    else:
        nm = seeds()["names"].get(domain) or label(domain).capitalize()
        b = Brand(name=nm, name_key=compact(nm), primary_domain=domain, identity="domain", aliases=[])
        s.add(b)
        s.flush()
        s.add(BrandDomain(domain=domain, brand_id=b.id, source="detected"))
        s.flush()
    while b.merged_into:
        b = s.get(Brand, b.merged_into)
    cache[domain] = b
    return b


def resolve(s: Session) -> dict:
    sd = seeds()
    cache: dict[str, Brand] = {}
    rows = list(s.scalars(select(SponsorshipEvent).where(history_filter() | (SponsorshipEvent.cls == "uncertain")).order_by(SponsorshipEvent.id)))
    # pass 1: domain brands (+ same-sentence name aliases)
    alias_to_domain: dict[str, str] = dict(sd["aliases"])
    for e in rows:
        if e.domain and effective_class(e) in ("declared_sponsorship", "likely_sponsorship"):
            b = _brand_for_domain(s, e.domain, cache)
            e.brand_id = b.id
            for a in (e.brand_name and [e.brand_name] or []):
                if compact(a) == compact(label(e.domain)) and a not in (b.aliases or []):
                    b.aliases = sorted(set(b.aliases or []) | {a})
            for a in b.aliases or []:                      # names SEEN in the same sentence as this domain
                alias_to_domain.setdefault(compact(a), e.domain)
    # pass 2: names -> domain brand only via a domain match (same-sentence alias) or the manual seed; else name-only brand
    by_key: dict[str, Brand] = {b.name_key: b for b in s.scalars(select(Brand).where(Brand.identity == "name_only", Brand.merged_into.is_(None)))}
    for e in rows:
        if e.domain or not e.brand_name or effective_class(e) not in ("declared_sponsorship", "likely_sponsorship"):
            continue
        k = compact(e.brand_name)
        if not k:
            continue
        dom = alias_to_domain.get(k)
        if dom:
            e.brand_id = _brand_for_domain(s, dom, cache).id
            continue
        b = by_key.get(k)
        if b is None:
            b = Brand(name=e.brand_name.strip(), name_key=k, primary_domain=None, identity="name_only", aliases=[])
            s.add(b)
            s.flush()
            by_key[k] = b
        e.brand_id = b.id
    # manual seed: alias domains that never appeared as a URL still get their domain row (source alias_seed)
    for dom in set(sd["aliases"].values()):
        if dom in cache and not s.scalar(select(BrandDomain).where(BrandDomain.domain == dom)):
            s.add(BrandDomain(domain=dom, brand_id=cache[dom].id, source="alias_seed"))
    # parents (seed, deterministic): both brands must exist
    for child, parent in sd["parents"].items():
        cb, pb = cache.get(child), (cache.get(parent) or (_brand_for_domain(s, parent, cache) if child in cache else None))
        if cb is not None and pb is not None and cb.id != pb.id:
            cb.parent_brand_id = pb.id
    s.flush()
    return refresh_stats(s)


def refresh_stats(s: Session) -> dict:
    at = now()
    hist: dict[str, list[SponsorshipEvent]] = defaultdict(list)
    for e in s.scalars(select(SponsorshipEvent).where(SponsorshipEvent.brand_id.is_not(None))):
        if effective_class(e) in ("declared_sponsorship", "likely_sponsorship"):
            hist[e.brand_id].append(e)
    counts = Counter()
    for b in s.scalars(select(Brand).where(Brand.merged_into.is_(None))):
        ev = hist.get(b.id, [])
        dates = [e.episode_date for e in ev if e.episode_date]
        b.n_events, b.n_shows = len(ev), len({e.show_id for e in ev})
        b.first_seen, b.last_seen = (min(dates), max(dates)) if dates else (None, None)
        b.status = "unknown" if not dates else ("active" if at - b.last_seen <= timedelta(days=ACTIVE_DAYS) else "inactive")
        counts[b.status] += 1
    s.flush()
    return {"brands": sum(counts.values()), "by_status": dict(counts)}


# ───────────────────────── categories ─────────────────────────
def categorize(s: Session, *, max_snippets: int = 6) -> dict:
    """Infer brand categories from ad snippets (local e5) + record co-occurring show groups. Manual edits are kept."""
    from ..intel.vectors import embed_queries, get_embedder
    sd = seeds()
    cats = sd["categories"]
    ids = list(cats)
    qmat = embed_queries([cats[c]["description"] for c in ids]).astype(np.float64)
    emb = get_embedder()
    done = Counter()
    for b in s.scalars(select(Brand).where(Brand.merged_into.is_(None), Brand.n_events > 0)):
        if b.category_method == "manual":
            done["manual_kept"] += 1
            continue
        ov = sd["overrides"].get((b.primary_domain or "").lower())
        if ov:
            b.categories = [{"id": c, "label": cats[c]["label"], "score": 1.0, "method": "override", "tier": "manual",
                             "sensitive": bool(cats[c].get("sensitive"))} for c in ov if c in cats]
            b.category_method = "override"
            done["override"] += 1
            continue
        ev = list(s.scalars(select(SponsorshipEvent).where(SponsorshipEvent.brand_id == b.id, history_filter())
                            .order_by(SponsorshipEvent.episode_date.desc(), SponsorshipEvent.id).limit(max_snippets)))
        texts = [f"{b.name}. {e.snippet}" for e in ev] or [b.name]
        v = np.asarray(emb.embed(texts), dtype=np.float64).mean(axis=0)
        v = v / (np.sqrt((v * v).sum()) or 1.0)
        sims = mm(qmat, v)
        rel = sims - sims.mean()
        order = np.argsort(-rel)
        top = [int(order[0])] + [int(j) for j in order[1:3] if rel[j] >= rel[order[0]] - 0.01]
        groups = Counter(g for e in ev for g in (_groups(s, e.show_id) or []))
        b.categories = [{"id": ids[j], "label": cats[ids[j]]["label"], "score": round(float(rel[j]), 4), "method": "model", "tier": "inferred",
                         "confidence": 0.35, "sensitive": bool(cats[ids[j]].get("sensitive")), "evidence_event_ids": [e.id for e in ev[:3]],
                         "co_occurring_show_groups": dict(groups.most_common(3))} for j in top]
        b.category_method = "inferred"
        done["inferred"] += 1
    s.flush()
    return dict(done)


_gcache: dict[str, list] = {}


def _groups(s: Session, show_id: str) -> list:
    if show_id not in _gcache:
        r = live_rows(s, "show", show_id, "category_group")
        _gcache[show_id] = r[0].value_json if r else []
    return _gcache[show_id]
