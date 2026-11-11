"""Embeddings + VectorIndex (sqlite-vec locally, pgvector in production behind the same interface).

Model choice - intfloat/multilingual-e5-small (118M params, 384-d, 100+ languages):
  * podcasts are multilingual and the shows we ingest are not English-only, so an English-only MiniLM is out;
  * bge-m3 / e5-large are better but 5-10x heavier (1024-d) for a gain we cannot yet measure on our own data;
  * e5-small runs in ~1-2 GB of GPU RAM, embeds a show in milliseconds on GPU, and is fine on CPU.
  A bigger model is a config change (INTEL_EMBED_MODEL); vectors are re-embedded when the stored model differs.
If the model cannot be loaded (offline), a deterministic hashing embedder is used and labelled as such.
"""
from __future__ import annotations

import hashlib
import math
import os
import re
import threading
import time
from typing import Protocol

os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

import numpy as np
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from .config import get_settings
from .models import Embedding
from .trust import budget


# ───────────────────────────── embedders ─────────────────────────────
class Embedder(Protocol):
    name: str
    version: str
    dim: int

    def embed(self, texts: list[str], kind: str = "passage") -> np.ndarray: ...


class HashEmbedder:
    name, version, dim = "hash-embed-v1", "1", 256

    def embed(self, texts: list[str], kind: str = "passage") -> np.ndarray:
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for i, t in enumerate(texts):
            toks = re.findall(r"\w+", t.lower())
            grams = toks + [f"{a}_{b}" for a, b in zip(toks, toks[1:])]
            for g in grams:
                h = int.from_bytes(hashlib.blake2b(g.encode(), digest_size=8).digest(), "little")
                out[i, h % self.dim] += 1.0 if (h >> 63) & 1 else -1.0
            from .linalg import norm
            n = norm(out[i])
            if n:
                out[i] /= n
        return out


class STEmbedder:
    def __init__(self, model_name: str):
        import sentence_transformers
        import torch
        self.name = model_name
        self.version = f"st-{sentence_transformers.__version__}"
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.model = sentence_transformers.SentenceTransformer(model_name, device=self.device)
        self.model.max_seq_length = 512
        getdim = getattr(self.model, "get_embedding_dimension", None) or self.model.get_sentence_embedding_dimension
        self.dim = int(getdim())
        self._e5 = "e5" in model_name.lower()
        self._lock = threading.Lock()       # one GPU job at a time; seed runs ingest from several threads

    def embed(self, texts: list[str], kind: str = "passage") -> np.ndarray:
        pre = f"{'query' if kind == 'query' else 'passage'}: " if self._e5 else ""
        with self._lock:
            v = self.model.encode([pre + t for t in texts], batch_size=32, normalize_embeddings=True, show_progress_bar=False)
        return np.asarray(v, dtype=np.float32)


_embedder: Embedder | None = None
_fallback_reason: str | None = None


class EmbedderUnavailable(RuntimeError):
    """The configured embedding model could not be loaded. Raised instead of silently switching models: vectors from
    two different models are not comparable, so a silent fallback would corrupt similarity, vibe calibration and topics."""


def get_embedder() -> Embedder:
    global _embedder, _fallback_reason
    if _embedder is None:
        name = get_settings().embed_model
        if name in ("hash", "hash-embed-v1"):
            _embedder = HashEmbedder()
        else:
            try:
                _embedder = STEmbedder(name)
            except Exception as exc:  # noqa: BLE001 - offline / missing weights / torch DLL problems
                _fallback_reason = f"{type(exc).__name__}: {exc}"[:300]
                if not os.environ.get("INTEL_EMBED_ALLOW_FALLBACK", "").lower() in ("1", "true", "yes"):
                    raise EmbedderUnavailable(f"could not load embedding model {name!r}: {_fallback_reason}. Set "
                                              "INTEL_EMBED_MODEL=hash for an offline test setup, or INTEL_EMBED_ALLOW_FALLBACK=true "
                                              "to accept the hash fallback knowingly.") from exc
                _embedder = HashEmbedder()
    return _embedder


