"""Compatibility factors ("Fit"). Every factor is a pure function of two shows' stored features + the config and returns:

  status  'used'     the factor had data on both sides; value in [0,1]
          'missing'  the factor exists but this pair lacks the data (excluded, weights renormalised, confidence lowered)
          'disabled' the factor needs data nobody has yet (audience size / geography): it switches on automatically
                     when BOTH shows have creator-provided or estimated data
  inputs  the exact numbers / ids used (stored in breakdown_json; explanations may only quote these)
  sources which stored fields were read, with their tier, confidence and freshness

Nothing is imputed. "unknown" conversational style is treated as missing, never as a category."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable

from ..intel.linalg import dot
from ..intel.understanding.schemas import VIBE_TERMS
from ..intel.understanding.signals import taxonomy
from .features import Corpus, ShowFeatures, days_between, finite, parse_iso


@dataclass
class FactorResult:
    name: str
    status: str
    value: float | None = None
    inputs: dict[str, Any] = field(default_factory=dict)
    sources: list[dict] = field(default_factory=list)
    reason: str | None = None

    def as_dict(self, weight: float) -> dict:
        return {"name": self.name, "status": self.status, "value": None if self.value is None else round(self.value, 4),
                "weight": weight, "inputs": self.inputs, "sources": self.sources, "reason": self.reason}


def clip01(x: float) -> float:
    return 0.0 if x < 0 else 1.0 if x > 1 else x


def ratio_closeness(a: float, b: float, ratio_zero: float) -> float:
    """1 when equal, 0 when one is ratio_zero times the other (log scale)."""
    if a <= 0 or b <= 0:
        return 0.0
    return clip01(1.0 - abs(math.log(a / b)) / math.log(ratio_zero))


def _missing(name: str, reason: str, sources: list[dict] | None = None) -> FactorResult:
    return FactorResult(name, "missing", None, {}, sources or [], reason)


# ───────────────────────── topic_alignment ─────────────────────────
def topic_vector(sf: ShowFeatures, cfg: dict) -> dict[str, float]:
    vec: dict[str, float] = {}
    for t in sf.val("declared_topics") or []:
        vec[t] = max(vec.get(t, 0.0), float(cfg["declared_weight"]))
    for t in sf.val("topics") or []:
        tid = t.get("id") if isinstance(t, dict) else None
        if tid:
            vec[tid] = max(vec.get(tid, 0.0), float(t.get("weight", 0.0)) * float(cfg["inferred_scale"]))
    return vec


def topic_alignment(m: ShowFeatures, c: ShowFeatures, corpus: Corpus, cfg: dict) -> FactorResult:
    name = "topic_alignment"
    srcs = [fv.src(f, side) for side, sf in (("member", m), ("candidate", c)) for f in ("declared_topics", "topics", "category_group")
            if (fv := sf.get(f)) is not None]
    vm, vc = topic_vector(m, cfg), topic_vector(c, cfg)
    gm, gc = set(m.val("category_group") or []), set(c.val("category_group") or [])
    if (not vm and not gm) or (not vc and not gc):
        return _missing(name, "no topics, declared topics or category group on one side", srcs)
    shared = sorted(set(vm) & set(vc))
    cos = 0.0
    if vm and vc:
        num = sum(vm[t] * vc[t] for t in shared)
        den = math.sqrt(sum(x * x for x in vm.values())) * math.sqrt(sum(x * x for x in vc.values()))
        cos = num / den if den else 0.0
    gj = len(gm & gc) / len(gm | gc) if (gm | gc) else 0.0
    group_part = float(cfg["group_credit"]) * gj
    value = max(cos, group_part)
    tax = taxonomy()
    dm, dc = set(m.val("declared_topics") or []), set(c.val("declared_topics") or [])
    shared_named = [{"id": t, "name": tax.get(t, {}).get("label", t), "member_weight": round(vm[t], 2), "candidate_weight": round(vc[t], 2),
                     "declared_by_both": t in dm and t in dc}
                    for t in sorted(shared, key=lambda t: (-(vm[t] * vc[t]), t))]
    basis = "topics" if cos >= group_part else "category_group"
    # evidence behind the VALUE: declared-by-both overlap is publisher-stated (verified); an inferred-only overlap is inferred;
    # group-only credit rests on the verified category groups
    if basis == "category_group":
        ev_fields = ["category_group"]
    elif any(x["declared_by_both"] for x in shared_named):
        ev_fields = ["declared_topics"]
    else:
        ev_fields = ["topics"]
    ev = [x for x in srcs if x["field"] in ev_fields]
    return FactorResult(name, "used", clip01(value), {
        "shared_topics": shared_named, "topic_cosine": round(cos, 4), "shared_groups": sorted(gm & gc), "group_jaccard": round(gj, 4),
        "basis": basis, "evidence_fields": ev_fields}, ev or srcs)


# ───────────────────────── content_similarity ─────────────────────────
def content_transform(z: float, cfg: dict) -> float:
    a, b, c_, d, floor = (float(cfg[k]) for k in ("ramp_start_z", "peak_start_z", "peak_end_z", "clone_z", "clone_floor"))
    if z <= a:
        return 0.0
    if z < b:
        return (z - a) / (b - a)
    if z <= c_:
        return 1.0
    if z < d:
        return 1.0 - (1.0 - floor) * (z - c_) / (d - c_)
    return floor


def content_similarity(m: ShowFeatures, c: ShowFeatures, corpus: Corpus, cfg: dict, emb_conf: float = 0.8) -> FactorResult:
    name = "content_similarity"
    srcs = [{"field": "content_embedding", "side": side, "tier": "estimated", "confidence": emb_conf, "fresh": True, "method": "model"}
            for side, sf in (("member", m), ("candidate", c)) if sf.content_vec is not None]
    cos = corpus.cos(m.show_id, c.show_id)
    if cos is None:
        return _missing(name, "no content embedding on one side", srcs)
    z = corpus.z(cos)
    if z is None:
        return _missing(name, "corpus too small for content statistics", srcs)
    v = content_transform(z, cfg)
    band = "below" if z < float(cfg["peak_start_z"]) else "peak" if z <= float(cfg["peak_end_z"]) else "near_clone"
    return FactorResult(name, "used", v, {"cosine": round(cos, 4), "z": round(z, 2), "band": band, "pair_percentile": corpus.percentile(cos),
                                           "corpus_mean": round(corpus.pair_mean or 0, 4), "corpus_std": round(corpus.pair_std or 0, 4)}, srcs)


# ───────────────────────── vibe_compatibility ─────────────────────────
def _top_vibes(sf: ShowFeatures, n: int = 3) -> list[str]:
    v = sf.val("vibe") or {}
    return [k for k, x in sorted(v.items(), key=lambda kv: (-kv[1], kv[0]))[:n] if isinstance(x, (int, float))]


def vibe_compatibility(m: ShowFeatures, c: ShowFeatures, corpus: Corpus, cfg: dict) -> FactorResult:
    name = "vibe_compatibility"
    srcs = [fv.src(f, side) for side, sf in (("member", m), ("candidate", c)) for f in ("style_features", "vibe", "conversational_style")
            if (fv := sf.get(f)) is not None]
    sm, sc = m.val("conversational_style"), c.val("conversational_style")
    both_known = sm not in (None, "unknown") and sc not in (None, "unknown")
    vm, vc = corpus.style_vec(m.show_id, both_known), corpus.style_vec(c.show_id, both_known)
    if vm is None or vc is None:
        return _missing(name, "no numeric style features on one side", srcs)
    cos = dot(vm, vc)
    lo, hi = float(cfg["cos_floor"]), float(cfg["cos_ceiling"])
    shared = sorted(set(_top_vibes(m)) & set(_top_vibes(c)), key=lambda x: VIBE_TERMS.index(x) if x in VIBE_TERMS else 99)
    return FactorResult(name, "used", clip01((cos - lo) / (hi - lo)), {
        "centred_cosine": round(cos, 4), "shared_top_vibes": shared,
        "style_dims": "included" if both_known else "excluded (conversational style unknown on at least one side)",
        "member_style": sm, "candidate_style": sc}, srcs)


# ───────────────────────── format_compatibility ─────────────────────────
def format_compatibility(m: ShowFeatures, c: ShowFeatures, corpus: Corpus, cfg: dict) -> FactorResult:
    name = "format_compatibility"
    srcs = [fv.src(f, side) for side, sf in (("member", m), ("candidate", c)) for f in ("avg_episode_minutes", "cadence_days")
            if (fv := sf.get(f)) is not None]
    parts: list[tuple[float, float]] = []
    inputs: dict[str, Any] = {}
    lm, lc = finite(m.val("avg_episode_minutes")), finite(c.val("avg_episode_minutes"))
    if lm and lc and lm > 0 and lc > 0:
        s_ = ratio_closeness(lm, lc, float(cfg["length_ratio_zero"]))
        parts.append((float(cfg["length_share"]), s_))
        inputs.update(member_minutes=round(lm), candidate_minutes=round(lc), length_score=round(s_, 4))
    cm, cc = finite(m.val("cadence_days")), finite(c.val("cadence_days"))
    if cm is not None and cc is not None and cm >= 0 and cc >= 0:
        s_ = ratio_closeness(cm + 1, cc + 1, float(cfg["cadence_ratio_zero"]))
        parts.append((float(cfg["cadence_share"]), s_))
        inputs.update(member_cadence_days=round(cm, 1), candidate_cadence_days=round(cc, 1), cadence_score=round(s_, 4))
    if not parts:
        return _missing(name, "no episode length or cadence on one side", srcs)
    w = sum(p[0] for p in parts)
    inputs["parts_used"] = [k for k in ("length_score", "cadence_score") if k in inputs]
    return FactorResult(name, "used", sum(p[0] * p[1] for p in parts) / w, inputs, srcs)


# ───────────────────────── activity_match ─────────────────────────
def activity_match(m: ShowFeatures, c: ShowFeatures, corpus: Corpus, cfg: dict) -> FactorResult:
    name = "activity_match"
    srcs = [fv.src(f, side) for side, sf in (("member", m), ("candidate", c)) for f in ("activity_status", "last_published")
            if (fv := sf.get(f)) is not None]
    st = cfg["status_score"]
    am, ac = m.val("activity_status") or m.activity, c.val("activity_status") or c.activity
    lp = parse_iso(c.val("last_published"))
    if am not in st or ac not in st or lp is None:
        return _missing(name, "activity status or last-published date missing", srcs)
    days = max(0.0, days_between(corpus.as_of, lp))
    recency = 0.5 ** (days / float(cfg["recency_half_life_days"]))
    status_part = (float(st[am]) + float(st[ac])) / 2
    return FactorResult(name, "used", clip01(0.5 * status_part + 0.5 * recency), {
        "member_status": am, "candidate_status": ac, "candidate_days_since_last_episode": int(days),
        "recency_score": round(recency, 4)}, srcs)


# ───────────────────────── collaboration_openness ─────────────────────────
def collaboration_openness(m: ShowFeatures, c: ShowFeatures, corpus: Corpus, cfg: dict) -> FactorResult:
    name = "collaboration_openness"
    srcs = [fv.src(f, "candidate") for f in ("guest_friendliness", "creator.collaboration_openness") if (fv := c.get(f)) is not None]
    g = finite(c.val("guest_friendliness"))
    op = c.val("creator.collaboration_openness")
    scores = cfg["openness_score"]
    inputs: dict[str, Any] = {}
    if g is not None:
        inputs["guest_share"] = round(g, 2)
        inputs["guest_score"] = round(clip01(g / float(cfg["guest_share_full"])), 4)
    if op in scores:
        inputs["stated_openness"] = op
    if g is None and op not in scores:
        return _missing(name, "no guest-friendliness and no stated openness", srcs)
    if op in scores and g is not None:
        sh = float(cfg["openness_share"])
        v = sh * float(scores[op]) + (1 - sh) * inputs["guest_score"]
    elif op in scores:
        v = float(scores[op])
    else:
        v = inputs["guest_score"]
        inputs["note"] = "creator has not stated collaboration openness"
    return FactorResult(name, "used", clip01(v), inputs, srcs)


# ───────────────────────── audience factors (defined, auto-disabled) ─────────────────────────
def _usable_audience(fv) -> bool:
    return fv is not None and fv.tier in ("creator_provided", "estimated", "verified")


def audience_size_parity(m: ShowFeatures, c: ShowFeatures, corpus: Corpus, cfg: dict) -> FactorResult:
    name = "audience_size_parity"
    fm, fc = m.get("audience.totals"), c.get("audience.totals")
    srcs = [fv.src("audience.totals", side) for side, fv in (("member", fm), ("candidate", fc)) if fv is not None]
    if not (_usable_audience(fm) and _usable_audience(fc)):
        return FactorResult(name, "disabled", None, {}, srcs, "no audience size data for both shows (needs creator analytics)")
    dm, dc = (fm.value or {}).get("data") or {}, (fc.value or {}).get("data") or {}
    metric = next((k for k in cfg["metrics"] if finite(dm.get(k)) and finite(dc.get(k))), None)
    if metric is None:
        return FactorResult(name, "disabled", None, {}, srcs, "no comparable audience metric in both uploads")
    a, b = float(dm[metric]), float(dc[metric])
    return FactorResult(name, "used", ratio_closeness(a, b, float(cfg["ratio_zero"])),
                        {"metric": metric, "member_value": a, "candidate_value": b}, srcs)


def geo_overlap(m: ShowFeatures, c: ShowFeatures, corpus: Corpus, cfg: dict) -> FactorResult:
    name = "geo_overlap"
    fm, fc = m.get("audience.top_countries"), c.get("audience.top_countries")
    srcs = [fv.src("audience.top_countries", side) for side, fv in (("member", fm), ("candidate", fc)) if fv is not None]
    if not (_usable_audience(fm) and _usable_audience(fc)):
        return FactorResult(name, "disabled", None, {}, srcs, "no audience geography for both shows (needs creator analytics)")

    def pct(fv) -> dict[str, float]:
        rows = (fv.value or {}).get("data") or []
        out = {str(r.get("label", "")).strip().lower(): float(r["percent"]) for r in rows if finite(r.get("percent")) is not None}
        if not out:   # counts only: convert to shares
            cnt = {str(r.get("label", "")).strip().lower(): float(r["count"]) for r in rows if finite(r.get("count"))}
            tot = sum(cnt.values())
            out = {k: 100 * v / tot for k, v in cnt.items()} if tot else {}
        return out
    pm, pc = pct(fm), pct(fc)
    if not pm or not pc:
        return FactorResult(name, "disabled", None, {}, srcs, "audience geography has no usable percentages")
    shared = sorted(set(pm) & set(pc))
    ov = sum(min(pm[k], pc[k]) for k in shared) / 100.0
    return FactorResult(name, "used", clip01(ov), {"shared_countries": shared[:10], "overlap_share": round(ov, 4)}, srcs)


FACTOR_FUNCS: dict[str, Callable[..., FactorResult]] = {
    "topic_alignment": topic_alignment, "content_similarity": content_similarity, "vibe_compatibility": vibe_compatibility,
    "format_compatibility": format_compatibility, "activity_match": activity_match,
    "collaboration_openness": collaboration_openness, "audience_size_parity": audience_size_parity, "geo_overlap": geo_overlap,
}


def combine_rows(results: list[tuple[FactorResult, float]]) -> tuple[float, list[dict]]:
    """THE Fit formula, shared by every opportunity kind (partners, sponsors):
    Fit 0-100 = 100 * sum(w_i * v_i) / sum(w_i) over USED factors only (missing/disabled excluded, weights renormalised)."""
    rows: list[dict] = []
    num = den = 0.0
    for r, w in results:
        d = r.as_dict(w)
        if r.status == "used" and w > 0:
            num += w * float(r.value)
            den += w
        rows.append(d)
    fit = round(100.0 * num / den, 2) if den else 0.0
    for d in rows:
        d["effective_weight"] = round(d["weight"] / den, 4) if d["status"] == "used" and den else 0.0
        d["contribution"] = round(100.0 * d["effective_weight"] * d["value"], 2) if d["status"] == "used" else 0.0
    return fit, rows


def score_pair(m: ShowFeatures, c: ShowFeatures, corpus: Corpus, cfg: dict) -> tuple[float, list[dict]]:
    """Podcast-partner Fit: the partner factors, combined by combine_rows()."""
    fcfg = cfg["factors"]
    results = []
    for name, fn in FACTOR_FUNCS.items():
        fc = fcfg[name]
        r = fn(m, c, corpus, fc, float(cfg["confidence"]["embedding_confidence"])) if name == "content_similarity" else fn(m, c, corpus, fc)
        results.append((r, float(fc["weight"])))
    return combine_rows(results)
