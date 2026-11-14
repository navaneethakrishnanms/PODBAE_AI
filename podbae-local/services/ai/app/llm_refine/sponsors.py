"""Phase 4 sponsor refiners (Layer 2). All are second opinions stored NEXT TO the rule result; humans still decide.

  uncertain_classify  the 'uncertain' detections -> one of the 8 classes, with a reason and a verbatim quote from the snippet
                      or its context window. The LLM may NOT create declared_sponsorship on its own: a 'declared' or
                      'likely' verdict becomes likely_sponsorship (weight 0.5) unless a rule already found an explicit
                      sponsor phrase ("sponsored by", ad header) in that event.
  organic_audit       a deterministic sample of organic_mention events, stratified by brand: did the rules miss a
                      sponsorship? Promoted events become likely_sponsorship AND are flagged for human review. Reports a
                      miss-rate estimate; the full 21,975 are NOT re-run unless the sample says it is worth it.
  brand_categories    active brands -> the fixed 28 categories, each with a verbatim quote from the brand's own ad text;
                      a SENSITIVE category needs a quote that itself contains a sensitive keyword. Manual / override win.
  brand_names         domain-derived names ("Uncommongoods") -> a clean name found verbatim in snippets. Applied
                      automatically only if the exact string appears in >= 2 snippets; otherwise pending admin approval.
"""
from __future__ import annotations

import math
import random
import re
from collections import Counter, defaultdict
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..intel.config import get_settings
from ..intel.models import Episode, Transcript
from ..sponsors.detect import compact, no_contacts
from ..sponsors.domains import label as domain_label
from ..sponsors.models import EVIDENCE_CLASSES, Brand, SponsorshipEvent
from ..sponsors.resolve import SENSITIVE_LEXICON, history_filter, seeds
from . import client

PV = {"uncertain_classify": "uncertain-v2", "organic_audit": "organic-v1", "brand_categories": "brandcat-v1", "brand_names": "brandname-v1"}
HISTORY = ("declared_sponsorship", "likely_sponsorship")
EXPLICIT_RULE = re.compile(r"^(explicit:|ad_block_header)")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ClassVerdict(_Strict):
    id: int
    cls: Literal["declared_sponsorship", "likely_sponsorship", "affiliate", "podcast_promo", "self_promotion", "network_disclosure",
                 "organic_mention", "uncertain"]
    reason: str = Field(default="", max_length=160)
    quote: str = Field(default="", max_length=300)


class ClassOut(_Strict):
    items: list[ClassVerdict] = Field(default_factory=list, max_length=12)


class AuditVerdict(_Strict):
    id: int
    sponsored: bool
    reason: str = Field(default="", max_length=160)
    quote: str = Field(default="", max_length=300)


class AuditOut(_Strict):
    items: list[AuditVerdict] = Field(default_factory=list, max_length=12)


class CatPick(_Strict):
    id: str = Field(max_length=40)
    quote: str = Field(max_length=300)


class CatOut(_Strict):
    categories: list[CatPick] = Field(default_factory=list, max_length=2)


class NameOut(_Strict):
    name: str = Field(default="", max_length=80)
    quote: str = Field(default="", max_length=300)


def _version(pv: str) -> str:
    p = client.get_llm_provider()
    return f"{p.model_version if p else 'none'}/{pv}"[:120]


# ───────────────────────── context windows ─────────────────────────
def context_window(s: Session, e: SponsorshipEvent, half: int = 350) -> str:
    """The text around the snippet in its episode notes / transcript (contact lines removed). '' if not locatable."""
    if e.source == "transcript":
        tr = s.get(Transcript, e.episode_id)
        text = tr.text if tr else ""
    else:
        ep = s.get(Episode, e.episode_id)
        text = f"{ep.title}\n{ep.description or ''}" if ep else ""
    core = re.sub(r"\s+", " ", (e.snippet or "").replace("[contact details removed]", " ")).strip()[:40]
    flat = re.sub(r"\s+", " ", text)
    i = flat.lower().find(core.lower()) if len(core) >= 12 else -1
    if i < 0:
        return ""
    return no_contacts(flat[max(0, i - half): i + len(core) + half])


