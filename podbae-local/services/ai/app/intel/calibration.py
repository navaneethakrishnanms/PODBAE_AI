"""Corpus calibration (deterministic, no LLM). Two statistics, both keyed by embedding model + version so stats from one
model are never applied to another:

  vibe:<model>:<vibe-version>     per-term mean/std of raw vibe similarity across all shows -> vibe z-scores
  style_mean:<style-version>       mean of L2-normalised style feature vectors -> centred cosine for style similarity

recalibrate() recomputes both from the store, rewrites every show's vibe (new provenance rows; history kept) and its
style vector, and rebuilds the style index. It runs after a seed and from POST /v1/admin/recalibrate."""
from __future__ import annotations

import hashlib

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import CorpusStat, Embedding, Provenance, Show, now
from .trust.audit import audit
from .trust.provenance import get_source, live_rows, record
from .understanding.model_signals import STYLE_VERSION, raw_style_vector, style_features, style_vector, vibe_descriptions, vibe_scores
from .vectors import get_embedder, get_index, to_blob

MIN_CORPUS = 20


def vibe_key() -> str:
    return f"vibe:{get_embedder().name}:{vibe_descriptions()[0]}"


def style_key() -> str:
    return f"style_mean:{STYLE_VERSION}"


def get_stat(s: Session, key: str) -> CorpusStat | None:
    return s.get(CorpusStat, key)


def vibe_stats(s: Session) -> dict | None:
    st = get_stat(s, vibe_key())
    return st.value if st is not None and st.n >= MIN_CORPUS else None


def style_mean(s: Session) -> list[float] | None:
    st = get_stat(s, style_key())
    return st.value.get("mean") if st is not None and st.n >= MIN_CORPUS else None


def _put(s: Session, key: str, value: dict, n: int) -> None:
    st = s.get(CorpusStat, key)
    if st is None:
        s.add(CorpusStat(key=key, value=value, n=n, updated_at=now()))
    else:
        st.value, st.n, st.updated_at = value, n, now()
    s.flush()


def _live(s: Session, sid: str, field: str):
    rows = live_rows(s, "show", sid, field)
    return rows[0].value_json if rows else None


def write_style_vector(s: Session, show_id: str, feat: dict, mean: list[float] | None) -> str:
    """Store the centred style vector in embeddings(space='style') + the vector index. Idempotent."""
    vec = style_vector(feat, mean)
    h = hashlib.sha256(vec.tobytes()).hexdigest()
    row = s.scalar(select(Embedding).where(Embedding.entity_type == "show", Embedding.entity_id == show_id, Embedding.space == "style"))
    if row is not None and row.content_hash == h and row.model == STYLE_VERSION:
        return "cached"
    if row is None:
        row = Embedding(entity_type="show", entity_id=show_id, space="style", model=STYLE_VERSION, model_version="1", dim=len(vec),
                        content_hash=h, vector=to_blob(vec))
        s.add(row)
    else:
        get_index().delete(s, "style", row.id)
        row.model, row.model_version, row.dim, row.content_hash, row.vector = STYLE_VERSION, "1", len(vec), h, to_blob(vec)
    s.flush()
    get_index().upsert(s, "style", row.id, vec)
    return "embedded"


def recalibrate(s: Session) -> dict:
    roots = [sh.id for sh in s.scalars(select(Show).where(Show.merged_into.is_(None)))]
    raws = {sid: r for sid in roots if (r := _live(s, sid, "vibe_similarity"))}
    out: dict = {"shows": len(roots), "with_vibe": len(raws)}
    if len(raws) < MIN_CORPUS:
        out["skipped"] = f"need >= {MIN_CORPUS} shows with vibe similarities, have {len(raws)}"
        return out
    mat = np.asarray([r["raw"] for r in raws.values()], dtype=np.float64)
    vstats = {"mean": mat.mean(axis=0).round(6).tolist(), "std": mat.std(axis=0).round(6).tolist(), "model": get_embedder().name}
    _put(s, vibe_key(), vstats, len(raws))
    src = get_source(s, "local-model:e5", "local_model", "Local multilingual-e5-small embeddings; inferred, not measured")
    changed = 0
    for sid, r in raws.items():
        scores, mode = vibe_scores(r["raw"], vstats)
        prev = _live(s, sid, "vibe")
        record(s, "show", sid, "vibe", scores, source=src, tier="inferred", method="model",
               confidence=0.35 if r.get("episodes", 0) >= 3 else 0.25, model_version=f"{get_embedder().name}/{vibe_descriptions()[0]}/{mode}",
               source_ref=f"corpus z-score over {len(raws)} shows")
        changed += int(prev != scores)
    # style: features from the live calibrated vibe + style + tone, mean-centred
    feats = {}
    for sid in roots:
        vibe, style, tone = _live(s, sid, "vibe"), _live(s, sid, "conversational_style"), _live(s, sid, "tone")
        if vibe:
            feats[sid] = style_features(vibe, style, list((tone or {}) if isinstance(tone, dict) else (tone or [])))
    if feats:
        mean = np.mean(np.stack([raw_style_vector(f) for f in feats.values()]), axis=0).round(6).tolist()
        _put(s, style_key(), {"mean": mean}, len(feats))
        for sid, f in feats.items():
            record(s, "show", sid, "style_features", f, source=src, tier="inferred", method="rule+model", confidence=0.3,
                   model_version=STYLE_VERSION)
            write_style_vector(s, sid, f, mean if len(feats) >= MIN_CORPUS else None)
    out.update({"vibe_stats_n": len(raws), "vibe_changed": changed, "style_vectors": len(feats)})
    audit(s, "calibration", "recalibrate", None, None, out)
    return out


def needs_recalibration(s: Session) -> bool:
    n = s.scalar(select(Provenance.id).where(Provenance.field == "vibe_similarity").limit(1))
    if n is None:
        return False
    total = len(list(s.scalars(select(Show.id).where(Show.merged_into.is_(None)))))
    st = get_stat(s, vibe_key())
    return total >= MIN_CORPUS and (st is None or total >= 1.1 * st.n)