def reset_embedder() -> None:
    global _embedder, _fallback_reason
    _embedder, _fallback_reason = None, None


def embedder_status() -> dict:
    try:
        e = get_embedder()
    except EmbedderUnavailable as exc:
        return {"configured": get_settings().embed_model, "active": None, "dim": None, "fallback_reason": str(exc)[:300], "error": True}
    return {"configured": get_settings().embed_model, "active": e.name, "dim": e.dim, "fallback_reason": _fallback_reason}


def to_blob(v: np.ndarray) -> bytes:
    return np.asarray(v, dtype=np.float32).tobytes()


def from_blob(b: bytes) -> np.ndarray:
    return np.frombuffer(b, dtype=np.float32)


# ───────────────────────────── vector index ─────────────────────────────
class VectorIndex(Protocol):
    def upsert(self, s: Session, space: str, emb_id: int, vec: np.ndarray) -> None: ...
    def query(self, s: Session, space: str, vec: np.ndarray, k: int) -> list[tuple[int, float]]: ...
    def delete(self, s: Session, space: str, emb_id: int) -> None: ...


def _ident(space: str, dim: int) -> str:
    assert re.fullmatch(r"[a-z]+", space)
    return f"vec_{space}_{int(dim)}"


class SqliteVecIndex:
    """One vec0 virtual table per (space, dim). Rowid == embeddings.id. Cosine distance; similarity = 1 - distance."""

    def _ensure(self, s: Session, space: str, dim: int) -> str:
        t = _ident(space, dim)
        s.execute(text(f"CREATE VIRTUAL TABLE IF NOT EXISTS {t} USING vec0(embedding float[{int(dim)}] distance_metric=cosine)"))
        return t

    def upsert(self, s: Session, space: str, emb_id: int, vec: np.ndarray) -> None:
        t = self._ensure(s, space, len(vec))
        s.execute(text(f"DELETE FROM {t} WHERE rowid = :i"), {"i": emb_id})
        s.execute(text(f"INSERT INTO {t}(rowid, embedding) VALUES (:i, :v)"), {"i": emb_id, "v": to_blob(vec)})

    def query(self, s: Session, space: str, vec: np.ndarray, k: int) -> list[tuple[int, float]]:
        t = self._ensure(s, space, len(vec))
        rows = s.execute(text(f"SELECT rowid, distance FROM {t} WHERE embedding MATCH :v AND k = :k ORDER BY distance"),
                         {"v": to_blob(vec), "k": k}).all()
        return [(int(r[0]), 1.0 - float(r[1])) for r in rows]

    def delete(self, s: Session, space: str, emb_id: int) -> None:
        for dim in {r[0] for r in s.execute(select(Embedding.dim).where(Embedding.id == emb_id)).all()}:
            s.execute(text(f"DELETE FROM {_ident(space, dim)} WHERE rowid = :i"), {"i": emb_id})


