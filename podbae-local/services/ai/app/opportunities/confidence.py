"""Evidence confidence (separate from Fit; never merged into it).

    coverage      = sum(weight of USED factors) / sum(weight of factors not disabled)
                    (a factor that exists but lacks data for this pair counts against coverage; a factor that is disabled
                     because nobody has that data yet - audience size / geography - does not)
    q(input)      = tier_weight[tier] * (0.5 + 0.5 * field_confidence) * (stale_factor if past its freshness window else 1)
    q(factor)     = mean q(input) over the stored fields behind the factor's value (topic alignment: declared topics when
                    both shows declare a shared topic, inferred topics when the overlap is inferred only, category groups for
                    group-only credit)
    input_quality = sum(w_i * v_i * q_i) / sum(w_i * v_i) over used factors  (contribution-weighted)
    confidence    = coverage ^ coverage_exponent * input_quality                         (0..1, 3 decimals)
    level         = High if >= levels.high, Medium if >= levels.medium, else Low

tier_weight: verified 1.0 > creator_provided 0.9 > estimated 0.7 > inferred 0.5 (config.yaml). Layer 1 field confidences
(e.g. vibe 0.35, topics 0.20-0.55) therefore pull confidence down exactly where Layer 1 said the data is weak."""
from __future__ import annotations

FORMULA = ("confidence = coverage^{exp} x input_quality; coverage = used factor weight / non-disabled factor weight; "
           "input_quality = contribution-weighted mean over used factors of mean(tier_weight x (0.5 + 0.5 x field confidence) x freshness)")


def input_quality(sources: list[dict], cc: dict) -> float:
    tw = cc["tier_weight"]
    if not sources:
        return 0.5
    vals = [float(tw.get(x["tier"], 0.5)) * (0.5 + 0.5 * float(x["confidence"])) * (1.0 if x.get("fresh", True) else float(cc["stale_factor"]))
            for x in sources]
    return sum(vals) / len(vals)


def apply_adjustments(conf: dict, gate_detail: dict, cfg: dict) -> dict:
    """Language uncertain (tags conflict with low detection confidence, or unknown): not a hard reject, but confidence is
    multiplied by gates.language_uncertain_confidence_factor and the reason is recorded."""
    if not gate_detail.get("language_uncertain"):
        return conf
    f = float(cfg["gates"].get("language_uncertain_confidence_factor", 0.8))
    lv = cfg["confidence"]["levels"]
    v = round(conf["value"] * f, 3)
    out = dict(conf, value=v, level="High" if v >= float(lv["high"]) else "Medium" if v >= float(lv["medium"]) else "Low")
    out["adjustments"] = list(conf.get("adjustments") or []) + [{
        "code": "language_uncertain", "factor": f,
        "detail": f"member language {gate_detail.get('member_language')} ({gate_detail.get('member_language_basis')}); "
                  f"candidate language {gate_detail.get('candidate_language')} ({gate_detail.get('candidate_language_basis')})"}]
    return out


def evidence_confidence(rows: list[dict], cfg: dict) -> dict:
    cc = cfg["confidence"]
    active = [r for r in rows if r["status"] != "disabled" and r["weight"] > 0]
    used = [r for r in active if r["status"] == "used"]
    den = sum(r["weight"] for r in active)
    coverage = sum(r["weight"] for r in used) / den if den else 0.0
    per = {r["name"]: round(input_quality(r["sources"], cc), 4) for r in used}
    # weight each factor's input quality by how much it actually CONTRIBUTED to the Fit (w_i x v_i): a Fit driven by verified
    # facts earns more confidence than one driven by inferred vibe. Falls back to nominal weights if nothing contributed.
    contrib = {r["name"]: r["weight"] * float(r["value"] or 0.0) for r in used}
    tot = sum(contrib.values())
    wts = contrib if tot > 0 else {r["name"]: r["weight"] for r in used}
    den_q = sum(wts.values())
    quality = sum(wts[n] * per[n] for n in per) / den_q if den_q else 0.0
    value = round((coverage ** float(cc["coverage_exponent"])) * quality, 3)
    lv = cc["levels"]
    level = "High" if value >= float(lv["high"]) else "Medium" if value >= float(lv["medium"]) else "Low"
    return {"value": value, "level": level, "coverage": round(coverage, 4), "input_quality": round(quality, 4),
            "per_factor_quality": per, "missing_factors": [r["name"] for r in rows if r["status"] == "missing"],
            "disabled_factors": [r["name"] for r in rows if r["status"] == "disabled"],
            "formula": FORMULA.format(exp=cc["coverage_exponent"])}