def _blocks(s: Session, evs: list[SponsorshipEvent]) -> dict[str, str]:
    b: dict[str, str] = {}
    for e in evs:
        b[f"ev_{e.id}"] = e.snippet or ""
        ctx = context_window(s, e)
        if ctx:
            b[f"ctx_{e.id}"] = ctx
    return b


def _items(evs: list[SponsorshipEvent]) -> dict:
    """Trusted META: the brand name / domain the rules saw for each id (public ad text, not quotable evidence)."""
    return {str(e.id): (e.brand_name or e.domain or None) for e in evs}


def _quote_ok(quote: str, out: client.Outcome, eid: int) -> bool:
    return any(client.verbatim(quote, out.sent.get(k, ""), min_len=8) for k in (f"ev_{eid}", f"ctx_{eid}"))


# ───────────────────────── uncertain -> 8 classes ─────────────────────────
CLASS_TASK = ("Each 'ev_<id>' block is a short passage from podcast show notes or a transcript that our rules could not classify; "
              "'ctx_<id>' is the text around it. For EACH id give the class: declared_sponsorship (an explicit paid ad / 'sponsored "
              "by' / 'thanks to our sponsor'), likely_sponsorship (promo code / offer / vanity URL for a brand, no explicit "
              "statement), affiliate (affiliate links / commissions), podcast_promo (promoting another podcast), self_promotion "
              "(the show's own merch, Patreon, socials, website), network_disclosure (hosting / ad-choices / privacy boilerplate), "
              "organic_mention (a brand mentioned without being an ad), uncertain (cannot tell). A promo code or listener "
              "discount for a brand is likely_sponsorship, not affiliate. Give a reason of at most 10 words and a quote of at most "
              "20 words copied exactly from that id's ev_ or ctx_ block.")


def map_class(raw: str, rule: str) -> str:
    """The cap: the LLM alone never creates declared_sponsorship."""
    if raw in HISTORY:
        return "declared_sponsorship" if raw == "declared_sponsorship" and EXPLICIT_RULE.match(rule or "") else "likely_sponsorship"
    return raw


def classify_uncertain(s: Session, limit: int | None = None, batch: int = 6, force: bool = False) -> dict:
    q = select(SponsorshipEvent).where(SponsorshipEvent.cls == "uncertain", SponsorshipEvent.verification_status == "auto")
    if not force:
        q = q.where(SponsorshipEvent.llm_task.is_(None))
    evs = list(s.scalars(q.order_by(SponsorshipEvent.id)))[: limit or None]
    stats = Counter()
    for i in range(0, len(evs), batch):
        chunk = evs[i:i + batch]
        out = client.run(s, "uncertain_classify", PV["uncertain_classify"], CLASS_TASK, _blocks(s, chunk), ClassOut,
                         meta={"classes": list(EVIDENCE_CLASSES), "items": _items(chunk)}, entity=("sponsor_batch", str(chunk[0].id)), force=force)
        stats[f"call_{out.status}"] += 1
        if not out.ok:
            continue
        got = {v.id: v for v in out.value.items}
        for e in chunk:
            v = got.get(e.id)
            if v is None:
                stats["no_answer"] += 1
                continue
            if not _quote_ok(v.quote, out, e.id):
                stats["quote_not_verbatim"] += 1
                continue
            e.llm_raw_cls, e.llm_cls = v.cls, map_class(v.cls, e.rule)
            e.llm_reason, e.llm_quote = v.reason[:300], v.quote[:300]
            e.llm_task, e.llm_version = "uncertain_classify", _version(PV["uncertain_classify"])
            e.llm_flag = e.llm_cls in HISTORY
            stats[f"to_{e.llm_cls}"] += 1
            if v.cls == "declared_sponsorship" and e.llm_cls != "declared_sponsorship":
                stats["declared_capped_to_likely"] += 1
        s.commit()
    return {"events": len(evs), **dict(stats)}


