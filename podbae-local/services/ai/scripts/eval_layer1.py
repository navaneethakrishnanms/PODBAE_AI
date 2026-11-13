"""Layer 1 evaluation after Phase 1.   python scripts/eval_layer1.py report     -> ../../EVAL_LAYER1.md

Scores ONLY human labels from the store (admin /admin/labels). Claude-written drafts in eval/labels.yaml are marked
`labeler: claude-draft` and are never scored. Compares, on the same shows:
  OLD = the Layer 1 mock heuristic (rules.heuristic_analysis + old title-pattern guest rule), recomputed from stored text
  NEW = the Phase 1 rule/model pipeline (live provenance values)
Also: style-similarity before/after (Step 5), dedupe (Step 6), seed / coverage / feed failures (Steps 2-3), costs and
the no-LLM ledger check."""
from __future__ import annotations

try:  # import torch BEFORE other native libraries: on Windows a different DLL load order can make torch fail
    import torch  # noqa: F401  (WinError 127 on fbgemm.dll), and the embedding model then cannot load
    # Phase 2: sentence_transformers must ALSO load before lxml (RSS connector): lxml.etree first, then
    # sentence_transformers (-> sklearn/scipy) segfaults the process in the torch_gpu env (access violation on import).
    import sentence_transformers  # noqa: F401
except Exception:  # noqa: BLE001 - reported later by the embedder, which refuses to fall back silently
    pass

import json
import sqlite3
import statistics
import sys
import time
from itertools import combinations
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.envfile import load_env  # noqa: E402

load_env()
from sqlalchemy import func, select  # noqa: E402

from app import intel  # noqa: E402
from app.intel.config import REPO_ROOT  # noqa: E402
from app.intel.db import session_scope  # noqa: E402
from app.intel.labels import agreement, human_labels, jaccard  # noqa: E402
from app.intel.models import CostLedger, Embedding, Episode, EvalLabel, LabelItem, Provenance, Show  # noqa: E402
from app.intel.trust import budget  # noqa: E402
from app.intel.trust.provenance import live_rows  # noqa: E402
from app.intel.understanding import signals as sg  # noqa: E402
from app.intel.understanding.rules import compute_facts, heuristic_analysis  # noqa: E402
from app.intel.linalg import dot, gram, norm  # noqa: E402
from app.intel.vectors import from_blob, get_embedder  # noqa: E402

EVAL = ROOT / "eval"
OLD_STYLE_MAP = {"educational_lecture": "mixed_or_other", "mixed": "mixed_or_other"}


def val(s, sid, f):
    rows = live_rows(s, "show", sid, f)
    if not rows:
        return None
    rows.sort(key=lambda r: ({"verified": 0, "creator_provided": 1, "estimated": 2, "inferred": 3}[r.data_tier], -r.fetched_at.timestamp()))
    return rows[0].value_json


def pct(a, b) -> str:
    return f"{100 * a / b:.0f}%" if b else "n/a"


def prf(tp, fp, fn):
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    return p, r, (2 * p * r / (p + r) if p + r else 0.0)


def old_prediction(s, sid) -> dict:
    """The Layer 1 mock heuristic, recomputed from the same stored text the mock provider used to see."""
    sh = s.get(Show, sid)
    eps = list(s.scalars(select(Episode).where(Episode.show_id == sid, Episode.removed.is_(False)).order_by(Episode.published_at.desc()).limit(20)))
    facts = compute_facts([e.published_at for e in eps], [e.duration_sec for e in eps], [e.title for e in eps], [e.persons or [] for e in eps],
                          [{"name": h, "role": "host"} for h in (val(s, sid, "hosts") or [])], None)
    gp = facts["guests_present"] or {}
    a = heuristic_analysis(title=sh.title or "", description=val(s, sid, "description") or "", categories=val(s, sid, "categories") or [],
                           episode_titles=[e.title for e in eps[:10]], episode_texts=[f"{e.title}\n{(e.description or '')[:600]}" for e in eps[:10]],
                           guest_share=gp.get("share", 0.0), n_hosts=max(1, len(val(s, sid, "hosts") or [])))
    return a


