"""Blind pair labels: engine vs legacy.

For 20 member shows we freeze the engine's top 5 (qualified only: the engine never pads) and the legacy scorer's top 5,
and show labelers the UNION in a seeded random order without saying which system produced which pair. Each labeler rates
each pair good / ok / bad. Labels are stored per labeler; 2+ labelers -> agreement (Cohen's kappa, % exact agreement).

Metrics (computed per system on its own frozen list, gains good=2, ok=1, bad=0, mean over labelers):
  Precision@3  share of the system's top-3 slots holding a pair rated 'good' (an empty slot counts as not good)
  nDCG@5       DCG of the system's top 5 over the ideal DCG of all labelled pairs for that member show
  Coverage@3   share of member shows where the system returned 3 pairs and all 3 are rated ok or better"""
from __future__ import annotations

import hashlib
import math
import random
import re
from itertools import combinations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..intel.labels import cohen_kappa
from ..intel.models import Episode, Show, ShowClaim, now
from . import legacy
from .config import get_config
from .engine import compute, load_history
from .features import Corpus, redact
from .models import PairLabel, PairLabelItem

RATINGS = ("good", "ok", "bad")
GAIN = {"good": 2.0, "ok": 1.0, "bad": 0.0}
LABELER_RX = re.compile(r"^[\w .@'-]{1,80}$")
EXCLUDED = {"claude-draft", "claude"}


class PairLabelError(ValueError):
    pass


def pick_items(s: Session, n: int = 20, replace: bool = False) -> list[str]:
    if not replace and s.scalar(select(func.count()).select_from(PairLabelItem)):
        return [i.member_show_id for i in s.scalars(select(PairLabelItem).order_by(PairLabelItem.position))]
    if replace:
        for it in s.scalars(select(PairLabelItem)):
            s.delete(it)
        s.flush()
    cfg = get_config()
    corpus = Corpus.load(s, now())
    members = sorted({c.show_id for c in s.scalars(select(ShowClaim)) if c.show_id in corpus.shows})
    chosen = list(members[:n])
    if len(chosen) < n:     # fill with a deterministic, group-stratified sample of non-member shows (hypothetical members)
        by_group: dict[str, list[str]] = {}
        for sid in corpus.ids:
            if sid in chosen or corpus.shows[sid].content_vec is None:
                continue
            g = (corpus.shows[sid].val("category_group") or ["?"])[0]
            by_group.setdefault(g, []).append(sid)
        rng = random.Random(23)
        for g in by_group:
            rng.shuffle(by_group[g])
        groups = sorted(by_group)
        while len(chosen) < n and any(by_group.values()):
            for g in groups:
                if by_group[g] and len(chosen) < n:
                    chosen.append(by_group[g].pop())
    for pos, sid in enumerate(chosen):
        res = compute(s, corpus, sid, cfg, load_history(s, sid, cfg), {})
        eng = [r["target_show_id"] for r in res["qualified"][:5]]
        leg = [r["target_show_id"] for r in legacy.rank(corpus, sid, 5)]
        s.add(PairLabelItem(member_show_id=sid, position=pos, engine_top=eng, legacy_top=leg, scoring_version=cfg["scoring_version"]))
    s.flush()
    return chosen


def _show_card(s: Session, sid: str) -> dict:
    from ..intel.trust.provenance import live_rows
    sh = s.get(Show, sid)

    def val(f):
        rows = live_rows(s, "show", sid, f)
        return rows[0].value_json if rows else None
    eps = list(s.scalars(select(Episode).where(Episode.show_id == sid, Episode.removed.is_(False))
                         .order_by(Episode.published_at.desc()).limit(6)))
    return {"show_id": sid, "title": sh.title if sh else sid, "description": redact(str(val("description") or ""))[:500],
            "categories": val("categories") or [], "language": sh.language if sh else None,
            "episodes": [redact(e.title)[:160] for e in eps]}


def queue(s: Session, labeler: str | None) -> dict:
    items = []
    mine = {}
    if labeler:
        mine = {(l.member_show_id, l.candidate_show_id): l.rating for l in s.scalars(select(PairLabel).where(PairLabel.labeler == labeler))}
    for it in s.scalars(select(PairLabelItem).order_by(PairLabelItem.position)):
        pool = sorted(set(it.engine_top) | set(it.legacy_top))
        seed = int(hashlib.sha256(it.member_show_id.encode()).hexdigest()[:8], 16)
        random.Random(seed).shuffle(pool)
        items.append({"member": _show_card(s, it.member_show_id), "position": it.position,
                      "pairs": [{"candidate": _show_card(s, c), "rating": mine.get((it.member_show_id, c))} for c in pool]})
    done = sum(1 for i in items for p in i["pairs"] if p["rating"])
    total = sum(len(i["pairs"]) for i in items)
    return {"items": items, "done": done, "total": total, "ratings": list(RATINGS),
            "instructions": "Would these two shows make good cross-promo / guest-swap partners? good = I would recommend this pair; "
                            "ok = plausible but not exciting; bad = poor fit. You are not told which system suggested a pair."}