# ───────────────────────── organic_mention audit ─────────────────────────
AUDIT_TASK = ("Each 'ev_<id>' block is a passage where a brand is mentioned, which our rules called an ORGANIC mention (not an ad); "
              "'ctx_<id>' is the text around it. For EACH id: is it actually a paid sponsorship or ad read (promo code, discount "
              "for listeners, 'sponsored by', 'thanks to X for supporting the show', 'go to x.com/show')? sponsored=true ONLY "
              "with a quote copied exactly from that id's blocks that shows the ad; otherwise sponsored=false.")


def organic_sample(s: Session, n: int, seed: int = 4) -> list[int]:
    """Deterministic, stratified by brand: round-robin over brands (or brand names / domains when no brand id)."""
    rows = s.execute(select(SponsorshipEvent.id, SponsorshipEvent.brand_id, SponsorshipEvent.brand_name, SponsorshipEvent.domain)
                     .where(SponsorshipEvent.cls == "organic_mention", SponsorshipEvent.verification_status == "auto")
                     .order_by(SponsorshipEvent.id)).all()
    by: dict[str, list[int]] = defaultdict(list)
    for eid, bid, bn, dom in rows:
        by[bid or compact(bn or "") or (dom or "") or "_none"].append(eid)
    rng = random.Random(seed)
    keys = sorted(by)
    rng.shuffle(keys)
    for k in keys:
        rng.shuffle(by[k])
    out: list[int] = []
    while len(out) < n and any(by[k] for k in keys):
        for k in keys:
            if by[k] and len(out) < n:
                out.append(by[k].pop())
    return out


def audit_organic(s: Session, n: int | None = None, batch: int = 8, force: bool = False) -> dict:
    n = n or get_settings().llm_organic_sample
    ids = organic_sample(s, n)
    stats = Counter()
    todo = [s.get(SponsorshipEvent, i) for i in ids]
    todo = [e for e in todo if e is not None and (force or e.llm_task != "organic_audit")]
    for i in range(0, len(todo), batch):
        chunk = todo[i:i + batch]
        out = client.run(s, "organic_audit", PV["organic_audit"], AUDIT_TASK, _blocks(s, chunk), AuditOut,
                         meta={"items": _items(chunk)}, entity=("sponsor_batch", str(chunk[0].id)), force=force)
        stats[f"call_{out.status}"] += 1
        if not out.ok:
            continue
        got = {v.id: v for v in out.value.items}
        for e in chunk:
            v = got.get(e.id)
            if v is None:
                stats["no_answer"] += 1
                continue
            e.llm_task, e.llm_version, e.llm_reason = "organic_audit", _version(PV["organic_audit"]), v.reason[:300]
            if v.sponsored and _quote_ok(v.quote, out, e.id):
                e.llm_raw_cls, e.llm_cls, e.llm_quote, e.llm_flag = "likely_sponsorship", "likely_sponsorship", v.quote[:300], True
                stats["promoted"] += 1
            else:
                e.llm_raw_cls, e.llm_cls, e.llm_flag = "organic_mention", None, False
                e.llm_quote = v.quote[:300] if v.quote else None
                stats["sponsored_without_verbatim_quote" if v.sponsored else "confirmed_organic"] += 1
        s.commit()
    return {"sampled": len(ids), "audited_now": len(todo), **dict(stats), "miss_rate": miss_rate(s)}


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (round(max(0.0, c - h), 4), round(min(1.0, c + h), 4))


