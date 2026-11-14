"""Phase 4 measurements: per-task LLM calls, tokens, latency, cache hit rate, rate-limit pauses (from llm_calls), and the
rules-vs-LLM comparison for the label set (no human labels needed; human verdicts are the ground truth when they exist)."""
from __future__ import annotations

from collections import Counter, defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..intel.config import get_settings
from ..intel.models import LabelItem, Show
from ..intel.trust.provenance import live_rows
from . import llm_active
from .models import LlmCall


def _p(vals: list[int], q: float) -> int | None:
    if not vals:
        return None
    v = sorted(vals)
    return v[min(len(v) - 1, int(q * len(v)))]


def call_metrics(s: Session) -> dict:
    rows = list(s.scalars(select(LlmCall)))
    by: dict[str, list[LlmCall]] = defaultdict(list)
    for r in rows:
        by[r.task].append(r)
    out = {}
    for task, rs in sorted(by.items()):
        real = [r for r in rs if not r.cache_hit and r.status not in ("privacy",)]
        ok = [r for r in real if r.status == "ok"]
        hits = sum(1 for r in rs if r.cache_hit)
        lat = [r.latency_ms for r in real if r.latency_ms]
        out[task] = {"provider_calls": len(real), "ok": len(ok), "cache_hits": hits,
                     "cache_hit_rate": round(hits / (hits + len(real)), 3) if (hits + len(real)) else None,
                     "status": dict(Counter(r.status for r in rs)), "tokens_in": sum(r.tokens_in for r in real),
                     "tokens_out": sum(r.tokens_out for r in real), "latency_ms_avg": round(sum(lat) / len(lat)) if lat else None,
                     "latency_ms_p95": _p(lat, 0.95), "rate_limit_pauses": sum(1 for r in rs if r.status == "rate_limited"),
                     "retries": sum(1 for r in real if r.attempt > 1), "models": sorted({r.model for r in rs}),
                     "providers": sorted({r.provider for r in rs})}
    tot_calls = sum(v["provider_calls"] for v in out.values())
    tot_hits = sum(v["cache_hits"] for v in out.values())
    return {"by_task": out, "total": {"provider_calls": tot_calls, "cache_hits": tot_hits,
                                      "tokens_in": sum(v["tokens_in"] for v in out.values()),
                                      "tokens_out": sum(v["tokens_out"] for v in out.values()),
                                      "cost_usd": 0.0, "rate_limit_pauses": sum(v["rate_limit_pauses"] for v in out.values())}}


def status() -> dict:
    cfg = get_settings()
    return {"llm_active": llm_active(), "provider": cfg.llm_provider, "refine_enabled": cfg.llm_refine_enabled,
            "phrasing_enabled": cfg.llm_phrasing_enabled, "model": cfg.ollama_model if cfg.llm_provider == "ollama" else None,
            "base_url": cfg.ollama_base_url if cfg.llm_provider == "ollama" else None, "confidence_cap": cfg.llm_conf_cap,
            "rate_per_min": cfg.llm_rate_per_min, "phrase_daily_calls": cfg.llm_phrase_daily_calls,
            "kill_switches": "LLM_PROVIDER=mock or INTEL_LLM_REFINE=false -> exact Phase 3 behaviour"}


def _pair(s: Session, sid: str, field: str):
    """(rule value, llm value) for one field; llm only from live method='llm' rows."""
    rows = live_rows(s, "show", sid, field, include_llm=True)
    rule = sorted([r for r in rows if r.method != "llm"], key=lambda r: -r.fetched_at.timestamp())
    llm = sorted([r for r in rows if r.method == "llm"], key=lambda r: -r.fetched_at.timestamp())
    return (rule[0].value_json if rule else None), (llm[0].value_json if llm else None)


