"""Phase 4 evaluation (EVAL_LLM.md numbers). Read-only. Usage: npm run intel:evalllm  -> services/ai/eval/llm.json

With human labels / reviews: rules-vs-LLM accuracy per field / class (humans are the ground truth; the AI never labels).
Without them: rules-vs-LLM agreement, coverage gained, and 20 random examples per refiner for a human to read."""
from __future__ import annotations

import json
import os
import random
import re
import sys
from collections import Counter
from pathlib import Path

import torch  # noqa: F401  (safe native import order)
import sentence_transformers  # noqa: F401

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.envfile import load_env  # noqa: E402

load_env()
from sqlalchemy import func, select  # noqa: E402

from app.intel import startup  # noqa: E402
from app.intel.db import session_scope  # noqa: E402
from app.intel.models import AuditLog, EvalLabel, Evidence, Provenance, Show, Source  # noqa: E402
from app.llm_refine import llm_active  # noqa: E402
from app.llm_refine import metrics as m  # noqa: E402
from app.llm_refine.models import LlmCache  # noqa: E402
from app.llm_refine.sponsors import miss_rate  # noqa: E402
from app.sponsors.models import Brand, SponsorReview, SponsorshipEvent  # noqa: E402

EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
OUT = Path(__file__).resolve().parents[1] / "eval" / "llm.json"
RNG = random.Random(20261114)


def _sample(xs: list, n: int = 20) -> list:
    xs = list(xs)
    RNG.shuffle(xs)
    return xs[:n]


def layer1_examples(s) -> dict:
    llm_src = {x.id for x in s.scalars(select(Source).where(Source.kind == "llm"))}
    out: dict[str, list] = {}
    for field, key in (("conversational_style", "style"), ("guests_present", "guests"), ("topics", "topics")):
        rows = list(s.scalars(select(Provenance).where(Provenance.field == field, Provenance.method == "llm",
                                                       Provenance.superseded_by.is_(None))))
        ex = []
        for p in _sample(rows):
            sh = s.get(Show, p.entity_id)
            kind = "guest_friendliness" if field == "guests_present" else field
            quotes = [e.snippet for e in s.scalars(select(Evidence).where(Evidence.entity_id == p.entity_id, Evidence.kind == kind,
                                                                          Evidence.source_id.in_(llm_src))).all()][:3]
            val = p.value_json
            if field == "topics":
                val = [t["id"] for t in val if "llm" in (t.get("basis") or [])]
            elif field == "guests_present":
                val = {"share": val.get("share"), "rule_share": val.get("rule_share")}
            ex.append({"show": sh.title if sh else p.entity_id, "show_id": p.entity_id, "ai": val, "rule": p.source_ref,
                       "confidence": p.confidence, "evidence": quotes})
        out[key] = ex
    return out


def human_accuracy(s) -> dict:
    """Rules vs LLM against human labels (label set). Unmeasured until humans label."""
    labels = list(s.scalars(select(EvalLabel).where(EvalLabel.labeler != "claude-draft")))
    if not labels:
        return {"labels": 0, "note": "No human labels yet: rules-vs-LLM ACCURACY is unmeasured (agreement below is not accuracy)."}
    res = Counter()
    for lb in labels:
        c = m.show_comparison(s, lb.show_id)
        if lb.style:
            res["style_n"] += 1
            res["style_rule_ok"] += int(c["style"]["rule"] == lb.style)
            res["style_ai_ok"] += int((c["style"]["ai"] or c["style"]["rule"]) == lb.style)
        if lb.guest_friendly is not None:
            res["guest_n"] += 1
            res["guest_rule_ok"] += int(c["guest"]["rule"] == lb.guest_friendly)
            res["guest_ai_ok"] += int((c["guest"]["ai"] if c["guest"]["ai"] is not None else c["guest"]["rule"]) == lb.guest_friendly)
    f = lambda a, b: round(res[a] / res[b], 3) if res[b] else None  # noqa: E731
    return {"labels": len(labels), "style": {"n": res["style_n"], "rules": f("style_rule_ok", "style_n"), "rules+llm": f("style_ai_ok", "style_n")},
            "guest_friendly": {"n": res["guest_n"], "rules": f("guest_rule_ok", "guest_n"), "rules+llm": f("guest_ai_ok", "guest_n")}}


