"""Layer 2 evaluation. No LLM. Writes eval/layer2.json and prints a summary.
    python scripts/eval_layer2.py           (npm run intel:eval2)
1. corpus statistics (class counts, coverage, network-only share, brands, top brands, events / month)
2. privacy check over every stored snippet (no e-mail, no contact line)
3. sponsor-opportunity coverage over all store shows as hypothetical members (read-only)
4. brand-merge precision / recall on a CONSTRUCTED set, run through the real scan + resolve code in a temp database
5. human-review precision per class (only if reviews exist)"""
from __future__ import annotations

try:  # native load order (see app/main.py)
    import torch  # noqa: F401
    import sentence_transformers  # noqa: F401
except Exception:  # noqa: BLE001
    pass
import json
import os
import re
import statistics as st
import sys
import tempfile
import time
from collections import Counter
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.envfile import load_env  # noqa: E402

load_env()
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")

# (show, episode text) ... and the expected brand partition of the sponsor domains / names
MERGE_CASES = [
    ("s1", "Sponsored by Acme. Visit acme.com/one for 10% off."),
    ("s2", "Thanks to our sponsor: shop.acme.com/two use code TWO"),                 # same registrable domain -> Acme
    ("s3", "This episode is brought to you by Acme. Go to www.acme.com/three"),       # same -> Acme (+ alias)
    ("s1", "Sponsored by Acme Corp. Visit acmecorp.com for 10% off."),               # different domain -> different brand
    ("s2", "Today's sponsor is Zeta Labs."),                                          # name-only
    ("s3", "This episode is sponsored by Zeta Lab."),                                 # different name string: NOT merged
    ("s1", "Visit https://prizepicks.onelink.me/A/x and use code PICK for $50"),       # tenant platform -> prizepicks
    ("s2", "Visit https://underdog.onelink.me/B/y and use code DOG for $50"),          # tenant platform -> underdog (separate)
    ("s3", "Sponsored by Fanduel. Head to fanduel.com/show and use code SHOW."),
    ("s1", "Call 1-800-GAMBLER or visit FanDuel.com/RG or ccpg.org/chat"),           # regulatory disclaimer: no brand at all
    ("s2", "Sponsored by Spotify. Listen on open.spotify.com/show/abc"),              # denylisted platform: no brand
    ("s3", "This episode is sponsored by HelloFresh. Go to hellofresh.com/show for 10 free meals."),
    ("s1", "Sponsored by Factor. Get 50% off at factormeals.com/show with code SHOW."),  # parent HelloFresh via seed, separate brand
]
# expected brand group per case (None = must NOT become a brand at all)
EXPECTED_BY_CASE = ["A", "A", "A", "B", "C", "D", "E", "F", "G", None, None, "H", "I"]


