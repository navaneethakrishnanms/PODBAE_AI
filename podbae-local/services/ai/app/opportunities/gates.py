"""Hard eligibility gates, applied BEFORE scoring. A candidate that fails any gate is never scored, so a blocked category
cannot be rescued by a high Fit. Every rejection carries a stable reason code (stored in opportunity_rejections)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from ..intel.understanding.signals import taxonomy
from .features import ShowFeatures, days_between

REASONS = ("self", "same_owner", "opted_out", "closed_to_collaboration", "inactive", "slowing", "insufficient_data",
           "language_incompatible", "blocked_category", "blocked_brand_safety", "dismissed_recently", "contacted_recently",
           "already_partnered")
COOLDOWN_REASON = {"dismiss": "dismissed_recently", "contact": "contacted_recently", "reply": "contacted_recently",
                   "meeting": "contacted_recently", "partnership": "already_partnered"}


@dataclass
class GateResult:
    passed: bool
    reason: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)


def _primary(lang: Any) -> str | None:
    if not isinstance(lang, str) or not lang.strip():
        return None
    return lang.strip().lower().replace("_", "-").split("-")[0]


def effective_language(sf: ShowFeatures, min_detected_conf: float, min_chars: int = 0) -> tuple[str | None, str, bool]:
    """Base language (en-US / en-GB / en -> en) + basis + whether it is CONFIDENTLY known.
      declared and detected agree           -> declared, certain
      they disagree, detection conf >= min  -> detected, certain
      they disagree, detection conf <  min  -> declared, UNCERTAIN (never a hard reject; confidence is lowered instead)
      declared only                         -> declared, certain (publisher-stated, verified)
      detected only                         -> detected, certain only if conf >= min
      neither                               -> None, uncertain"""
    declared = next((r for r in sf.language_rows if r.tier == "verified"), None)
    detected = next((r for r in sorted(sf.language_rows, key=lambda r: -r.confidence) if r.tier != "verified"), None)
    d, t = _primary(declared.value) if declared else None, _primary(detected.value) if detected else None
    desc = sf.val("description")
    sample = (sf.text_chars or 0) + (len(desc) if isinstance(desc, str) else 0)
    long_enough = sample >= min_chars
    if d and t and d != t:
        if detected.confidence >= min_detected_conf and not long_enough:
            return d, (f"uncertain: declared '{d}' but detected '{t}' (confidence {detected.confidence:.2f}) on only {sample} characters "
                       f"of text (< {min_chars})"), False
        if detected.confidence >= min_detected_conf:
            return t, f"detected '{t}' (conflicts with declared '{d}'; detection confidence {detected.confidence:.2f} >= {min_detected_conf})", True
        return d, f"uncertain: declared '{d}' but detected '{t}' with confidence {detected.confidence:.2f} < {min_detected_conf}", False
    if d:
        return d, "declared", True
    if t:
        ok = detected.confidence >= min_detected_conf
        return t, f"detected only (confidence {detected.confidence:.2f})" + ("" if ok else ", uncertain"), ok
    return None, "unknown", False


def _norm(x: Any) -> str:
    return str(x).strip().lower().replace("_", " ").replace("&", "and")


def candidate_labels(sf: ShowFeatures) -> set[str]:
    """Every category / topic name or id a creator might block, normalised."""
    tax = taxonomy()
    out: set[str] = set()
    for f in ("category_group", "categories", "declared_topics"):
        for x in sf.val(f) or []:
            out.add(_norm(x))
            if x in tax:
                out.add(_norm(tax[x]["label"]))
    for t in sf.val("topics") or []:
        if isinstance(t, dict):
            for k in ("id", "name", "group"):
                if t.get(k):
                    out.add(_norm(t[k]))
    return out


def check(m: ShowFeatures, c: ShowFeatures, cfg: dict, history: dict[str, list[tuple[str, datetime]]], as_of: datetime) -> GateResult:
    g = cfg["gates"]
    if c.show_id == m.show_id:
        return GateResult(False, "self")
    om, oc = m.val("owner_email_hash"), c.val("owner_email_hash")
    if om and oc and om == oc:                       # internal identity signal only; never output
        return GateResult(False, "same_owner")
    if c.val("creator.opportunity_opt_out") is True:
        return GateResult(False, "opted_out")
    if g.get("exclude_closed_to_collaboration", True) and c.val("creator.collaboration_openness") == "closed":
        return GateResult(False, "closed_to_collaboration")
    act = c.val("activity_status") or c.activity
    if g.get("exclude_inactive", True) and act == "inactive":
        return GateResult(False, "inactive", {"activity": act})
    if g.get("exclude_slowing", False) and act == "slowing":
        return GateResult(False, "slowing", {"activity": act})
    if c.content_vec is None:
        return GateResult(False, "insufficient_data", {"missing": "content embedding"})
    mc, mch = float(g["language_detected_min_confidence"]), int(g.get("language_detected_min_chars", 0))
    lm, bm, okm = effective_language(m, mc, mch)
    lc, bc, okc = effective_language(c, mc, mch)
    # hard reject ONLY when both languages are confidently known and different
    if lm and lc and lm != lc and okm and okc:
        return GateResult(False, "language_incompatible", {"member": lm, "member_basis": bm, "candidate": lc, "candidate_basis": bc})
    lang_uncertain = (lm != lc) or not (okm and okc)
    blocked = {_norm(x) for x in (m.val("creator.blocked_categories") or [])}
    if blocked:
        hit = sorted(blocked & candidate_labels(c))
        if hit:
            return GateResult(False, "blocked_category", {"blocked": hit})
    bflags = {_norm(x) for x in (m.val("creator.blocked_brand_safety_flags") or [])}
    if bflags:
        hit = sorted(bflags & {_norm(x) for x in (c.val("brand_safety_flags") or [])})
        if hit:
            return GateResult(False, "blocked_brand_safety", {"flags": hit})
    cool = g.get("cooldown_days") or {}
    for etype, ts in sorted(history.get(c.show_id, []), key=lambda x: x[1], reverse=True):
        days = cool.get(etype)
        if days is not None and days_between(as_of, ts) < float(days):
            return GateResult(False, COOLDOWN_REASON.get(etype, f"cooldown_{etype}"),
                              {"event": etype, "days_ago": round(days_between(as_of, ts), 1), "cooldown_days": days})
    return GateResult(True, None, {"member_language": lm, "member_language_basis": bm, "candidate_language": lc,
                                   "candidate_language_basis": bc, "language_uncertain": bool(lang_uncertain)})
