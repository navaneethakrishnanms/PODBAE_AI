"""Layer 1 evaluation. Usage (from services/ai):
    python scripts/eval_layer1.py sheet     # pick 30 ingested shows -> eval/label_sheet.md (for hand-labelling)
    python scripts/eval_layer1.py report    # needs eval/labels.yaml -> writes ../../EVAL_LAYER1.md with real numbers
"""
from __future__ import annotations

import json
import os
import random
import statistics
import sys
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
EVAL = ROOT / "eval"

from app.intel.config import REPO_ROOT  # noqa: E402

for line in (REPO_ROOT / ".env").read_text(encoding="utf-8").splitlines() if (REPO_ROOT / ".env").exists() else []:
    if line.strip() and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

from sqlalchemy import func, select  # noqa: E402

from app import intel  # noqa: E402
from app.intel import ingest  # noqa: E402
from app.intel.db import session_scope  # noqa: E402
from app.intel.models import ConnectorRun, CostLedger, Episode, Show  # noqa: E402
from app.intel.trust import budget  # noqa: E402
from app.intel.trust.provenance import live_rows  # noqa: E402
from app.intel.vectors import similar  # noqa: E402

VIBES = ["Casual", "Compelling", "Educational", "Energetic", "Humorous", "Inspirational", "Personal Narrative", "Professional", "Reflective",
         "Relaxed", "Uplifting", "Wellness-Focused"]


def val(s, sid, f):
    r = live_rows(s, "show", sid, f)
    return r[0].value_json if r else None


def pick(n: int = 30) -> list[str]:
    """Stratified deterministic sample: shows with >= 5 episodes and a real description, spread over categories."""
    with session_scope() as s:
        rows = []
        for sh in s.scalars(select(Show).where(Show.merged_into.is_(None))):
            n_eps = s.scalar(select(func.count()).select_from(Episode).where(Episode.show_id == sh.id, Episode.removed.is_(False)))
            d = val(s, sh.id, "description") or ""
            if n_eps >= 5 and len(d) >= 120 and val(s, sh.id, "topics"):
                rows.append((sh.id, (val(s, sh.id, "categories") or ["?"])[0]))
    random.Random(11).shuffle(rows)
    by: dict[str, list[str]] = {}
    for sid, c in rows:
        by.setdefault(c, []).append(sid)
    out: list[str] = []
    while len(out) < n and any(by.values()):
        for c in sorted(by):
            if by[c] and len(out) < n:
                out.append(by[c].pop())
    return out


def cmd_sheet() -> None:
    ids = pick(30)
    lines = ["# Label sheet (30 shows)\n", "Label from the TEXT below only: topics (1-3 words), top-3 vibes (from the fixed 12), conversational style "
             "(solo_monologue | interview | co_hosted_banter | panel | narrative_storytelling | educational_lecture | mixed), guest_friendly (guests appear regularly).\n"]
    with session_scope() as s:
        for sid in ids:
            sh = s.get(Show, sid)
            eps = list(s.scalars(select(Episode).where(Episode.show_id == sid, Episode.removed.is_(False)).order_by(Episode.published_at.desc()).limit(8)))
            lines.append(f"\n## {sid} - {sh.title}\n**Declared categories:** {val(s, sid, 'categories')}\n\n**Description:** {(val(s, sid, 'description') or '')[:700]}\n\n**Recent episode titles:**")
            lines += [f"- {e.title}" for e in eps]
    (EVAL / "label_sheet.md").write_text("\n".join(lines), encoding="utf-8")
    (EVAL / "label_ids.json").write_text(json.dumps(ids), encoding="utf-8")
    print(f"wrote {EVAL / 'label_sheet.md'} ({len(ids)} shows)")


def stem(w: str) -> str:
    w = w.lower().strip()
    for suf in ("ing", "es", "s", "al", "ly"):
        if w.endswith(suf) and len(w) - len(suf) >= 4:
            return w[: -len(suf)]
    return w


def topic_hit(label: str, extracted: list[str]) -> bool:
    ls = stem(label)
    return any(ls in stem(e) or stem(e) in ls or ls in e.lower() for e in extracted)


def pct(a: float, b: float) -> str:
    return f"{100 * a / b:.0f}%" if b else "n/a"