def old_topics_to_taxonomy(names: list[str]) -> set[str]:
    out: set[str] = set()
    for n in names:
        d = sg.declared_topics([n])
        out |= set(d["topics"])
        for tid, t in sg.taxonomy().items():
            if sg.compile_lexicon(t["keywords"]).search(n) or n.lower() == t["label"].lower():
                out.add(tid)
    return out


def top3(v: dict | None) -> list[str]:
    return [k for k, x in sorted((v or {}).items(), key=lambda kv: -kv[1]) if x > 0][:3]


# ───────────────────────────── 1. human labels ─────────────────────────────
def section_labels(out: list[str]) -> dict:
    res: dict = {}
    import yaml
    drafts = yaml.safe_load((EVAL / "labels.yaml").read_text(encoding="utf-8")) if (EVAL / "labels.yaml").exists() else {}
    n_draft = len((drafts or {}).get("shows") or {})
    with session_scope() as s:
        labs = human_labels(s)
        n_items = s.scalar(select(func.count()).select_from(LabelItem)) or 0
        ag = agreement(s)
        out.append("## 1. Extraction vs HUMAN labels\n")
        out.append(f"Label set: **{n_items} shows** (stratified across category groups, `label_items`). Human labels stored: **{len(labs)}** "
                   f"from **{len({l.labeler for l in labs})}** labeler(s). Claude-written drafts excluded from scoring: {n_draft} (`labeler: claude-draft`).\n")
        if not labs:
            out.append("**Not available yet: no human labels exist.** Label the 30 shows at http://localhost:5173/admin/labels (admin login), "
                       "then re-run `python scripts/eval_layer1.py report`. Until then there is NO accuracy number for topics, vibe, style or "
                       "guest-friendliness, and the acceptance targets (style above the majority baseline, guest-friendly F1 >= 0.7, topic "
                       "Jaccard per category) are **not yet measurable**.\n")
            res["human_labels"] = 0
            return res
        if ag["status"] != "ok":
            out.append(f"_Agreement: {ag['message']} Results below are single-labeler results._\n")
        else:
            out.append("| Pair | Shared | Style kappa | Guest kappa | Topics Jaccard | Topic-group Jaccard | Vibes Jaccard |\n|---|---|---|---|---|---|---|")
            out += [f"| {p['a']} x {p['b']} | {p['shared']} | {p.get('style_kappa')} | {p.get('guest_kappa')} | {p.get('topics_jaccard')} | "
                    f"{p.get('topic_groups_jaccard')} | {p.get('vibes_jaccard')} |" for p in ag["pairs"]]
            out.append("")
        for labeler in sorted({l.labeler for l in labs}):
            L = [l for l in labs if l.labeler == labeler and s.get(Show, l.show_id) is not None]
            n = len(L)
            styles = [l.style for l in L]
            maj = max(set(styles), key=styles.count)
            m = {"old": {"style": 0, "tp": 0, "fp": 0, "fn": 0, "tj": [], "vj": [], "gj": []},
                 "new": {"style": 0, "tp": 0, "fp": 0, "fn": 0, "tj": [], "vj": [], "gj": [], "unknown": 0}}
            per_cat: dict[str, dict[str, list[float]]] = {}
            for l in L:
                old = old_prediction(s, l.show_id)
                new_style = val(s, l.show_id, "conversational_style")
                new_g = bool((val(s, l.show_id, "guests_present") or {}).get("value"))
                old_g = (old["guest_friendliness"] or 0) >= 0.4
                new_t = {t["id"] for t in (val(s, l.show_id, "topics") or [])}
                old_t = old_topics_to_taxonomy([t["name"] for t in old["topics"]])
                grp = lambda ts: {sg.taxonomy()[t]["group"] for t in ts}  # noqa: E731
                for k, st, g, t, v in (("old", OLD_STYLE_MAP.get(old["conversational_style"], old["conversational_style"]), old_g, old_t, top3(old["vibe"])),
                                       ("new", new_style, new_g, new_t, top3(val(s, l.show_id, "vibe")))):
                    m[k]["style"] += int(st == l.style)
                    m[k]["tp"] += int(g and l.guest_friendly); m[k]["fp"] += int(g and not l.guest_friendly); m[k]["fn"] += int((not g) and l.guest_friendly)
                    m[k]["tj"].append(jaccard(t, l.topics)); m[k]["gj"].append(jaccard(grp(t), grp(l.topics))); m[k]["vj"].append(jaccard(v, l.vibes))
                    cat = (val(s, l.show_id, "category_group") or ["?"])[0] if val(s, l.show_id, "category_group") else "?"
                    per_cat.setdefault(cat, {"old": [], "new": []})[k].append(jaccard(t, l.topics))
                m["new"]["unknown"] += int(new_style == "unknown")
            po, ro, fo = prf(m["old"]["tp"], m["old"]["fp"], m["old"]["fn"])
            pn, rn, fn_ = prf(m["new"]["tp"], m["new"]["fp"], m["new"]["fn"])
            mean = lambda xs: sum(xs) / len(xs) if xs else 0.0  # noqa: E731
            out += [f"\n### Labeler `{labeler}` ({n} shows)\n", "| Field | Metric | OLD (Layer 1 mock heuristic) | NEW (Phase 1 rules + local model) | Baseline / target |",
                    "|---|---|---|---|---|",
                    f"| conversational style | accuracy (6 classes) | {m['old']['style']}/{n} = {pct(m['old']['style'], n)} | {m['new']['style']}/{n} = {pct(m['new']['style'], n)} "
                    f"({m['new']['unknown']} said 'unknown') | always '{maj}' = {pct(styles.count(maj), n)}; target: clearly above |",
                    f"| guest-friendly | precision / recall / F1 | {po:.2f} / {ro:.2f} / **{fo:.2f}** | {pn:.2f} / {rn:.2f} / **{fn_:.2f}** | target F1 >= 0.70 |",
                    f"| topics | mean Jaccard vs labelled taxonomy ids | {mean(m['old']['tj']):.2f} | {mean(m['new']['tj']):.2f} | |",
                    f"| topic groups | mean Jaccard of topic groups | {mean(m['old']['gj']):.2f} | {mean(m['new']['gj']):.2f} | |",
                    f"| vibe | mean Jaccard of top-3 | {mean(m['old']['vj']):.2f} | {mean(m['new']['vj']):.2f} | random 3 of 12 ~ 0.15 |", ""]
            out += ["Topic Jaccard per category group (OLD -> NEW): " + "; ".join(f"{c}: {mean(v['old']):.2f} -> {mean(v['new']):.2f} (n={len(v['new'])})"
                                                                              for c, v in sorted(per_cat.items())) + "\n"]
            res[labeler] = {"n": n, "style_new": m["new"]["style"] / n, "style_majority": styles.count(maj) / n, "guest_f1_new": fn_,
                            "guest_f1_old": fo, "topic_j_new": mean(m["new"]["tj"]), "topic_j_old": mean(m["old"]["tj"])}
        res["human_labels"] = len(labs)
    return res