def sponsors(s) -> dict:
    unc = list(s.scalars(select(SponsorshipEvent).where(SponsorshipEvent.llm_task == "uncertain_classify")))
    total_unc = s.scalar(select(func.count()).select_from(SponsorshipEvent).where(SponsorshipEvent.cls == "uncertain")) or 0
    reviews = {r.event_id: r for r in s.scalars(select(SponsorReview))}
    rv_n = rv_rule = rv_ai = 0
    for e in s.scalars(select(SponsorshipEvent).where(SponsorshipEvent.llm_task.is_not(None))):
        r = reviews.get(e.id)
        if r is None:
            continue
        truth = r.correct_class if r.verdict == "ok" else None
        rv_n += 1
        rv_rule += int(truth == e.cls)
        rv_ai += int(truth == (e.llm_cls or e.llm_raw_cls or e.cls))
    cats_rows = list(s.scalars(select(Brand).where(Brand.llm_categories_version.is_not(None))))
    changed, examples = [], {}
    for b in cats_rows:
        rule = [c.get("id") for c in b.categories or []]
        ai = [c.get("id") for c in b.llm_categories or []]
        if b.llm_categories and sorted(rule) != sorted(ai):
            changed.append({"brand": b.name, "domain": b.primary_domain, "rule": rule, "ai": ai,
                            "quotes": [c.get("quote") for c in b.llm_categories or []]})
    for name in ("Chime", "Zenni", "Zocdoc", "Quince", "Uncommongoods", "Rocket Money"):
        b = s.scalar(select(Brand).where(Brand.name == name, Brand.merged_into.is_(None)))
        if b:
            examples[name] = {"before_rule": [c.get("label") for c in b.categories or []],
                              "after_ai": [c.get("label") for c in b.llm_categories or []] if b.llm_categories_version else "not run",
                              "quotes": [c.get("quote") for c in b.llm_categories or []], "method": b.category_method}
    names = list(s.scalars(select(Brand).where(Brand.name_suggestion_status.is_not(None))))
    org = list(s.scalars(select(SponsorshipEvent).where(SponsorshipEvent.llm_task == "organic_audit")))
    return {
        "uncertain": {"total": total_unc, "classified": len(unc), "coverage": round(len(unc) / total_unc, 3) if total_unc else None,
                      "by_llm_class": dict(Counter(e.llm_cls for e in unc)), "model_said": dict(Counter(e.llm_raw_cls for e in unc)),
                      "declared_capped_to_likely": sum(1 for e in unc if e.llm_raw_cls == "declared_sponsorship" and e.llm_cls != "declared_sponsorship"),
                      "now_counts_as_history": sum(1 for e in unc if e.llm_cls in ("declared_sponsorship", "likely_sponsorship")),
                      "examples": [{"snippet": e.snippet, "rule": e.rule, "ai": e.llm_cls, "model_said": e.llm_raw_cls, "reason": e.llm_reason,
                                    "quote": e.llm_quote} for e in _sample(unc)]},
        "organic_audit": {**miss_rate(s), "examples_promoted": [{"snippet": e.snippet, "quote": e.llm_quote, "reason": e.llm_reason}
                                                                for e in _sample([x for x in org if x.llm_flag])],
                          "examples_confirmed_organic": [{"snippet": e.snippet} for e in _sample([x for x in org if not x.llm_flag], 5)]},
        "human_review_vs_rules_and_llm": {"reviewed": rv_n, "rules_correct": rv_rule, "llm_correct": rv_ai,
                                          "note": None if rv_n else "No human reviews of LLM-touched events yet: accuracy unmeasured."},
        "categories": {"brands_run": len(cats_rows), "with_ai_categories": sum(1 for b in cats_rows if b.llm_categories),
                       "no_supported_category": sum(1 for b in cats_rows if not b.llm_categories),
                       "changed_vs_rules": len(changed), "changed": changed,
                       "sensitive_assigned": [{"brand": b.name, "cats": [c["id"] for c in b.llm_categories if c.get("sensitive")],
                                               "quotes": [c["quote"] for c in b.llm_categories if c.get("sensitive")]}
                                              for b in cats_rows if any(c.get("sensitive") for c in b.llm_categories or [])],
                       "known_cases": examples},
        "names": {"suggested": len(names), "by_status": dict(Counter(b.name_suggestion_status for b in names)),
                  "list": [{"name": b.name, "suggestion": b.name_suggestion, "status": b.name_suggestion_status,
                            "exact_snippets": b.name_suggestion_support} for b in names]},
    }


def phrasing(s) -> dict:
    ok = s.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.action == "phrase_faithful")) or 0
    bad = list(s.scalars(select(AuditLog).where(AuditLog.action == "phrase_unfaithful")))
    return {"phrasings_checked": ok + len(bad), "faithful": ok, "unfaithful_fell_back_to_template": len(bad),
            "unfaithful_rate": round(len(bad) / (ok + len(bad)), 3) if (ok + len(bad)) else None,
            "examples_problems": [b.detail.get("problems") for b in bad[:10]],
            "cached_phrasings": s.scalar(select(func.count()).select_from(LlmCache).where(LlmCache.task == "phrase")) or 0}


def main() -> int:
    startup(use_alembic=True, start_worker=False)
    with session_scope() as s:
        cache_blobs = [json.dumps(c.output) for c in s.scalars(select(LlmCache))]
        out = {"llm_active": llm_active(), "status": m.status(), "calls": m.call_metrics(s), "layer1": m.corpus_comparison(s),
               "layer1_human_accuracy": human_accuracy(s), "layer1_examples": layer1_examples(s), "sponsors": sponsors(s),
               "phrasing": phrasing(s),
               "privacy": {"cached_outputs": len(cache_blobs), "outputs_with_email": sum(1 for b in cache_blobs if EMAIL.search(b))}}
    OUT.write_text(json.dumps(out, indent=1, default=str, ensure_ascii=False), encoding="utf-8")
    short = {k: out[k] for k in ("llm_active", "layer1", "layer1_human_accuracy", "privacy", "phrasing")}
    short["calls"] = out["calls"]["total"]
    short["sponsors"] = {k: {kk: vv for kk, vv in v.items() if kk not in ("examples", "changed", "list", "examples_promoted",
                                                                           "examples_confirmed_organic", "known_cases")}
                         for k, v in out["sponsors"].items()}
    print(json.dumps(short, indent=1, default=str))
    print("written", OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