def merge_eval() -> dict:
    """Event-level pairwise precision / recall of 'same brand' decisions on the constructed set (temp DB, rules-only NER):
    every pair of brand-bearing detections is a decision; a pair is a true merge if both expected groups are equal."""
    os.environ["SPONSOR_NER"] = "rules"
    import sqlalchemy as sa
    from app.intel.config import reset_settings
    from app.intel.db import create_all, init_engine, session_scope
    from app.intel.models import Episode, Show, now
    from app.sponsors.models import SponsorshipEvent
    from app.sponsors.scan import scan_all
    tmp = Path(tempfile.mkdtemp()) / "merge_eval.db"
    url = f"sqlite:///{tmp.as_posix()}"
    reset_settings(database_url=url, embed_model="hash")
    from app.intel import vectors
    vectors.reset_embedder()
    init_engine(url)
    create_all()
    with session_scope() as s:
        for sid in ("s1", "s2", "s3"):
            s.add(Show(id=sid, canonical_feed_url=f"https://feeds.test/{sid}.xml", title=f"Show {sid}"))
        s.flush()
        for i, (sid, txt) in enumerate(MERGE_CASES):
            s.add(Episode(id=f"ep_case{i:02d}", show_id=sid, guid=f"g{i}", title=f"Ep {i}", description=txt,
                          published_at=now() - timedelta(days=i + 1)))
    scan_all(["s1", "s2", "s3"])
    got: dict[int, str | None] = {}
    with session_scope() as s:
        for e in s.scalars(sa.select(SponsorshipEvent).where(SponsorshipEvent.cls.in_(("declared_sponsorship", "likely_sponsorship")))):
            i = int(e.episode_id[-2:])
            if e.brand_id:
                got.setdefault(i, e.brand_id)
    wrongly_brand = [i for i, exp in enumerate(EXPECTED_BY_CASE) if exp is None and got.get(i)]
    missed_brand = [i for i, exp in enumerate(EXPECTED_BY_CASE) if exp is not None and not got.get(i)]
    idx = [i for i, exp in enumerate(EXPECTED_BY_CASE) if exp is not None and got.get(i)]
    tp = fp = fn = 0
    for x, i in enumerate(idx):
        for j in idx[x + 1:]:
            same_t, same_p = EXPECTED_BY_CASE[i] == EXPECTED_BY_CASE[j], got[i] == got[j]
            tp += same_t and same_p
            fp += (not same_t) and same_p
            fn += same_t and not same_p
    return {"cases": len(MERGE_CASES), "brand_bearing_cases": len(idx), "pairs": len(idx) * (len(idx) - 1) // 2,
            "true_merges": tp, "false_merges": fp, "missed_merges": fn,
            "precision": round(tp / (tp + fp), 3) if tp + fp else None, "recall": round(tp / (tp + fn), 3) if tp + fn else None,
            "became_brand_but_should_not": wrongly_brand, "should_be_brand_but_is_not": missed_brand,
            "cases_covered": ["same domain via www. / shop. subdomains", "name next to its domain (alias)", "different domain, similar name",
                              "two name-only spellings (never merged)", "tenant link platform (two advertisers on onelink.me)",
                              "regulatory gambling disclaimer", "denylisted platform", "product brand with a seeded parent"]}


def main() -> int:
    from sqlalchemy import select
    from app.intel.db import init_engine, session_scope
    from app.intel.models import now
    from app.opportunities.features import Corpus
    from app.sponsors import opportunities as sp
    from app.sponsors.models import SponsorshipEvent
    from app.sponsors.review import precision
    from app.sponsors.stats import corpus_stats
    init_engine()
    out: dict = {"generated_at": now().isoformat() + "Z"}
    with session_scope() as s:
        out["corpus"] = corpus_stats(s, top=25)
        snips = [e.snippet for e in s.scalars(select(SponsorshipEvent))]
        out["privacy"] = {"snippets": len(snips), "with_email": sum(1 for x in snips if EMAIL.search(x)),
                          "contact_lines_removed": sum(1 for x in snips if "[contact details removed]" in x)}
        out["review"] = precision(s)
        cfg = sp.get_config()
        corpus = Corpus.load(s, now())
        idx = sp.BrandIndex.load(s)
        nq, lat, ready, gates, levels, faith = [], [], Counter(), Counter(), Counter(), 0
        for sid in corpus.ids:
            t = time.perf_counter()
            r = sp.compute(s, corpus, idx, sid, cfg)
            lat.append(1000 * (time.perf_counter() - t))
            nq.append(len(r["qualified"]))
            gates.update(r["gate_counts"])
            for x in r["qualified"]:
                ready[x["readiness"]["level"]] += 1
                levels[x["confidence"]["level"]] += 1
            faith += sum(len(x["explanation"]["faithfulness_problems"]) for x in r["scored"])
        n = len(corpus.ids)
        out["sponsor_opportunities"] = {
            "shows": n, "with_1_plus": sum(x >= 1 for x in nq), "with_3_plus": sum(x >= 3 for x in nq), "no_match": sum(x == 0 for x in nq),
            "qualified_median": st.median(nq), "qualified_by_readiness": dict(ready), "qualified_by_confidence": dict(levels),
            "gate_rejections": dict(gates.most_common()), "faithfulness_problems": faith,
            "latency_ms": {"p50": round(st.median(lat)), "p95": round(sorted(lat)[int(0.95 * (len(lat) - 1))])},
            "scoring_version": cfg["scoring_version"]}
    out["merge_eval"] = merge_eval()
    p = Path(__file__).resolve().parents[1] / "eval" / "layer2.json"
    p.write_text(json.dumps(out, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    print(json.dumps({k: v for k, v in out.items() if k != "corpus"}, indent=1, ensure_ascii=False, default=str))
    c = out["corpus"]
    print(json.dumps({k: c[k] for k in ("events_by_class", "coverage_sponsorship_history", "network_disclosure_only", "brands")}, indent=1))
    print("written", p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