# ───────────────────────────── 2. style similarity (Step 5) ─────────────────────────────
def pairwise_stats(vecs: list[np.ndarray]) -> dict:
    if len(vecs) < 3:
        return {}
    m = np.stack([v / (norm(v) or 1) for v in vecs])
    sims = gram(m)[np.triu_indices(len(vecs), 1)]
    return {"n": len(vecs), "p10": round(float(np.percentile(sims, 10)), 3), "p50": round(float(np.percentile(sims, 50)), 3),
            "p90": round(float(np.percentile(sims, 90)), 3)}


def old_style_text(a: dict) -> str:
    """Exactly the Layer 1 ingest.style_text() construction, applied to the old heuristic output."""
    vibe = a["vibe"]
    ranked = [k for k, v in sorted(vibe.items(), key=lambda kv: -kv[1]) if v > 0][:4]
    weighted = [t for k in ranked for t in [k] * (2 if vibe[k] >= 0.75 else 1)]
    parts = weighted + list(a.get("tone") or []) + [(a.get("conversational_style") or "mixed").replace("_", " ")] + [v.replace("_", " ") for v in (a.get("values") or [])]
    return ", ".join(parts) or "unspecified"


MATCH_GROUPS = ["Comedy", "True Crime", "Religion & Spirituality", "Health & Fitness", "Technology", "Sports", "Kids & Family", "Business",
                "TV & Film", "Education"]
