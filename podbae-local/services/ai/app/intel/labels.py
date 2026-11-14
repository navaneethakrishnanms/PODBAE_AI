"""Human evaluation labels (Step 7). Labels are evaluation data only; they never feed a profile.

- pick_label_set(): 30 shows, stratified across category groups, deterministic, stored in label_items.
- save_label(): one row per (show, labeler); 2+ labelers supported.
- agreement(): Cohen's kappa (style, guest-friendly) and mean Jaccard (topics, vibe top-3) for every labeler pair.
Claude-written draft labels (eval/labels.yaml, labeler 'claude-draft') are never stored here and never scored."""
from __future__ import annotations

import random
import re
from itertools import combinations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import Episode, EvalLabel, LabelItem, Show, now
from .trust.provenance import live_rows
from .understanding.schemas import VIBE_TERMS
from .understanding.signals import STYLES, taxonomy

LABEL_STYLES = STYLES + ["mixed_or_other"]
EXCLUDED_LABELERS = {"claude-draft"}
LABELER_RX = re.compile(r"^[\w .@'-]{1,80}$")


class LabelError(ValueError):
    pass


def _val(s: Session, sid: str, f: str):
    from .trust.provenance import pick_key
    rows = sorted(live_rows(s, "show", sid, f), key=pick_key)
    return rows[0].value_json if rows else None


def pick_label_set(s: Session, n: int = 30, seed: int = 11, replace: bool = False) -> list[str]:
    """Stratified deterministic sample of shows with >= 5 episodes and a real description, round-robin over groups."""
    if not replace and s.scalar(select(func.count()).select_from(LabelItem)):
        return [i.show_id for i in s.scalars(select(LabelItem).order_by(LabelItem.position))]
    rows: list[tuple[str, str]] = []
    for sh in s.scalars(select(Show).where(Show.merged_into.is_(None)).order_by(Show.id)):
        n_eps = s.scalar(select(func.count()).select_from(Episode).where(Episode.show_id == sh.id, Episode.removed.is_(False))) or 0
        if n_eps >= 5 and len(_val(s, sh.id, "description") or "") >= 80:
            grp = (_val(s, sh.id, "category_group") or ["Other"])
            rows.append((sh.id, grp[0] if grp else "Other"))
    random.Random(seed).shuffle(rows)
    by: dict[str, list[str]] = {}
    for sid, g in rows:
        by.setdefault(g, []).append(sid)
    out: list[tuple[str, str]] = []
    while len(out) < n and any(by.values()):
        for g in sorted(by):
            if by[g] and len(out) < n:
                out.append((by[g].pop(), g))
    if replace:
        for it in s.scalars(select(LabelItem)):
            s.delete(it)
        s.flush()
    for i, (sid, g) in enumerate(out):
        s.add(LabelItem(show_id=sid, position=i, category=g))
    s.flush()
    return [sid for sid, _ in out]


def item_view(s: Session, it: LabelItem, labeler: str | None) -> dict:
    sh = s.get(Show, it.show_id)
    eps = list(s.scalars(select(Episode).where(Episode.show_id == it.show_id, Episode.removed.is_(False))
                         .order_by(Episode.published_at.desc()).limit(10)))
    lab = s.scalar(select(EvalLabel).where(EvalLabel.show_id == it.show_id, EvalLabel.labeler == labeler)) if labeler else None
    return {"show_id": it.show_id, "position": it.position, "category": it.category, "title": sh.title if sh else "(missing)",
            "description": (_val(s, it.show_id, "description") or "")[:1500], "categories": _val(s, it.show_id, "categories") or [],
            "feed_url": sh.canonical_feed_url if sh else None,
            "episodes": [{"title": e.title, "published_at": e.published_at.isoformat() + "Z" if e.published_at else None,
                          "description": (e.description or "")[:280]} for e in eps],
            "label": label_dict(lab) if lab else None}


def label_dict(l: EvalLabel) -> dict:
    return {"show_id": l.show_id, "labeler": l.labeler, "topics": l.topics, "vibes": l.vibes, "style": l.style,
            "guest_friendly": l.guest_friendly, "notes": l.notes, "updated_at": l.updated_at.isoformat() + "Z"}