def cmd_report() -> None:
    labels = yaml.safe_load((EVAL / "labels.yaml").read_text(encoding="utf-8"))
    intel.startup(start_worker=False)
    out: list[str] = ["# EVAL_LAYER1: measured numbers\n",
                      f"_Generated {time.strftime('%Y-%m-%d %H:%M')} by `python scripts/eval_layer1.py report` from the real local intelligence store._\n"]

    # ---------------- 1. extraction vs labels ----------------
    topic_hits = topic_total = vibe_overlap = top1_in = n = 0
    style_ok = guest_tp = guest_fp = guest_fn = guest_tn = 0
    rows, confusion = [], []
    with session_scope() as s:
        for sid, lab in labels["shows"].items():
            if s.get(Show, sid) is None:
                continue
            n += 1
            tops = [t["name"] for t in (val(s, sid, "topics") or [])]
            tops += (val(s, sid, "categories") or [])
            hits = [topic_hit(t, tops) for t in lab["topics"]]
            topic_hits += sum(hits); topic_total += len(hits)
            vibe = val(s, sid, "vibe") or {}
            pred3 = [k for k, v in sorted(vibe.items(), key=lambda kv: -kv[1]) if v > 0][:3]
            ov = len(set(pred3) & set(lab["vibe_top3"]))
            vibe_overlap += ov
            top1_in += int(bool(pred3) and pred3[0] in lab["vibe_top3"])
            ps = val(s, sid, "conversational_style")
            style_ok += int(ps == lab["style"])
            if ps != lab["style"]:
                confusion.append((lab["style"], ps))
            gf = (val(s, sid, "guest_friendliness") or 0) >= 0.4
            gl = bool(lab["guest_friendly"])
            guest_tp += gf and gl; guest_fp += gf and not gl; guest_fn += (not gf) and gl; guest_tn += (not gf) and not gl
            rows.append((val(s, sid, "title") or s.get(Show, sid).title, lab["topics"], [t["name"] for t in (val(s, sid, "topics") or [])][:4], lab["vibe_top3"], pred3,
                         lab["style"], ps, lab["guest_friendly"], gf))
    majority_style = max(set(l["style"] for l in labels["shows"].values()), key=[l["style"] for l in labels["shows"].values()].count)
    maj_acc = [l["style"] for l in labels["shows"].values()].count(majority_style) / max(1, len(labels["shows"]))
    guest_base = max(sum(1 for l in labels["shows"].values() if l["guest_friendly"]), sum(1 for l in labels["shows"].values() if not l["guest_friendly"])) / max(1, len(labels["shows"]))
    out += [f"\n## 1. Extraction vs hand labels ({n} shows)\n",
            "**Caveat:** labels in `eval/labels.yaml` were written by Claude from each show's description and episode titles (see `eval/label_sheet.md`), "
            "not by a human listener. They are for you to review and correct; agreement against them measures consistency with a reader of the same text, not ground truth. "
            "The extractor under test is the **mock/heuristic provider** (no LLM key), so this is the floor a real LLM must beat.\n",
            "| Field | Metric | Result | Baseline |", "|---|---|---|---|",
            f"| topics | label topics found among extracted topics/categories (recall) | {topic_hits}/{topic_total} = {pct(topic_hits, topic_total)} | n/a |",
            f"| vibe top-3 | mean overlap of predicted vs labelled top-3 | {vibe_overlap / max(1, n):.2f} / 3 | random 3 of 12 = 0.75 / 3 |",
            f"| vibe top-1 | predicted #1 is in labelled top-3 | {top1_in}/{n} = {pct(top1_in, n)} | random = 25% |",
            f"| conversational style | exact match (7 classes) | {style_ok}/{n} = {pct(style_ok, n)} | always '{majority_style}' = {maj_acc * 100:.0f}% |",
            f"| guest-friendly | accuracy @ threshold 0.4 | {guest_tp + guest_tn}/{n} = {pct(guest_tp + guest_tn, n)} (TP {guest_tp}, FP {guest_fp}, FN {guest_fn}, TN {guest_tn}) | majority = {guest_base * 100:.0f}% |", ""]
    if confusion:
        out.append("Style disagreements (label -> predicted): " + "; ".join(f"{a} -> {b}" for a, b in confusion[:12]) + "\n")
    out += ["<details><summary>Per-show detail</summary>\n", "| Show | Label topics | Predicted topics | Label vibe | Pred vibe | Label style | Pred style | Guest label | Guest pred |", "|---|---|---|---|---|---|---|---|---|"]
    out += [f"| {r[0][:38]} | {', '.join(r[1])} | {', '.join(r[2])} | {', '.join(r[3])} | {', '.join(r[4])} | {r[5]} | {r[6]} | {r[7]} | {r[8]} |" for r in rows]
    out += ["\n</details>\n"]

    # ---------------- 2. dedupe ----------------
    d = json.loads((EVAL / "dedupe_results.json").read_text(encoding="utf-8")) if (EVAL / "dedupe_results.json").exists() else None
    out.append("## 2. Dedupe precision (constructed duplicates)\n")
    if d:
        out += [f"{d['feeds']} synthetic feeds ({d['true_entities']} true shows -> {d['predicted_shows']} predicted shows); {d['pairs']} feed pairs. "
                f"**Precision {d['precision']:.3f}** (FP={d['fp']}), **recall {d['recall']:.3f}** (FN={d['fn']}).",
                "Scenarios: tracking params, trailing slash, same `podcast:guid`, mirror/feedburner copy, 80% episode overlap, moved feed (`itunes:new-feed-url`); "
                "negatives: identical guid strings but different title, homonyms with disjoint episodes, same title in another language, near-identical titles, 30% overlap.",
                f"Misses: {json.dumps([e['b'] for e in d['errors']])}  (deliberately hard: host migration with all-new episode guids and no `podcast:guid`).",
                f"_{d['note']}_\n"]
    with session_scope() as s:
        from app.intel.models import AuditLog
        merges = list(s.scalars(select(AuditLog).where(AuditLog.action == "merge_shows")))
        out.append(f"On the **real** seed run: {len(merges)} automatic merge(s) happened. " + ("; ".join(f"{m.detail}" for m in merges[:5]) if merges else "None, so there is no real-world precision signal beyond the constructed set.") + "\n")

    # ---------------- 3. similarity sanity ----------------
    out.append("## 3. Similarity sanity: top-5 neighbours for 10 shows (you judge)\n")
    random.seed(5)
    with session_scope() as s:
        ids = [i for i in labels["shows"] if s.get(Show, i) is not None]
        random.Random(3).shuffle(ids)
        same_cat = tot = 0
        for sid in ids[:10]:
            sh = s.get(Show, sid)
            base_cat = set(val(s, sid, "categories") or [])
            out.append(f"\n**{sh.title}**  _{', '.join(sorted(base_cat))}_")
            for space in ("content", "style"):
                nb = similar(s, "show", sid, space, 5)
                line = []
                for nid, sim in nb:
                    cats = set(val(s, nid, "categories") or [])
                    if space == "content":
                        tot += 1; same_cat += bool(base_cat & cats)
                    line.append(f"{s.get(Show, nid).title[:34]} ({sim:.2f})")
                out.append(f"- {space}: " + (" · ".join(line) or "(none)"))
        out.append(f"\nProxy: {same_cat}/{tot} content-space neighbours share at least one declared category with the query show ({pct(same_cat, tot)}).\n")

    # ---------------- 4. coverage, cost, cache, time ----------------
    sr = json.loads((EVAL / "seed_run.json").read_text(encoding="utf-8")) if (EVAL / "seed_run.json").exists() else None
    out.append("## 4. Real ingestion: coverage, cost, cache, time\n")
    with session_scope() as s:
        total = s.scalar(select(func.count()).select_from(Show).where(Show.merged_into.is_(None)))
        latest = {}
        for r in s.scalars(select(ConnectorRun).order_by(ConnectorRun.id)):
            if r.show_id:
                latest[(r.connector, r.show_id)] = r
        agg: dict[str, dict] = {}
        for (c, _), r in latest.items():
            a = agg.setdefault(c, {"n": 0, "ok": 0, "cnt": {}, "exp": r.fields_expected})
            a["n"] += 1
            if r.ok:
                a["ok"] += 1
                for f in r.fields_returned:
                    a["cnt"][f] = a["cnt"].get(f, 0) + 1
        out.append(f"Shows in store: **{total}**.\n")
        for c, a in agg.items():
            out += [f"\n**Coverage matrix: connector `{c}`** ({a['ok']} of {a['n']} shows fetched OK). Share of fetched shows where the field was present:\n", "| Field | Present | % |", "|---|---|---|"]
            out += [f"| {f} | {a['cnt'].get(f, 0)} | {pct(a['cnt'].get(f, 0), a['ok'])} |" for f in a["exp"]]
        out.append("\nConnectors not listed (Podcast Index, Taddy) were **not run**: no keys in this environment.\n")
    if sr:
        ok = [r for r in sr["results"] if r["ok"]]
        secs = sorted(r["seconds"] for r in ok)
        fails = [r for r in sr["results"] if not r["ok"]]
        kinds: dict[str, int] = {}
        for r in fails:
            k = r["error"].split(":")[0] + ":" + (r["error"].split(":")[2].strip()[:40] if r["error"].count(":") > 1 else "")
            kinds[k] = kinds.get(k, 0) + 1
        out += [f"\n**Seed run:** {len(sr['results'])} feeds attempted, {len(ok)} ok, {len(fails)} failed; wall time {sr['wall_seconds']} s (6 parallel workers, includes embedding on GPU).",
                f"Ingestion time per show (end-to-end, ok shows): mean {statistics.mean(secs):.2f} s, median {statistics.median(secs):.2f} s, p95 {secs[min(len(secs) - 1, int(.95 * len(secs)))]:.2f} s, max {secs[-1]:.2f} s.",
                "Failure causes: " + (", ".join(f"{k} x{v}" for k, v in sorted(kinds.items(), key=lambda kv: -kv[1])[:6]) or "none") + ".\n"]

    # cache-hit measurement: re-run ingestion (forced re-fetch) for the labelled shows, count enrichment cache behaviour
    with session_scope() as s:
        mark = s.scalar(select(func.max(CostLedger.id))) or 0
        urls = [s.get(Show, i).canonical_feed_url for i in list(labels["shows"])[:30] if s.get(Show, i) is not None]
    t0 = time.perf_counter()
    done = 0
    for u in urls:
        try:
            ingest.run_pipeline(u, force=True); done += 1
        except Exception:  # noqa: BLE001
            pass
    with session_scope() as s:
        rows = list(s.scalars(select(CostLedger).where(CostLedger.id > mark, CostLedger.operation.in_(["llm_extract", "embed"]))))
        llm = [r for r in rows if r.operation == "llm_extract"]
        emb = [r for r in rows if r.operation == "embed"]
        out += [f"**Cache-hit measurement:** re-ingested {done}/{len(urls)} already-ingested shows with a forced re-fetch ({time.perf_counter() - t0:.0f} s). "
                f"Enrichment (LLM-call) cache hits: {sum(r.cache_hit for r in llm)}/{len(llm)} = {pct(sum(r.cache_hit for r in llm), len(llm))}; "
                f"embedding cache hits: {sum(r.cache_hit for r in emb)}/{len(emb)} = {pct(sum(r.cache_hit for r in emb), len(emb))}. "
                "Misses are shows whose feed text changed between the seed run and now (new episode) and are re-processed by design.\n"]
        cs = budget.summary(s)
        out += ["**Cost ledger** (all numbers are *estimates*; the mock LLM and local embeddings have no API cost, GPU time is priced at the configured $/GPU-second):\n",
                f"- total estimated spend: ${cs['total_usd']}; shows costed: {cs['shows_costed']}; **avg ${cs['avg_usd_per_show']} / show, p95 ${cs['p95_usd_per_show']} / show**",
                f"- overall enrichment/embedding cache-hit rate in ledger: {cs['cache_hit_rate_enrichment']}"]
        out += [f"- {op}: {v['calls']} ledger rows, {v['cache_hits']} cache hits, {v['skipped']} skipped, ${v['usd']}" for op, v in cs["by_operation"].items()]
        out.append("\n**Projection if a real LLM were used** (gpt-4o-mini-class list prices, input ~1.5k tokens + output ~400 tokens per show): roughly $0.0005 per show, "
                   "i.e. about $0.15 for 300 shows; unchanged shows cost $0 thereafter because of the content-hash cache. This is arithmetic, not a measurement.\n")
    (REPO_ROOT / "EVAL_LAYER1.md").write_text("\n".join(out), encoding="utf-8")
    print(f"wrote {REPO_ROOT / 'EVAL_LAYER1.md'}")


if __name__ == "__main__":
    {"sheet": cmd_sheet, "report": cmd_report}[sys.argv[1] if len(sys.argv) > 1 else "report"]()