CONTRAST = [("Comedy", "Religion & Spirituality"), ("True Crime", "Kids & Family"), ("Sports", "Religion & Spirituality"), ("Comedy", "Education"),
            ("True Crime", "Health & Fitness"), ("Technology", "Kids & Family"), ("Business", "True Crime"), ("TV & Film", "Health & Fitness"),
            ("Sports", "Education"), ("Comedy", "Business")]


def section_style(out: list[str]) -> dict:
    res: dict = {}
    out.append("## 2. Style similarity: diagnosis and fix (Step 5)\n")
    # before, Layer 1 store (archived): text-embedded style vectors as they were
    archived = sorted((REPO_ROOT / "data" / "archive").glob("intel_layer1_*/intel.db")) if (REPO_ROOT / "data" / "archive").exists() else []
    before_l1 = {}
    if archived:
        con = sqlite3.connect(str(archived[-1]))
        vs = [np.frombuffer(b, dtype=np.float32) for (b,) in con.execute("SELECT vector FROM embeddings WHERE space='style' AND entity_type='show'")]
        con.close()
        before_l1 = pairwise_stats(vs)
    with session_scope() as s:
        roots = [sh.id for sh in s.scalars(select(Show).where(Show.merged_into.is_(None)).order_by(Show.id))]
        groups = {sid: ((val(s, sid, "category_group") or ["?"]) or ["?"])[0] for sid in roots}
        # before, same corpus: the old method (old heuristic -> short label text -> e5 text embedding)
        texts = {sid: old_style_text(old_prediction(s, sid)) for sid in roots}
        emb = get_embedder()
        from app.intel.vectors import embedder_status
        res["embedder"] = embedder_status()
        if res["embedder"]["fallback_reason"] or emb.name == "hash-embed-v1":
            raise RuntimeError(f"e5 did not load ({res['embedder']}); refusing to report a 'before' number from the hash fallback")
        ids = list(texts)
        old_vecs = dict(zip(ids, emb.embed([texts[i] for i in ids]))) if ids else {}
        new_vecs = {e.entity_id: from_blob(e.vector) for e in s.scalars(select(Embedding).where(Embedding.space == "style", Embedding.entity_type == "show"))
                    if e.entity_id in groups}
        styles = {sid: val(s, sid, "conversational_style") for sid in roots}
    before = pairwise_stats(list(old_vecs.values()))
    after = pairwise_stats(list(new_vecs.values()))
    cos = lambda vs, a, b: dot(vs[a], vs[b]) / ((norm(vs[a]) * norm(vs[b])) or 1)  # noqa: E731
    out += ["**Cause.** Layer 1 embedded a short comma-joined label string (e.g. `Educational, Professional, curious, interview, tech innovation`) "
            "with the sentence model. Every show's string is drawn from the same ~40-word vocabulary and has the same shape, and e5 sentence embeddings "
            "have a large shared component for short texts (anisotropy), so nearly all pairs land at cosine 0.95-0.99 whatever the labels say. The "
            "vector mostly encoded 'this is a short list of podcast adjectives', not which adjectives.\n",
            "**Fix.** A numeric style vector: 12 calibrated vibe scores + one-hot conversational style (5) + multi-hot tone (8), L2-normalised, "
            "then mean-centred across the corpus and re-normalised, so cosine measures how a show *differs from the average show*. Content "
            "embeddings are unchanged.\n",
            "| Pairwise style cosine | n shows | p10 | p50 | p90 |", "|---|---|---|---|---|"]
    if before_l1:
        out.append(f"| BEFORE: Layer 1 store as it was (archived) | {before_l1['n']} | {before_l1['p10']} | {before_l1['p50']} | {before_l1['p90']} |")
    if before:
        out.append(f"| BEFORE: old method re-applied to the Phase 1 corpus | {before['n']} | {before['p10']} | {before['p50']} | {before['p90']} |")
    if after:
        out.append(f"| AFTER: numeric, mean-centred (Phase 1) | {after['n']} | {after['p10']} | {after['p50']} | {after['p90']} |")
    out.append("")
    # matched vs contrasting pairs, chosen by category group only (independent of the style vector itself)
    by_g: dict[str, list[str]] = {}
    for sid, g in groups.items():
        if sid in new_vecs:
            by_g.setdefault(g, []).append(sid)
    matched = []
    for g in MATCH_GROUPS:
        cands = by_g.get(g, [])
        pair = next(((a, b) for a, b in combinations(cands, 2) if styles.get(a) == styles.get(b) and styles.get(a) != "unknown"), None) \
            or (tuple(cands[:2]) if len(cands) >= 2 else None)
        if pair:
            matched.append(pair)
    contrasting = [(by_g[a][0], by_g[b][0]) for a, b in CONTRAST if by_g.get(a) and by_g.get(b)]
    with session_scope() as s:
        title = {sid: (s.get(Show, sid).title or "")[:40] for sid in groups}
    rows_m = [(a, b, cos(new_vecs, a, b), cos(old_vecs, a, b)) for a, b in matched[:10]]
    rows_c = [(a, b, cos(new_vecs, a, b), cos(old_vecs, a, b)) for a, b in contrasting[:10]]
    if rows_m and rows_c:
        mm, mc = statistics.mean(r[2] for r in rows_m), statistics.mean(r[2] for r in rows_c)
        om, oc = statistics.mean(r[3] for r in rows_m), statistics.mean(r[3] for r in rows_c)
        wins = sum(1 for x in rows_m for y in rows_c if x[2] > y[2]) / (len(rows_m) * len(rows_c))
        out += [f"**Matched vs contrasting pairs** (pairs chosen by category group only: matched = two shows of the same group, preferring the same "
                f"rule-detected style; contrasting = groups with opposite registers, e.g. Comedy vs Religion). NEW mean cosine: matched **{mm:.2f}** vs "
                f"contrasting **{mc:.2f}** (gap {mm - mc:+.2f}; a matched pair beats a contrasting pair {wins:.0%} of the time). "
                f"OLD method on the same pairs: matched {om:.2f} vs contrasting {oc:.2f} (gap {om - oc:+.2f}).\n",
                "| Type | Show A | Show B | NEW cosine | OLD cosine |", "|---|---|---|---|---|"]
        out += [f"| matched ({groups[a]}) | {title[a]} | {title[b]} | {n:.2f} | {o:.2f} |" for a, b, n, o in rows_m]
        out += [f"| contrasting ({groups[a]} vs {groups[b]}) | {title[a]} | {title[b]} | {n:.2f} | {o:.2f} |" for a, b, n, o in rows_c]
        out.append("")
        res.update({"matched_mean": mm, "contrast_mean": mc, "old_matched": om, "old_contrast": oc, "win_rate": wins})
    res.update({"before_l1": before_l1, "before": before, "after": after})
    return res