def miss_rate(s: Session) -> dict:
    """Share of audited organic mentions the LLM says were really sponsorships (with a verbatim quote). Two views:
    per sampled event (brand-stratified sample) and re-weighted to the corpus (each brand's events weighted by how many
    organic events that brand has). It is an LLM estimate, not a human-measured rate."""
    aud = list(s.scalars(select(SponsorshipEvent).where(SponsorshipEvent.llm_task == "organic_audit")))
    if not aud:
        return {"audited": 0}
    k = sum(1 for e in aud if e.llm_cls in HISTORY)
    totals = Counter(r[0] or compact(r[1] or "") or (r[2] or "") or "_none" for r in s.execute(
        select(SponsorshipEvent.brand_id, SponsorshipEvent.brand_name, SponsorshipEvent.domain).where(SponsorshipEvent.cls == "organic_mention")))
    by: dict[str, list[int]] = defaultdict(list)
    for e in aud:
        by[e.brand_id or compact(e.brand_name or "") or (e.domain or "") or "_none"].append(int(e.llm_cls in HISTORY))
    num = sum(totals.get(key, len(v)) * (sum(v) / len(v)) for key, v in by.items())
    den = sum(totals.get(key, len(v)) for key in by for v in [by[key]])
    lo, hi = wilson(k, len(aud))
    return {"audited": len(aud), "promoted": k, "rate_sample": round(k / len(aud), 4), "ci95_sample": [lo, hi],
            "rate_corpus_weighted": round(num / den, 4) if den else None, "organic_total": sum(totals.values()),
            "projected_missed_events": round((num / den) * sum(totals.values())) if den else None}


# ───────────────────────── brand categories ─────────────────────────
CAT_TASK = ("Assign this advertiser brand to at most 2 categories from 'brand_categories' (use the ids). Base it ONLY on the "
            "brand's own ad text in the snip_ blocks (and its name / domain). For each category copy a quote exactly from a "
            "snip_ block that shows what the brand sells. Categories marked sensitive need a quote that explicitly names that "
            "kind of product (e.g. 'sportsbook', 'wine'). If unclear, return an empty list.")


CAT_RANK_MAX = 5
_cat_mat: dict = {}


def category_rank(quote: str, cat_id: str) -> int:
    """1-based rank of `cat_id` among the 28 categories by local-e5 similarity to the quote (a cheap, deterministic check
    that the model's evidence is actually about the category it picked)."""
    import numpy as np
    from ..intel.vectors import embed_queries, get_embedder
    cats = seeds()["categories"]
    ids = list(cats)
    if "m" not in _cat_mat:
        _cat_mat["m"] = np.asarray(embed_queries([cats[c]["description"] for c in ids]), dtype=np.float64)
    v = np.asarray(get_embedder().embed([quote]), dtype=np.float64)[0]
    sims = _cat_mat["m"] @ (v / (np.linalg.norm(v) or 1.0))
    order = [ids[int(j)] for j in np.argsort(-sims)]
    return order.index(cat_id) + 1 if cat_id in order else 99


def _brand_snips(s: Session, b: Brand, n: int = 5) -> list[str]:
    evs = list(s.scalars(select(SponsorshipEvent).where(SponsorshipEvent.brand_id == b.id, history_filter())
                         .order_by(SponsorshipEvent.episode_date.desc(), SponsorshipEvent.id).limit(40)))
    seen, out = set(), []
    for e in evs:
        k = client.norm(e.snippet)[:80]
        if k not in seen and len(e.snippet or "") >= 20:
            seen.add(k)
            out.append(e.snippet)
        if len(out) >= n:
            break
    return out