class PgVectorIndex:
    """Production backend (Postgres + pgvector). Same interface; selected with INTEL_VECTOR_BACKEND=pgvector.
    NOTE: written to pgvector's documented SQL, but NOT exercised in local tests (no Postgres here)."""

    def _ensure(self, s: Session, space: str, dim: int) -> str:
        t = _ident(space, dim)
        s.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        s.execute(text(f"CREATE TABLE IF NOT EXISTS {t} (id BIGINT PRIMARY KEY, embedding vector({int(dim)}))"))
        s.execute(text(f"CREATE INDEX IF NOT EXISTS {t}_hnsw ON {t} USING hnsw (embedding vector_cosine_ops)"))
        return t

    def upsert(self, s: Session, space: str, emb_id: int, vec: np.ndarray) -> None:
        t = self._ensure(s, space, len(vec))
        s.execute(text(f"INSERT INTO {t}(id, embedding) VALUES (:i, CAST(:v AS vector)) "
                       f"ON CONFLICT (id) DO UPDATE SET embedding = EXCLUDED.embedding"),
                  {"i": emb_id, "v": "[" + ",".join(f"{x:.6f}" for x in vec) + "]"})

    def query(self, s: Session, space: str, vec: np.ndarray, k: int) -> list[tuple[int, float]]:
        t = self._ensure(s, space, len(vec))
        rows = s.execute(text(f"SELECT id, 1 - (embedding <=> CAST(:v AS vector)) FROM {t} ORDER BY embedding <=> CAST(:v AS vector) LIMIT :k"),
                         {"v": "[" + ",".join(f"{x:.6f}" for x in vec) + "]", "k": k}).all()
        return [(int(r[0]), float(r[1])) for r in rows]

    def delete(self, s: Session, space: str, emb_id: int) -> None:
        for dim in {r[0] for r in s.execute(select(Embedding.dim).where(Embedding.id == emb_id)).all()}:
            s.execute(text(f"DELETE FROM {_ident(space, dim)} WHERE id = :i"), {"i": emb_id})


def get_index() -> VectorIndex:
    return PgVectorIndex() if get_settings().vector_backend == "pgvector" else SqliteVecIndex()


# ───────────────────────────── per-entity embedding ─────────────────────────────
def upsert_embedding(s: Session, entity_type: str, entity_id: str, space: str, content: str, *, podcast_id: str | None = None) -> str:
    """Embed `content` into `space` unless the stored vector is already for the same content + model.
    Returns 'cached' | 'embedded' | 'skipped_budget'. Cache hits are ledgered at zero cost."""
    emb = get_embedder()
    h = hashlib.sha256(content.encode()).hexdigest()
    row = s.scalar(select(Embedding).where(Embedding.entity_type == entity_type, Embedding.entity_id == entity_id, Embedding.space == space))
    if row is not None and row.content_hash == h and row.model == emb.name and row.model_version == emb.version:
        budget.charge(s, "embed", emb.name, 0, 0, podcast_id=podcast_id, cache_hit=True, note=f"{space} unchanged")
        return "cached"
    est = len(content) / 4 * 0.0001 * get_settings().cost_gpu_second  # tiny, but accounted for
    dec = budget.check(s, est, podcast_id=podcast_id)
    if not dec.ok:
        budget.skip(s, "embed", emb.name, dec.reason or "budget", podcast_id)
        return "skipped_budget"
    t0 = time.perf_counter()
    vec = emb.embed([content[:6000]])[0]
    secs = time.perf_counter() - t0
    budget.charge(s, "embed", emb.name, secs, get_settings().cost_gpu_second, podcast_id=podcast_id, note=f"{space} {len(content)} chars")
    if row is None:
        row = Embedding(entity_type=entity_type, entity_id=entity_id, space=space, model=emb.name, model_version=emb.version,
                        dim=emb.dim, content_hash=h, vector=to_blob(vec))
        s.add(row)
    else:
        get_index().delete(s, space, row.id)
        row.model, row.model_version, row.dim, row.content_hash, row.vector = emb.name, emb.version, emb.dim, h, to_blob(vec)
    s.flush()
    get_index().upsert(s, space, row.id, vec)
    return "embedded"