# ───────────────────────────── 3-5. dedupe, ingestion, costs ─────────────────────────────
def section_rest(out: list[str]) -> None:
    d = json.loads((EVAL / "dedupe_results.json").read_text(encoding="utf-8")) if (EVAL / "dedupe_results.json").exists() else None
    out.append("## 3. Dedupe (Step 6, constructed cases)\n")
    if d:
        out += [f"{d['feeds']} synthetic feeds ({d['true_entities']} true shows -> {d['predicted_shows']} predicted). **Precision {d['precision']:.3f}** "
                f"(false merges: {d['fp']}), **recall {d['recall']:.3f}** (missed merges: {d['fn']}).",
                "New negatives: same-title homonyms with colliding short episode guids ('ep-1'...), a same-title SUBSET feed whose guids are all "
                "contained in the other, and same title + same artwork but different podcast:guid. New positives: host migration with all-new guids "
                "but the same owner (salted e-mail hash), and with the same artwork.",
                f"Missed: {json.dumps([e['b'] for e in d.get('missed_merges', d['errors'])])}\n"]
    with session_scope() as s:
        from app.intel.models import AuditLog
        merges = list(s.scalars(select(AuditLog).where(AuditLog.action == "merge_shows")))
        kept = s.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.action == "same_title_kept_separate"))
    out.append(f"Real seed run: {len(merges)} automatic merge(s); {kept} same-title pair(s) kept separate because no strong signal agreed. "
               + ("; ".join(str(m.detail) for m in merges[:5]) if merges else "") + "\n")

    out.append("## 4. Feed fetching, seed, coverage (Steps 2-3)\n")
    fd = json.loads((EVAL / "feed_diagnosis.json").read_text(encoding="utf-8")) if (EVAL / "feed_diagnosis.json").exists() else None
    fo = json.loads((EVAL / "feed_diagnosis_oldfetcher.json").read_text(encoding="utf-8")) if (EVAL / "feed_diagnosis_oldfetcher.json").exists() else None
    if fd:
        kinds = sorted(set(fd["before"]) | set(fd["after"]) | set((fo or {}).get("after", {})), key=lambda k: (k != "ok", k))
        out += [f"Same {fd['feeds']} Layer 1 feed URLs, three measurements:\n",
                "| Outcome | Layer 1 run (as recorded) | Today, OLD fetcher settings | Today, Phase 1 fetcher |", "|---|---|---|---|"]
        out += [f"| {k} | {fd['before'].get(k, 0)} | {(fo or {}).get('after', {}).get(k, '–') if fo else '–'} | {fd['after'].get(k, 0)} |" for k in kinds]
        out.append(f"\nOf the {fd['after'].get('ok', 0)} feeds that fetch today, only {fd['ok_active_90d']} published in the last 90 days: the Layer 1 "
                   "gPodder list was mostly old or dead shows, which is why the Phase 1 seed uses iTunes Search + the independent/active filter.\n")
    sr = json.loads((EVAL / "seed_run.json").read_text(encoding="utf-8")) if (EVAL / "seed_run.json").exists() else None
    if sr and "accepted_by_seed_group" in sr:
        out += [f"**Phase 1 seed** ({sr['finished']}, {sr['wall_seconds']} s): **{sr['shows_in_store']} shows** in the store (target {sr['target']}). "
                f"Feeds attempted {sr['attempted_feeds']}, fetched OK {sr['fetch_ok']} ({pct(sr['fetch_ok'], sr['attempted_feeds'])}), ingest failures {sr['ingest_failed']}.",
                "", "| Group | Quota | Accepted |", "|---|---|---|"]
        out += [f"| {g} | {sr['quota'][g]} | {sr['accepted_by_seed_group'][g]} |" for g in sr["quota"]]
        out += ["", f"By activity: {sr['by_activity']}. By language: {sr['by_language']}. Conversational style: {sr['by_style']}.",
                f"Rejections at the iTunes-metadata stage: {sr['rejections']['directory']}.",
                f"Rejections after reading the RSS feed: {sr['rejections']['rss']}.", f"Fetch failures: {sr['fetch_failures']}.",
                f"Ingestion time per show: median {sr['ingest_seconds']['median']} s, p95 {sr['ingest_seconds']['p95']} s.\n"]
    with session_scope() as s:
        from app.intel.api import admin_coverage
        cov = admin_coverage()
    for c, a in cov["connectors"].items():
        out += [f"**Coverage, connector `{c}`** ({a['shows_ok']}/{a['shows_attempted']} shows):", "", "| Field | % |", "|---|---|"]
        out += [f"| {f} | {v['pct']}% |" for f, v in a["fields"].items()]
        out.append("")
    out.append("Podcast Index and Taddy: **not tested (no keys)**.\n")

    out.append("## 5. Costs and the no-LLM check\n")
    with session_scope() as s:
        cs = budget.summary(s)
        llm_rows = s.scalar(select(func.count()).select_from(CostLedger).where(CostLedger.operation == "llm_extract"))
        llm_prov = s.scalar(select(func.count()).select_from(Provenance).where(Provenance.method == "llm"))
        methods = dict(s.execute(select(Provenance.method, func.count()).where(Provenance.superseded_by.is_(None)).group_by(Provenance.method)).all())
    out += [f"- LLM ledger rows: **{llm_rows}**; provenance rows with method=llm: **{llm_prov}** (Phase 1 requires 0).",
            f"- Live provenance rows by method: {methods}.",
            f"- Total estimated spend ${cs['total_usd']} (local GPU time only); avg ${cs['avg_usd_per_show']}/show, p95 ${cs['p95_usd_per_show']}/show.",
            f"- Embedding cache-hit rate in the ledger: {cs['cache_hit_rate_enrichment']}."]
    out += [f"- {op}: {v['calls']} ledger rows, {v['cache_hits']} cache hits, {v['skipped']} skipped, ${v['usd']}" for op, v in cs["by_operation"].items()]
    out.append("")


