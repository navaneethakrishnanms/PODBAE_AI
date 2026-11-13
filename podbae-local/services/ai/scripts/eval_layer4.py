"""Layer 4 evaluation without labels (and with labels when they exist). No LLM; read-only (nothing is persisted).

    python scripts/eval_layer4.py [--tag after]     -> eval/layer4_<tag>.json + printed summary

Every store show is treated as a hypothetical member (with its real creator settings) and run through engine.compute()
with an empty interaction history, so runs are comparable before/after a change."""
from __future__ import annotations

try:  # load order: torch, then sentence_transformers, before anything imports lxml (see app/main.py)
    import torch  # noqa: F401
    import sentence_transformers  # noqa: F401
except Exception:  # noqa: BLE001
    pass
import argparse
import json
import statistics as st
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.envfile import load_env  # noqa: E402

load_env()


def pct(v: list[float], p: float) -> float:
    s = sorted(v)
    return round(s[int(p * (len(s) - 1))], 3) if s else 0.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="after")
    a = ap.parse_args()
    from app.intel.db import init_engine, session_scope
    from app.intel.models import now
    from app.opportunities import pairlabels
    from app.opportunities.config import config_hash, get_config
    from app.opportunities.engine import compute
    from app.opportunities.features import Corpus
    from app.opportunities.readiness import readiness
    init_engine()
    cfg = get_config()
    out: dict = {"tag": a.tag, "scoring_version": cfg["scoring_version"], "config_hash": config_hash(cfg), "generated_at": now().isoformat() + "Z"}
    with session_scope() as s:
        t0 = time.perf_counter()
        c = Corpus.load(s, now())
        out["corpus_load_ms"] = int(1000 * (time.perf_counter() - t0))
        nq, lat, fits, confs = [], [], [], []
        reasons, lang_pairs, lang_conflict = Counter(), Counter(), Counter()
        q_ready, q_levels, uncertain_lang = Counter(), Counter(), 0
        div_cos, div_z, faith = [], [], 0
        hashes: dict[str, str] = {}
        for sid in c.ids:
            t = time.perf_counter()
            r = compute(s, c, sid, cfg)
            lat.append(1000 * (time.perf_counter() - t))
            hashes[sid] = r["result_hash"]
            nq.append(len(r["qualified"]))
            for rj in r["rejections"]:
                reasons[rj["reason"]] += 1
                if rj["reason"] == "language_incompatible":
                    d = rj["detail"]
                    lang_pairs[f"{d.get('member')}->{d.get('candidate')}"] += 1
                    conflict = any(k in str(d.get(b, "")) for b in ("member_basis", "candidate_basis") for k in ("conflict", "disagrees"))
                    lang_conflict["declared/detected disagreed on a side" if conflict else "no disagreement"] += 1
            for x in r["scored"]:
                fits.append(x["fit"])
                confs.append(x["confidence"]["value"])
                faith += len(x["explanation"].get("faithfulness_problems") or [])
                if (x.get("gate") or {}).get("language_uncertain"):
                    uncertain_lang += 1
            for x in r["qualified"]:
                q_ready[x["readiness"]["level"]] += 1
                q_levels[x["confidence"]["level"]] += 1
            top = [x["target_show_id"] for x in r["qualified"][:3]]
            pairs = [(i, j) for k, i in enumerate(top) for j in top[k + 1:]]
            if pairs:
                cs = [c.cos(i, j) for i, j in pairs]
                div_cos.append(sum(cs) / len(cs))
                div_z.append(sum(c.z(x) for x in cs) / len(cs))
        det_ok = all(compute(s, c, sid, cfg)["result_hash"] == hashes[sid] for sid in c.ids[:25])
        store_ready = Counter(readiness(c.shows[sid])["level"] for sid in c.ids)
        n = len(c.ids)
        out.update({
            "shows": n, "with_1_plus": sum(x >= 1 for x in nq), "with_3_plus": sum(x >= 3 for x in nq), "no_match": sum(x == 0 for x in nq),
            "qualified_median": st.median(nq), "gate_rejections": dict(reasons.most_common()),
            "language_rejections_by_pair": dict(lang_pairs.most_common()), "language_rejections_by_disagreement": dict(lang_conflict),
            "pairs_scored_with_uncertain_language": uncertain_lang,
            "fit_p10_p50_p90_p99": [pct(fits, p) for p in (0.1, 0.5, 0.9, 0.99)], "confidence_p10_p50_p90": [pct(confs, p) for p in (0.1, 0.5, 0.9)],
            "qualified_by_confidence_level": dict(q_levels), "qualified_by_readiness": dict(q_ready),
            "store_shows_by_readiness": dict(store_ready),
            "top3_diversity": {"shows": len(div_cos), "mean_pairwise_cosine": round(st.mean(div_cos), 4) if div_cos else None,
                               "mean_pairwise_z": round(st.mean(div_z), 2) if div_z else None},
            "faithfulness_problems": faith, "determinism_25_shows": det_ok,
            "latency_ms": {"p50": round(st.median(lat)), "p95": round(pct(lat, 0.95)), "max": round(max(lat))},
            "pair_labels": pairlabels.metrics(s),
        })
    p = Path(__file__).resolve().parents[1] / "eval" / f"layer4_{a.tag}.json"
    p.write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: v for k, v in out.items() if k not in ("language_rejections_by_pair", "pair_labels")}, indent=1, ensure_ascii=False))
    print("language rejections by pair (top 15):", list(out["language_rejections_by_pair"].items())[:15])
    print("written", p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