def save_label(s: Session, show_id: str, labeler: str, topics: list[str], vibes: list[str], style: str, guest_friendly: bool,
               notes: str | None = None) -> EvalLabel:
    labeler = (labeler or "").strip()
    if not LABELER_RX.match(labeler):
        raise LabelError("labeler name: 1-80 letters, digits, spaces or . @ ' -")
    if labeler.lower() in EXCLUDED_LABELERS:
        raise LabelError("'claude-draft' is reserved for machine-written drafts and is never a human labeler")
    if s.get(LabelItem, show_id) is None:
        raise LabelError("show is not in the label set")
    bad = [t for t in topics if t not in taxonomy()]
    if bad or not 1 <= len(topics) <= 5:
        raise LabelError(f"pick 1-5 topics from the taxonomy (unknown: {bad})" if bad else "pick 1-5 topics")
    if len(set(vibes)) != 3 or any(v not in VIBE_TERMS for v in vibes):
        raise LabelError("pick exactly 3 different vibes from the 12-term vocabulary")
    if style not in LABEL_STYLES:
        raise LabelError(f"style must be one of {LABEL_STYLES}")
    row = s.scalar(select(EvalLabel).where(EvalLabel.show_id == show_id, EvalLabel.labeler == labeler))
    if row is None:
        row = EvalLabel(show_id=show_id, labeler=labeler, topics=topics, vibes=vibes, style=style, guest_friendly=bool(guest_friendly), notes=notes)
        s.add(row)
    else:
        row.topics, row.vibes, row.style, row.guest_friendly, row.notes, row.updated_at = topics, vibes, style, bool(guest_friendly), notes, now()
    s.flush()
    return row


def human_labels(s: Session) -> list[EvalLabel]:
    return [l for l in s.scalars(select(EvalLabel)) if l.labeler.lower() not in EXCLUDED_LABELERS]


def cohen_kappa(a: list, b: list) -> float | None:
    n = len(a)
    if n == 0:
        return None
    po = sum(x == y for x, y in zip(a, b)) / n
    cats = set(a) | set(b)
    pe = sum((a.count(c) / n) * (b.count(c) / n) for c in cats)
    return round((po - pe) / (1 - pe), 3) if pe < 1 else (1.0 if po == 1 else 0.0)


def jaccard(a, b) -> float:
    a, b = set(a), set(b)
    return 1.0 if not a and not b else len(a & b) / len(a | b)


def agreement(s: Session) -> dict:
    labs = human_labels(s)
    by: dict[str, dict[str, EvalLabel]] = {}
    for l in labs:
        by.setdefault(l.labeler, {})[l.show_id] = l
    labelers = sorted(by)
    total = s.scalar(select(func.count()).select_from(LabelItem)) or 0
    out = {"labelers": [{"labeler": k, "labelled": len(v), "of": total} for k, v in by.items()], "pairs": []}
    if len(labelers) < 2:
        out["status"] = "not_available"
        out["message"] = ("Inter-labeler agreement needs at least 2 human labelers on the same shows. "
                          f"Currently {len(labelers)} labeler(s).")
        return out
    for x, y in combinations(labelers, 2):
        shared = sorted(set(by[x]) & set(by[y]))
        if not shared:
            out["pairs"].append({"a": x, "b": y, "shared": 0})
            continue
        A, B = [by[x][i] for i in shared], [by[y][i] for i in shared]
        out["pairs"].append({
            "a": x, "b": y, "shared": len(shared),
            "style_kappa": cohen_kappa([l.style for l in A], [l.style for l in B]),
            "guest_kappa": cohen_kappa([l.guest_friendly for l in A], [l.guest_friendly for l in B]),
            "topics_jaccard": round(sum(jaccard(p.topics, q.topics) for p, q in zip(A, B)) / len(shared), 3),
            "topic_groups_jaccard": round(sum(jaccard({taxonomy()[t]["group"] for t in p.topics}, {taxonomy()[t]["group"] for t in q.topics})
                                              for p, q in zip(A, B)) / len(shared), 3),
            "vibes_jaccard": round(sum(jaccard(p.vibes, q.vibes) for p, q in zip(A, B)) / len(shared), 3)})
    out["status"] = "ok"
    return out
