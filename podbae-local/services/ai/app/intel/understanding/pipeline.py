"""Phase 1 understanding stage (replaces the LLM 'enrich' stage in the ingestion pipeline). NO LLM CALLS.

Writes, for one show, with provenance (source, tier, method rule|model|rule+model, confidence) and evidence snippets:
  declared_topics (verified, rule)       category_group (verified, rule)
  topics (inferred)                      guests_present (verified if podcast:person-based, else inferred)
  guest_friendliness (inferred, rule)    conversational_style (inferred, rule; 'unknown' when not confident)
  tone / values / brand_safety_flags / likely_audience (inferred, rule)
  vibe + vibe_similarity (inferred, model)      style_features + style vector (inferred, rule+model)
"""
from __future__ import annotations

import time
from typing import Any

import numpy as np
from ..linalg import mm
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import Episode, Evidence, Show
from ..trust.provenance import add_evidence, get_source, live_rows, record
from ..vectors import embed_many, embed_queries, get_embedder, upsert_embedding, stored_vector
from . import model_signals as ms
from . import signals as sg
from .refine import refine_enabled

WRITTEN_FIELDS = ["declared_topics", "category_group", "topics", "guests_present", "guest_friendliness", "conversational_style", "tone",
                  "values", "brand_safety_flags", "likely_audience", "vibe", "vibe_similarity", "style_features"]
EVIDENCE_KINDS = ["topics", "guest_friendliness", "conversational_style", "tone", "values", "brand_safety_flags", "vibe", "declared_topics"]


def _fact(s: Session, sid: str, f: str) -> Any:
    rows = live_rows(s, "show", sid, f)
    if not rows:
        return None
    rows.sort(key=lambda r: ({"verified": 0, "creator_provided": 1, "estimated": 2, "inferred": 3}[r.data_tier], -r.fetched_at.timestamp()))
    return rows[0].value_json