def section_layer4(out: list[str]) -> dict:
    """What Layer 4 can rely on: per field, share of shows that have it, its tier(s), method(s) and confidence range."""
    from app.intel.profile import FIELDS
    extra = ["vibe_similarity", "style_features", "category_group", "image", "owner_email_hash", "show_type", "directory_categories"]
    with session_scope() as s:
        roots = [sh.id for sh in s.scalars(select(Show).where(Show.merged_into.is_(None)))]
        n = len(roots)
        rows = list(s.scalars(select(Provenance).where(Provenance.entity_type == "show", Provenance.superseded_by.is_(None))))
        styles: dict[str, int] = {}
        topics_n: list[int] = []
        for sid in roots:
            st = val(s, sid, "conversational_style") or "missing"
            styles[st] = styles.get(st, 0) + 1
            topics_n.append(len(val(s, sid, "topics") or []))
    by: dict[str, list[Provenance]] = {}
    root_set = set(roots)
    for r in rows:
        if r.entity_id in root_set:
            by.setdefault(r.field, []).append(r)
    out += ["## 6. What Layer 4 can rely on (measured over the store)\n", f"{n} shows. One row per profile field; 'present' = share of shows with a live value.\n",
            "| Field | Present | Tier(s) | Method(s) | Confidence min / median / max |", "|---|---|---|---|---|"]
    res = {}
    for f in [x[0] for x in FIELDS] + extra:
        rs = by.get(f, [])
        shows = {r.entity_id for r in rs}
        if not rs:
            out.append(f"| {f} | 0% | – | – | – |")
            continue
        confs = sorted(r.confidence for r in rs)
        tiers = sorted({r.data_tier for r in rs})
        meths = sorted({r.method for r in rs})
        out.append(f"| {f} | {pct(len(shows), n)} | {', '.join(tiers)} | {', '.join(meths)} | {confs[0]:.2f} / {statistics.median(confs):.2f} / {confs[-1]:.2f} |")
        res[f] = {"present": len(shows) / n if n else 0, "tiers": tiers, "methods": meths}
    out += ["", f"Conversational style distribution: {styles}.",
            f"Topics per show (after the evidence rule): mean {statistics.mean(topics_n):.1f}, shows with none {sum(1 for x in topics_n if x == 0)}.\n"
            if topics_n else ""]
    return res


def cmd_report() -> None:
    intel.startup(start_worker=False)
    out = ["# EVAL_LAYER1: measured numbers (after Phase 1)\n",
           f"_Generated {time.strftime('%Y-%m-%d %H:%M')} by `python scripts/eval_layer1.py report` from the local intelligence store. "
           "No LLM was used to produce any value measured here._\n"]
    res = {"labels": section_labels(out), "style": section_style(out)}
    section_rest(out)
    res["layer4"] = section_layer4(out)
    (REPO_ROOT / "EVAL_LAYER1.md").write_text("\n".join(out), encoding="utf-8")
    (EVAL / "eval_summary.json").write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
    print(f"wrote {REPO_ROOT / 'EVAL_LAYER1.md'}")
    print(json.dumps(res, indent=1, default=str)[:3000])


if __name__ == "__main__":
    {"report": cmd_report}[sys.argv[1] if len(sys.argv) > 1 else "report"]()