def save(s: Session, member_show_id: str, candidate_show_id: str, labeler: str, rating: str, note: str | None = None) -> dict:
    lab = (labeler or "").strip()
    if not LABELER_RX.match(lab) or lab.lower() in EXCLUDED:
        raise PairLabelError("invalid labeler name (machine-written labels are not accepted)")
    if rating not in RATINGS:
        raise PairLabelError(f"rating must be one of {RATINGS}")
    it = s.get(PairLabelItem, member_show_id)
    if it is None or candidate_show_id not in set(it.engine_top) | set(it.legacy_top):
        raise PairLabelError("that pair is not in the label set")
    row = s.scalar(select(PairLabel).where(PairLabel.member_show_id == member_show_id, PairLabel.candidate_show_id == candidate_show_id,
                                           PairLabel.labeler == lab))
    if row is None:
        row = PairLabel(member_show_id=member_show_id, candidate_show_id=candidate_show_id, labeler=lab, rating=rating, note=note)
        s.add(row)
    else:
        row.rating, row.note, row.updated_at = rating, note, now()
    s.flush()
    return {"member_show_id": member_show_id, "candidate_show_id": candidate_show_id, "labeler": lab, "rating": rating}


def _labels(s: Session) -> list[PairLabel]:
    return [l for l in s.scalars(select(PairLabel)) if l.labeler.lower() not in EXCLUDED]


def agreement(s: Session) -> dict:
    by: dict[str, dict[tuple[str, str], str]] = {}
    for l in _labels(s):
        by.setdefault(l.labeler, {})[(l.member_show_id, l.candidate_show_id)] = l.rating
    out = {"labelers": [{"labeler": k, "labelled": len(v)} for k, v in sorted(by.items())], "pairs": []}
    if len(by) < 2:
        out.update(status="not_available", message=f"Agreement needs at least 2 labelers on the same pairs (currently {len(by)}).")
        return out
    for a, b in combinations(sorted(by), 2):
        keys = sorted(set(by[a]) & set(by[b]))
        if not keys:
            continue
        xa, xb = [by[a][k] for k in keys], [by[b][k] for k in keys]
        out["pairs"].append({"a": a, "b": b, "shared": len(keys), "exact_agreement": round(sum(x == y for x, y in zip(xa, xb)) / len(keys), 3),
                             "kappa": cohen_kappa(xa, xb)})
    out["status"] = "ok" if out["pairs"] else "not_available"
    if not out["pairs"]:
        out["message"] = "Labelers have not rated any of the same pairs yet."
    return out


def _dcg(gains: list[float]) -> float:
    return sum(g / math.log2(i + 2) for i, g in enumerate(gains))


def metrics(s: Session) -> dict:
    gains: dict[tuple[str, str], list[float]] = {}
    for l in _labels(s):
        gains.setdefault((l.member_show_id, l.candidate_show_id), []).append(GAIN[l.rating])
    g = {k: sum(v) / len(v) for k, v in gains.items()}
    items = list(s.scalars(select(PairLabelItem).order_by(PairLabelItem.position)))
    res: dict[str, dict] = {}
    for system, attr in (("engine", "engine_top"), ("legacy", "legacy_top")):
        p3, nd, cov, n = [], [], [], 0
        for it in items:
            lst = getattr(it, attr)
            pool = set(it.engine_top) | set(it.legacy_top)
            if not any((it.member_show_id, c) in g for c in pool):
                continue
            n += 1
            gl = [g.get((it.member_show_id, c)) for c in lst]
            p3.append(sum(1 for x in gl[:3] if x is not None and x >= 1.5) / 3)
            ideal = sorted((g[(it.member_show_id, c)] for c in pool if (it.member_show_id, c) in g), reverse=True)[:5]
            idcg = _dcg(ideal)
            nd.append(_dcg([x or 0.0 for x in gl[:5]]) / idcg if idcg else 0.0)
            cov.append(1.0 if len(gl) >= 3 and all(x is not None and x >= 1.0 for x in gl[:3]) else 0.0)
        res[system] = {"member_shows_labelled": n, "precision_at_3": round(sum(p3) / n, 3) if n else None,
                       "ndcg_at_5": round(sum(nd) / n, 3) if n else None, "coverage_at_3": round(sum(cov) / n, 3) if n else None,
                       "avg_list_length": round(sum(len(getattr(it, attr)) for it in items) / len(items), 2) if items else None}
    labelers = sorted({l.labeler for l in _labels(s)})
    return {"labelers": labelers, "labelled_pairs": len(g), "items": len(items), "systems": res,
            "note": None if g else "No human pair labels yet: engine and legacy quality are UNMEASURED."}