def embed_many(s: Session, entity_type: str, items: list[tuple[str, str]], space: str, *, podcast_id: str | None = None,
               index: bool = True) -> dict[str, np.ndarray]:
    """Batch version of upsert_embedding: cache hit per item (content hash + model), one GPU batch for the misses,
    one ledger row for the batch. Returns {entity_id: vector} for every item (cached or new)."""
    emb = get_embedder()
    out: dict[str, np.ndarray] = {}
    if not items:
        return out
    ids = [i for i, _ in items]
    rows = {r.entity_id: r for r in s.scalars(select(Embedding).where(Embedding.entity_type == entity_type, Embedding.space == space,
                                                                       Embedding.entity_id.in_(ids)))}
    todo: list[tuple[str, str, str]] = []
    for eid, content in items:
        h = hashlib.sha256(content.encode()).hexdigest()
        r = rows.get(eid)
        if r is not None and r.content_hash == h and r.model == emb.name and r.model_version == emb.version:
            out[eid] = from_blob(r.vector)
        else:
            todo.append((eid, content, h))
    if out:
        budget.charge(s, "embed", emb.name, 0, 0, podcast_id=podcast_id, cache_hit=True, note=f"{space} x{len(out)} unchanged")
    if not todo:
        return out
    est = sum(len(c) for _, c, _ in todo) / 4 * 0.0001 * get_settings().cost_gpu_second
    dec = budget.check(s, est, podcast_id=podcast_id)
    if not dec.ok:
        budget.skip(s, "embed", emb.name, dec.reason or "budget", podcast_id)
        return out
    t0 = time.perf_counter()
    vecs = emb.embed([c[:6000] for _, c, _ in todo])
    secs = time.perf_counter() - t0
    budget.charge(s, "embed", emb.name, secs, get_settings().cost_gpu_second, podcast_id=podcast_id, note=f"{space} batch x{len(todo)}")
    for (eid, _c, h), v in zip(todo, vecs):
        r = rows.get(eid)
        if r is None:
            r = Embedding(entity_type=entity_type, entity_id=eid, space=space, model=emb.name, model_version=emb.version,
                          dim=emb.dim, content_hash=h, vector=to_blob(v))
            s.add(r)
        else:
            if index:
                get_index().delete(s, space, r.id)
            r.model, r.model_version, r.dim, r.content_hash, r.vector = emb.name, emb.version, emb.dim, h, to_blob(v)
        s.flush()
        if index:
            get_index().upsert(s, space, r.id, v)
        out[eid] = np.asarray(v, dtype=np.float32)
    return out


def stored_vector(s: Session, entity_type: str, entity_id: str, space: str) -> np.ndarray | None:
    r = s.scalar(select(Embedding).where(Embedding.entity_type == entity_type, Embedding.entity_id == entity_id, Embedding.space == space))
    return from_blob(r.vector) if r is not None else None


_query_cache: dict[tuple[str, str], np.ndarray] = {}


def embed_queries(texts: list[str]) -> np.ndarray:
    """Embed fixed reference texts (vibe / topic descriptions) as e5 'query:' inputs. Cached per model in memory;
    these are tiny, constant inputs, so they are not ledgered per call."""
    emb = get_embedder()
    missing = [t for t in texts if (emb.name, t) not in _query_cache]
    if missing:
        for t, v in zip(missing, emb.embed(missing, kind="query")):
            _query_cache[(emb.name, t)] = np.asarray(v, dtype=np.float32)
    return np.stack([_query_cache[(emb.name, t)] for t in texts])


def similar(s: Session, entity_type: str, entity_id: str, space: str, k: int = 10) -> list[tuple[str, float]]:
    row = s.scalar(select(Embedding).where(Embedding.entity_type == entity_type, Embedding.entity_id == entity_id, Embedding.space == space))
    if row is None:
        return []
    hits = get_index().query(s, space, from_blob(row.vector), k + 1 + 5)
    ids = [i for i, _ in hits if i != row.id]
    meta = {e.id: e for e in s.scalars(select(Embedding).where(Embedding.id.in_(ids)))} if ids else {}
    return [(meta[i].entity_id, sim) for i, sim in hits if i in meta and meta[i].entity_type == entity_type][:k]


def reindex_all(s: Session) -> int:
    """Rebuild the derived index from the embeddings table (e.g. after changing backend)."""
    n = 0
    for row in s.scalars(select(Embedding)):
        get_index().upsert(s, row.space, row.id, from_blob(row.vector))
        n += 1
    return n


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    from .linalg import dot, norm
    d = norm(a) * norm(b)
    return dot(a, b) / d if d else math.nan