def understand_show(s: Session, show_id: str) -> dict:
    t0 = time.perf_counter()
    cfg = get_settings()
    show = s.get(Show, show_id)
    assert show is not None
    rules_src = get_source(s, "podbae-rules", "rule", f"Deterministic rules ({sg.RULES_VERSION}, {sg.taxonomy_version()}); inferred, not measured")
    model_src = get_source(s, "local-model:e5", "local_model", "Local multilingual-e5-small embeddings; inferred, not measured")
    rss_src = get_source(s, "rss", "rss", "Publisher RSS feed; public, fetched with conditional GET")
    eps = list(s.scalars(select(Episode).where(Episode.show_id == show_id, Episode.removed.is_(False))
                         .order_by(Episode.published_at.desc()).limit(cfg.deep_episodes)))
    n_eps = len(eps)
    prelim = n_eps < 3
    desc = _fact(s, show_id, "description") or ""
    categories = list(dict.fromkeys((_fact(s, show_id, "categories") or []) + (_fact(s, show_id, "directory_categories") or [])))
    docs = sg.make_docs(desc, [(e.id, e.title, e.description) for e in eps])
    ep_title = {e.id: e.title for e in eps}
    res: dict[str, Any] = {"mode": "rules+local-model", "llm_calls": 0}

    s.execute(delete(Evidence).where(Evidence.entity_type == "show", Evidence.entity_id == show_id, Evidence.kind.in_(EVIDENCE_KINDS)))

    def ev(kind: str, snippet: str, loc: dict, src=rules_src) -> None:
        if snippet:
            add_evidence(s, "show", show_id, kind, snippet, {**loc, "url": show.canonical_feed_url} if "url" not in loc else loc, src)

    # ── declared topics (publisher categories -> taxonomy). Verified: it is what the publisher says. ──
    dec = sg.declared_topics(categories)
    if categories:
        record(s, "show", show_id, "declared_topics", dec["topics"], source=rss_src, tier="verified", method="rule", confidence=0.9,
               model_version=sg.category_map()["version"], source_ref="RSS/iTunes categories mapped by category_map.yaml")
        record(s, "show", show_id, "category_group", dec["groups"], source=rss_src, tier="verified", method="rule", confidence=0.9,
               model_version=sg.category_map()["version"])
        if dec["topics"]:
            ev("declared_topics", "Declared categories: " + ", ".join(categories[:6]), {"part": "categories"}, rss_src)

    # ── embeddings (local model): content vector + one vector per recent episode ──
    from ..ingest import content_text                       # lazy: ingest imports this module
    upsert_embedding(s, "show", show_id, "content", content_text(s, show), podcast_id=show_id)
    content_vec = stored_vector(s, "show", show_id, "content")
    clean_desc = sg.strip_boilerplate([e.description or "" for e in eps])   # same de-boilerplated text as the rules
    ep_items = [(e.id, f"{e.title}. {c[:600]}") for e, c in zip(eps, clean_desc)]
    ep_vecs = embed_many(s, "episode", ep_items, "episode", podcast_id=show_id, index=False)
    desc_vec = embed_many(s, "show_description", [(show_id, desc[:1500])], "description", podcast_id=show_id, index=False).get(show_id) \
        if desc.strip() else None

    # ── topics: lexicon + embedding, then the evidence rule ──
    lex = sg.lexicon_topics(docs)
    topic_mat = embed_queries(ms.topic_texts())
    emb = ms.embedding_topics(desc_vec, [(eid, ep_title[eid], v) for eid, v in ep_vecs.items()], topic_mat, desc_text=desc)
    topics, dropped = sg.finalize_topics(sg.merge_topic_support(lex, emb), dec["topics"])
    bases = {b for t in topics for b in t["basis"] if b != "declared"}
    tmethod = "rule+model" if bases >= {"lexicon", "model"} else "model" if bases == {"model"} else "rule"
    tconf = (0.55 if "lexicon" in bases else 0.4) - (0.2 if prelim else 0) - (0.1 if not desc.strip() else 0)
    record(s, "show", show_id, "topics", topics, source=rules_src if tmethod != "model" else model_src, tier="inferred", method=tmethod,
           confidence=round(max(0.1, min(0.8, tconf if topics else 0.2)), 2), model_version=f"{sg.taxonomy_version()}/{sg.RULES_VERSION}",
           source_ref=f"{len(topics)} topics met the evidence rule; {len(dropped)} candidates dropped")
    sup = sg.merge_topic_support(lex, emb)
    for t in topics[:5]:
        st = sup[t["id"]]
        if st.desc:
            ev("topics", f"[{t['name']}] {st.desc}"[:300], {"part": "show_description", "topic": t["id"]})
        for eid, sn in st.episodes[:2]:
            ev("topics", f"[{t['name']}] {sn}"[:300], {"episode_id": eid, "topic": t["id"]})
    res["topics"] = {"kept": [t["id"] for t in topics], "dropped": len(dropped)}

    # ── guests ──
    persons = _fact(s, show_id, "hosts") or []
    show_persons = [{"name": h, "role": "host"} for h in persons]
    author = _fact(s, show_id, "author")
    g = sg.detect_guests([(e.id, e.title, e.description, e.persons or []) for e in eps], show_persons, author)
    person_based = g["basis"].startswith("podcast:person")
    gp = {"value": g["guest_friendly"], "basis": g["basis"], "share": g["share"], "guest_episodes": g["guest_episodes"],
          "episodes_checked": g["episodes_checked"], "threshold": g["threshold"]}
    if n_eps:
        record(s, "show", show_id, "guests_present", gp, source=rss_src if person_based else rules_src,
               tier="verified" if person_based else "inferred", method="parsed" if person_based else "rule",
               confidence=1.0 if person_based else round(0.45 + 0.02 * min(10, n_eps) - (0.15 if prelim else 0), 2),
               model_version=sg.RULES_VERSION)
        record(s, "show", show_id, "guest_friendliness", g["share"], source=rules_src, tier="inferred", method="rule",
               confidence=round((0.7 if person_based else 0.5) - (0.2 if prelim else 0), 2), model_version=sg.RULES_VERSION,
               source_ref=f"guest-episode share {g['guest_episodes']}/{g['episodes_checked']} (guest-friendly at >= {g['threshold']})")
        for ex in g["examples"]:
            ev("guest_friendliness", f"{ex['title']} — rule: {ex['rule']}"[:300], {"episode_id": ex["episode_id"]})

    # ── conversational style ──
    hosts_tagged = len(persons)
    durs = [e.duration_sec for e in eps if e.duration_sec]
    st = sg.conversational_style(description=desc, episode_titles=[e.title for e in eps], hosts_tagged=hosts_tagged, author=author,
                                 guest_share=g["share"], avg_minutes=(sum(durs) / len(durs) / 60) if durs else None,
                                 show_type=_fact(s, show_id, "show_type"))
    record(s, "show", show_id, "conversational_style", st["value"], source=rules_src, tier="inferred", method="rule",
           confidence=round(max(0.1, st["confidence"] - (0.15 if prelim and st["value"] != "unknown" else 0)), 2),
           model_version=sg.RULES_VERSION, source_ref="; ".join(f"{k}: {', '.join(v)}" for k, v in st["signals"].items())[:500] or st.get("reason"))
    if st["value"] != "unknown":
        ev("conversational_style", f"{st['value']}: " + "; ".join(st["signals"].get(st["value"], []))[:280], {"part": "rules"})
    res["style"] = st["value"]

    # ── tone / values / brand safety / likely audience (lexicons) ──
    tvs = sg.tone_values_safety(docs, _fact(s, show_id, "explicit"))
    tones = list(tvs["tone"])
    for f, val, conf in (("tone", tones, 0.35), ("values", list(tvs["values"]), 0.35), ("brand_safety_flags", list(tvs["brand_safety_flags"]), 0.4)):
        record(s, "show", show_id, f, val, source=rules_src, tier="inferred", method="rule",
               confidence=round(conf - (0.1 if prelim else 0), 2), model_version=sg.RULES_VERSION,
               source_ref="lexicon matches in >= 2 separate texts")
        for label, hits in tvs[f].items():
            loc, sn = hits[0]
            ev(f, f"[{label}] {sn}"[:300], loc)
    if topics:
        aud = "Listeners interested in " + " and ".join(t["name"].lower() for t in topics[:2]) + "."
        record(s, "show", show_id, "likely_audience", aud, source=rules_src, tier="inferred", method="rule",
               confidence=0.3, model_version=sg.RULES_VERSION, source_ref="interests only, from the top topics; never demographics")

    # ── vibe (model): corpus-calibrated embedding similarity ──
    from .. import calibration as cal
    vver, vdesc = ms.vibe_descriptions()
    vibe_mat = embed_queries(list(vdesc.values()))
    raw = ms.vibe_raw(content_vec, list(ep_vecs.values()), vibe_mat)
    vibe = None
    if raw is not None:
        record(s, "show", show_id, "vibe_similarity", {"raw": raw, "episodes": len(ep_vecs), "model": get_embedder().name, "version": vver},
               source=model_src, tier="inferred", method="model", confidence=0.3, model_version=f"{get_embedder().name}/{vver}")
        vibe, mode = ms.vibe_scores(raw, cal.vibe_stats(s))
        record(s, "show", show_id, "vibe", vibe, source=model_src, tier="inferred", method="model",
               confidence=round((0.35 if mode == "corpus" else 0.2) - (0.1 if prelim else 0), 2),
               model_version=f"{get_embedder().name}/{vver}/{mode}",
               source_ref="corpus z-score of embedding similarity" if mode == "corpus" else "within-show ranking only (corpus not calibrated yet)")
        if ep_vecs:   # evidence: the recent episode most similar to each top vibe
            ids = list(ep_vecs)
            mat = mm(np.stack([ep_vecs[i] for i in ids]), vibe_mat.T.copy())
            for term in sorted(vibe, key=lambda k: -vibe[k])[:3]:
                j = int(np.argmax(mat[:, ms.VIBE_TERMS.index(term)]))
                ev("vibe", f"[{term}] closest episode: {ep_title[ids[j]]}"[:300], {"episode_id": ids[j]}, model_src)
        res["vibe_mode"] = mode

    # ── numeric style vector (Step 5) ──
    if vibe:
        feat = ms.style_features(vibe, st["value"], tones)
        record(s, "show", show_id, "style_features", feat, source=model_src, tier="inferred", method="rule+model", confidence=0.3,
               model_version=ms.STYLE_VERSION)
        res["style_vector"] = cal.write_style_vector(s, show_id, feat, cal.style_mean(s))

    if refine_enabled():   # Phase 1: never true (flag off, no refiners registered)
        res["refined"] = []
    res["seconds"] = round(time.perf_counter() - t0, 3)
    return res