def show_comparison(s: Session, sid: str) -> dict:
    """Rule vs AI, side by side, for the label UI. Only fields where a refiner ran have an AI value."""
    out = {}
    rs, ls = _pair(s, sid, "conversational_style")
    out["style"] = {"rule": rs, "ai": ls, "disagree": ls is not None and ls != rs}
    rt, lt = _pair(s, sid, "topics")
    rids = sorted(t["id"] for t in rt or [])
    lids = sorted(t["id"] for t in lt or []) if lt is not None else None
    out["topics"] = {"rule": rids, "ai": lids, "ai_added": sorted(set(lids or []) - set(rids)), "disagree": lids is not None and lids != rids}
    rg, lg = _pair(s, sid, "guests_present")
    rgv = rg.get("value") if isinstance(rg, dict) else None
    lgv = lg.get("value") if isinstance(lg, dict) else None
    out["guest"] = {"rule": rgv, "rule_share": rg.get("share") if isinstance(rg, dict) else None, "ai": lgv,
                    "ai_share": lg.get("share") if isinstance(lg, dict) else None, "disagree": lg is not None and lgv != rgv}
    out["any_disagree"] = any(v.get("disagree") for v in out.values() if isinstance(v, dict))
    return out


def label_disagreements(s: Session) -> dict:
    """For the human label set: rule vs AI per show; disagreements first. Empty when the LLM is off."""
    if not llm_active():
        return {"items": [], "llm_active": False}
    items = []
    for it in s.scalars(select(LabelItem).order_by(LabelItem.position)):
        sh = s.get(Show, it.show_id)
        cmp = show_comparison(s, it.show_id)
        items.append({"show_id": it.show_id, "title": sh.title if sh else it.show_id, "position": it.position, **cmp})
    items.sort(key=lambda x: (not x["any_disagree"], x["position"]))
    return {"items": items, "llm_active": True, "disagreements": sum(1 for x in items if x["any_disagree"])}


def corpus_comparison(s: Session) -> dict:
    """Rules vs LLM over the whole store: coverage gained and agreement (no labels needed)."""
    shows = [x for x in s.scalars(select(Show.id).where(Show.merged_into.is_(None)))]
    n = len(shows)
    st = Counter()
    for sid in shows:
        c = show_comparison(s, sid)
        if c["style"]["rule"] == "unknown":
            st["style_rule_unknown"] += 1
            st["style_unknown_after" if c["style"]["ai"] in (None, "unknown") else "style_filled_by_ai"] += 1
        if c["style"]["ai"] is not None:
            st["style_ai"] += 1
            st["style_ai_changed_known_rule"] += int(c["style"]["rule"] not in ("unknown", None) and c["style"]["ai"] != c["style"]["rule"])
        if c["topics"]["ai"] is not None:
            st["topics_ai_shows"] += 1
            st["topics_added"] += len(c["topics"]["ai_added"])
        if c["guest"]["ai"] is not None:
            st["guest_ai_shows"] += 1
            st["guest_agree"] += int(c["guest"]["ai"] == c["guest"]["rule"])
            if c["guest"]["ai_share"] is not None and c["guest"]["rule_share"] is not None:
                st["guest_share_absdiff_x100"] += round(100 * abs(c["guest"]["ai_share"] - c["guest"]["rule_share"]))
    unk = st["style_rule_unknown"]
    return {"shows": n,
            "style": {"rule_unknown": unk, "rule_unknown_share": round(unk / n, 3) if n else None,
                      "after_ai_unknown": unk - st["style_filled_by_ai"],
                      "after_ai_unknown_share": round((unk - st["style_filled_by_ai"]) / n, 3) if n else None,
                      "filled_by_ai": st["style_filled_by_ai"], "ai_values": st["style_ai"],
                      "ai_changed_a_known_low_conf_rule_value": st["style_ai_changed_known_rule"]},
            "topics": {"shows_with_ai_additions": st["topics_ai_shows"], "topics_added": st["topics_added"]},
            "guests": {"shows_verified_by_ai": st["guest_ai_shows"],
                       "agreement_guest_friendly": round(st["guest_agree"] / st["guest_ai_shows"], 3) if st["guest_ai_shows"] else None,
                       "mean_abs_share_diff": round(st["guest_share_absdiff_x100"] / 100 / st["guest_ai_shows"], 3) if st["guest_ai_shows"] else None}}
