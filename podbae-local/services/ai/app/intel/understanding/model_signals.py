"""Model-backed signals (local multilingual-e5-small embeddings; NO LLM). Pure numpy functions; the DB glue is in
understanding/pipeline.py and the corpus statistics are in calibration.py.

  embedding_topics()  episode / description text vs taxonomy topic descriptions. An episode supports a topic only if
                      that topic is its clear #1 (z-score across all topics >= TOPIC_Z and ahead of #2 by TOPIC_MARGIN).
                      The same evidence rule as lexicon topics then applies (>= 2 episodes, or description + 1 episode).
  vibe_raw()          similarity of show text (content vector + mean of episode vectors) to each vibe description.
  vibe_scores()       corpus z-score per vibe term -> normal CDF -> 0..1 (calibrated). Without corpus stats it falls back
                      to a within-show z-score and says so (lower confidence).
  style_features() / style_vector()  numeric style vector: 12 vibe scores + one-hot conversational style + multi-hot
                      tone, L2-normalised; similarity = cosine after mean-centring across the corpus (Step 5).
"""
from __future__ import annotations

import math
from functools import lru_cache
from pathlib import Path

import numpy as np

from ..linalg import mm, norm
import yaml

from .schemas import VIBE_TERMS
from .signals import STYLES, TONES, TopicSupport, taxonomy

HERE = Path(__file__).parent
TOPIC_Z = 2.5            # how far above the show's average topic similarity the #1 topic must be
TOPIC_MARGIN = 0.012     # and by how much (raw cosine) it must beat the #2 topic
STYLE_VERSION = "style-numeric-v1"


@lru_cache(maxsize=1)
def vibe_descriptions() -> tuple[str, dict[str, str]]:
    d = yaml.safe_load((HERE / "vibes.yaml").read_text(encoding="utf-8"))
    return d["version"], {t: d["terms"][t] for t in VIBE_TERMS}


def topic_ids() -> list[str]:
    return list(taxonomy())


def topic_texts() -> list[str]:
    tax = taxonomy()
    return [f"a podcast about {tax[t]['description']}" for t in topic_ids()]


def _z(row: np.ndarray) -> np.ndarray:
    sd = float(row.std())
    return (row - row.mean()) / sd if sd > 1e-9 else np.zeros_like(row)


def embedding_topics(desc_vec: np.ndarray | None, ep_vecs: list[tuple[str, str, np.ndarray]], topic_mat: np.ndarray,
                     desc_text: str = "") -> dict[str, TopicSupport]:
    """ep_vecs = [(episode_id, title, vector)]. Returns supports keyed by topic id (basis 'model')."""
    ids = topic_ids()
    out: dict[str, TopicSupport] = {}

    def winner(v: np.ndarray) -> int | None:
        sims = mm(topic_mat, v)
        order = np.argsort(-sims)
        z = _z(sims)
        b, b2 = int(order[0]), int(order[1])
        return b if z[b] >= TOPIC_Z and sims[b] - sims[b2] >= TOPIC_MARGIN else None

    if desc_vec is not None:
        w = winner(desc_vec)
        if w is not None:
            out.setdefault(ids[w], TopicSupport(ids[w], basis={"model"})).desc = (desc_text or "")[:300] or "(show description)"
    for eid, title, v in ep_vecs:
        w = winner(v)
        if w is not None:
            out.setdefault(ids[w], TopicSupport(ids[w], basis={"model"})).episodes.append((eid, title[:300]))
    return out


def vibe_raw(content_vec: np.ndarray | None, ep_vecs: list[np.ndarray], vibe_mat: np.ndarray) -> list[float] | None:
    parts = []
    if content_vec is not None:
        parts.append(mm(vibe_mat, content_vec))
    if ep_vecs:
        parts.append(np.mean(np.stack([mm(vibe_mat, v) for v in ep_vecs]), axis=0))
    if not parts:
        return None
    return [round(float(x), 6) for x in np.mean(np.stack(parts), axis=0)]


def _cdf(z: float) -> float:
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def vibe_scores(raw: list[float], stats: dict | None) -> tuple[dict[str, float], str]:
    """Returns ({term: 0..1}, calibration_mode). mode 'corpus' = z vs the corpus mean/std of that term (comparable
    across shows); 'within_show' = z across this show's 12 terms only (ranks terms, not comparable across shows)."""
    r = np.asarray(raw, dtype=np.float64)
    if stats and stats.get("std") and len(stats["std"]) == len(r):
        mu, sd = np.asarray(stats["mean"]), np.maximum(np.asarray(stats["std"]), 1e-6)
        z, mode = (r - mu) / sd, "corpus"
    else:
        z, mode = _z(r), "within_show"
    return {t: round(_cdf(float(x)), 3) for t, x in zip(VIBE_TERMS, z)}, mode


def style_features(vibe: dict[str, float] | None, style: str | None, tones: list[str] | None) -> dict:
    return {"vibe": [round(float((vibe or {}).get(t, 0.0)), 4) for t in VIBE_TERMS],
            "style": [1.0 if style == s else 0.0 for s in STYLES],
            "tone": [1.0 if t in (tones or []) else 0.0 for t in TONES], "version": STYLE_VERSION}


def raw_style_vector(feat: dict) -> np.ndarray:
    v = np.asarray(feat["vibe"] + feat["style"] + feat["tone"], dtype=np.float32)
    n = norm(v)
    return v / n if n else v


def style_vector(feat: dict, mean: list[float] | None) -> np.ndarray:
    """L2-normalised features, centred on the corpus mean, re-normalised (so cosine = centred cosine)."""
    v = raw_style_vector(feat)
    if mean is not None and len(mean) == len(v):
        v = v - np.asarray(mean, dtype=np.float32)
    n = norm(v)
    return (v / n if n else v).astype(np.float32)


def style_dim() -> int:
    return len(VIBE_TERMS) + len(STYLES) + len(TONES)