def categorize_brands(s: Session, limit: int | None = None, force: bool = False) -> dict:
    cats = seeds()["categories"]
    q = select(Brand).where(Brand.merged_into.is_(None), Brand.status == "active", Brand.category_method.notin_(("manual", "override")))
    if not force:
        q = q.where(Brand.llm_categories_version.is_(None))
    brands = list(s.scalars(q.order_by(Brand.n_shows.desc(), Brand.id)))[: limit or None]
    menu = {cid: (c["label"] + (" [sensitive]" if c.get("sensitive") else "")) for cid, c in cats.items()}
    stats = Counter()
    for b in brands:
        snips = _brand_snips(s, b)
        blocks = {"brand_name": b.name, "brand_domain": b.primary_domain or "", **{f"snip_{i}": t for i, t in enumerate(snips)}}
        out = client.run(s, "brand_categories", PV["brand_categories"], CAT_TASK, blocks, CatOut, meta={"brand_categories": menu},
                         entity=("brand", b.id), force=force)
        stats[f"call_{out.status}"] += 1
        if not out.ok:
            continue
        snip_text = {k: v for k, v in out.sent.items() if k.startswith("snip_")}
        picks = []
        for c in out.value.categories:
            if c.id not in cats or any(p["id"] == c.id for p in picks):
                stats["unknown_category"] += 1
                continue
            if not any(client.verbatim(c.quote, t, min_len=8) for t in snip_text.values()):
                stats["quote_not_verbatim"] += 1
                continue
            if len(re.findall(r"[A-Za-z]{3,}", re.sub(r"\S*(?:https?://|www\.|\.com)\S*", " ", c.quote))) < 3:
                stats["quote_not_descriptive"] += 1           # a bare URL / code is not evidence of what the brand sells
                continue
            sens = bool(cats[c.id].get("sensitive"))
            if sens and not re.search(SENSITIVE_LEXICON.get(c.id, r"$^"), c.quote, re.I):
                stats["sensitive_without_explicit_quote"] += 1
                continue
            rank = category_rank(c.quote, c.id)
            if rank > CAT_RANK_MAX:                          # local e5: the quote is not about this category at all
                stats["quote_not_about_category"] += 1
                continue
            picks.append({"id": c.id, "label": cats[c.id]["label"], "score": 1.0, "method": "llm", "tier": "inferred",
                          "confidence": round(min(get_settings().llm_conf_cap, 0.5), 2), "sensitive": sens, "quote": c.quote[:300]})
        b.llm_categories = picks or None
        b.llm_categories_version = _version(PV["brand_categories"])
        stats["with_llm_categories" if picks else "no_supported_category"] += 1
        s.commit()
    return {"brands": len(brands), **dict(stats)}


# ───────────────────────── display names ─────────────────────────
NAME_TASK = ("The brand below was named automatically from its web domain, so the name may be squashed together (e.g. "
             "'Uncommongoods'). Copy the brand's name EXACTLY as it is written in the snip_ blocks (e.g. 'Uncommon Goods'), and "
             "the quote it appears in. If the blocks never write the name, return an empty name.")


def name_candidates(s: Session) -> list[Brand]:
    out = []
    for b in s.scalars(select(Brand).where(Brand.merged_into.is_(None), Brand.status == "active", Brand.identity == "domain")):
        if b.primary_domain and " " not in b.name and compact(b.name) == compact(domain_label(b.primary_domain)) and b.name[1:].islower():
            out.append(b)
    return out


def suggest_names(s: Session, limit: int | None = None, force: bool = False) -> dict:
    cands = [b for b in name_candidates(s) if force or b.name_suggestion_status is None][: limit or None]
    stats = Counter()
    for b in cands:
        evs = list(s.scalars(select(SponsorshipEvent).where(SponsorshipEvent.brand_id == b.id).order_by(SponsorshipEvent.id).limit(200)))
        mention = [e.snippet for e in evs if compact(b.name) in compact(e.snippet or "")]
        blocks = {"brand_domain": b.primary_domain, **{f"snip_{i}": t for i, t in enumerate(mention[:6])}}
        if len(blocks) < 2:
            stats["no_snippet_mentions"] += 1
            continue
        out = client.run(s, "brand_names", PV["brand_names"], NAME_TASK, blocks, NameOut, meta={"domain": b.primary_domain},
                         entity=("brand", b.id), force=force)
        stats[f"call_{out.status}"] += 1
        if not out.ok:
            continue
        sug = (out.value.name or "").strip()
        # same letters as the domain name, but better written: must contain a capital and not be all-lowercase / all-caps-off
        if not sug or sug == b.name or compact(sug) != compact(b.name) or sug == sug.lower() or not sug[0].isupper():
            stats["no_valid_suggestion"] += 1
            continue
        support = sum(1 for e in evs if sug in (e.snippet or ""))       # EXACT (case-sensitive) string in stored snippets
        if support == 0:
            stats["not_in_snippets"] += 1
            continue
        b.name_suggestion, b.name_suggestion_support = sug, support
        b.name_suggestion_status = "auto_applied" if support >= 2 else "pending"
        stats[b.name_suggestion_status] += 1
        s.commit()
    return {"candidates": len(cands), **dict(stats)}
