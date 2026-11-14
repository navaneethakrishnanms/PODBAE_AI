"""Read-only view of the intelligence store for the engine.

`Corpus.load()` reads every live provenance row the engine uses in ONE query, resolves each (show, field) the same way the
profile does (tier priority verified > creator_provided > estimated > inferred, then newest, then most confident), and
keeps tier / confidence / freshness next to every value. Nothing here writes to the store and nothing is imputed: a
field that has no live value is simply absent."""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..intel.linalg import gram, mm, norm
from ..intel.models import Embedding, Episode, Evidence, Provenance, Show, ShowClaim, Source
from ..intel.trust.provenance import TIER_RANK, pick_key  # noqa: F401
from ..intel.understanding.model_signals import STYLE_VERSION
from ..intel.understanding.schemas import VIBE_TERMS
from ..intel.understanding.signals import STYLES, TONES
from ..intel.vectors import from_blob

ENGINE_FIELDS = [
    "title", "description", "image", "website", "contact_routes", "language", "categories", "declared_topics", "category_group", "topics",
    "activity_status", "cadence_days", "avg_episode_minutes", "last_published", "episode_count", "guest_friendliness",
    "guests_present", "conversational_style", "tone", "vibe", "brand_safety_flags", "style_features",
    "audience.totals", "audience.top_countries",
    "creator.goals", "creator.collaboration_openness", "creator.blocked_categories", "creator.blocked_brand_safety_flags",
    "creator.opportunity_opt_out", "owner_email_hash",
    "creator.blocked_brands", "creator.blocked_brand_categories", "creator.exclusive_categories",   # Layer 2 sponsor gates
]
EMAIL_RX = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


@dataclass(frozen=True)
class FieldVal:
    value: Any
    tier: str
    confidence: float
    fresh: bool
    method: str
    source: str
    provenance_id: int

    def src(self, field_name: str, side: str) -> dict:
        return {"field": field_name, "side": side, "tier": self.tier, "confidence": round(self.confidence, 3), "fresh": self.fresh,
                "method": self.method}


@dataclass
class ShowFeatures:
    show_id: str
    title: str
    activity: str | None
    fields: dict[str, FieldVal] = field(default_factory=dict)
    language_rows: list[FieldVal] = field(default_factory=list)
    text_chars: int | None = None          # description + stored episode descriptions (language-detection sample size)
    content_vec: np.ndarray | None = None
    is_member: bool = False
    member_user_id: str | None = None
    joined_at: datetime | None = None
    demo_member: bool = False

    def get(self, f: str) -> FieldVal | None:
        return self.fields.get(f)

    def val(self, f: str, default: Any = None) -> Any:
        fv = self.fields.get(f)
        return fv.value if fv is not None else default


def _fresh(p: Provenance, as_of: datetime) -> bool:
    return p.expires_at is None or p.expires_at > as_of


def unit(v: np.ndarray) -> np.ndarray:
    n = norm(v)
    return v / n if n else v


class Corpus:
    """Everything the engine needs, loaded once. Deterministic: shows are ordered by id."""

    def __init__(self, as_of: datetime):
        self.as_of = as_of
        self.shows: dict[str, ShowFeatures] = {}
        self.ids: list[str] = []
        self.content_ids: list[str] = []
        self.content_mat: np.ndarray | None = None
        self.content_index: dict[str, int] = {}
        self.pair_mean: float | None = None
        self.pair_std: float | None = None
        self.style_means: dict[bool, np.ndarray] = {}
        self._episodes: dict[str, list[Episode]] = {}
        self._evidence: dict[tuple[str, str], list[Evidence]] = {}

    # ───────────── loading ─────────────
    @classmethod
    def load(cls, s: Session, as_of: datetime) -> "Corpus":
        c = cls(as_of)
        for sh in s.scalars(select(Show).where(Show.merged_into.is_(None)).order_by(Show.id)):
            c.shows[sh.id] = ShowFeatures(sh.id, sh.title or "", sh.activity)
        c.ids = sorted(c.shows)
        from sqlalchemy import func as _f
        from ..intel.models import Episode as _E
        for sid, n in s.execute(select(_E.show_id, _f.sum(_f.length(_E.description))).group_by(_E.show_id)):
            if sid in c.shows:
                c.shows[sid].text_chars = int(n or 0)
        sources = {x.id: x.name for x in s.scalars(select(Source))}
        best: dict[tuple[str, str], Provenance] = {}
        from ..llm_refine import llm_active
        q = select(Provenance).where(Provenance.entity_type == "show", Provenance.superseded_by.is_(None),
                                     Provenance.field.in_(ENGINE_FIELDS))
        if not llm_active():                      # Phase 4 kill switch: LLM refinements are invisible -> exact Phase 3 inputs
            q = q.where(Provenance.method != "llm")
        rows = s.scalars(q.order_by(Provenance.id))
        for p in rows:
            sf = c.shows.get(p.entity_id)
            if sf is None:
                continue
            fv = FieldVal(p.value_json, p.data_tier, float(p.confidence), _fresh(p, as_of), p.method, sources.get(p.source_id, "?"), p.id)
            if p.field == "language":
                sf.language_rows.append(fv)
            key = (p.entity_id, p.field)
            cur = best.get(key)
            if cur is None or (*pick_key(p), p.id) < (*pick_key(cur), cur.id):
                best[key] = p
        for (sid, f), p in best.items():
            c.shows[sid].fields[f] = FieldVal(p.value_json, p.data_tier, float(p.confidence), _fresh(p, as_of), p.method,
                                              sources.get(p.source_id, "?"), p.id)
        for cl in s.scalars(select(ShowClaim).order_by(ShowClaim.created_at, ShowClaim.id)):
            sf = c.shows.get(cl.show_id)
            if sf is not None and not sf.is_member:
                sf.is_member, sf.member_user_id, sf.joined_at, sf.demo_member = True, cl.user_id, cl.created_at, bool(cl.demo)
        vecs: dict[str, np.ndarray] = {}
        for e in s.scalars(select(Embedding).where(Embedding.entity_type == "show", Embedding.space == "content")):
            if e.entity_id in c.shows:
                vecs[e.entity_id] = unit(from_blob(e.vector).astype(np.float64))
        c.content_ids = sorted(vecs)
        if c.content_ids:
            c.content_mat = np.stack([vecs[i] for i in c.content_ids])
            c.content_index = {sid: i for i, sid in enumerate(c.content_ids)}
            for sid in c.content_ids:
                c.shows[sid].content_vec = c.content_mat[c.content_index[sid]]
        c._pair_stats()
        c._style_means()
        return c

    def _pair_stats(self, max_n: int = 1500) -> None:
        """Mean / std of all pairwise content cosines (deterministic subsample above max_n shows)."""
        if self.content_mat is None or len(self.content_ids) < 3:
            return
        m = self.content_mat
        if len(m) > max_n:
            m = m[np.linspace(0, len(m) - 1, max_n).astype(int)]
        g = gram(m)
        iu = np.triu_indices(len(m), 1)
        vals = g[iu]
        self.pair_mean, self.pair_std = float(vals.mean()), float(vals.std()) or None
        self.pair_sorted = np.sort(vals)

    def percentile(self, cosine: float) -> int | None:
        """Share (0-100) of all show pairs in the corpus whose content cosine is below this one."""
        ps = getattr(self, "pair_sorted", None)
        if ps is None or not len(ps):
            return None
        return int(100 * np.searchsorted(ps, cosine, side="left") / len(ps))

    # ───────────── style vector (unknown style = missing, never a category) ─────────────
    @staticmethod
    def style_raw(feat: dict, with_style: bool) -> np.ndarray | None:
        if not feat or feat.get("version") != STYLE_VERSION:
            return None
        parts = list(feat.get("vibe") or []) + list(feat.get("tone") or [])
        if len(parts) != len(VIBE_TERMS) + len(TONES):
            return None
        if with_style:
            parts += list(feat.get("style") or [0.0] * len(STYLES))
        return unit(np.asarray(parts, dtype=np.float64))

    def _style_means(self) -> None:
        for with_style in (False, True):
            vs = []
            for sid in self.ids:
                sf = self.shows[sid]
                known = sf.val("conversational_style") not in (None, "unknown")
                if with_style and not known:
                    continue
                v = self.style_raw(sf.val("style_features") or {}, with_style)
                if v is not None:
                    vs.append(v)
            if len(vs) >= 20:
                self.style_means[with_style] = np.mean(np.stack(vs), axis=0)

    def style_vec(self, sid: str, with_style: bool) -> np.ndarray | None:
        v = self.style_raw(self.shows[sid].val("style_features") or {}, with_style)
        if v is None:
            return None
        mean = self.style_means.get(with_style)
        return unit(v - mean) if mean is not None else v

    # ───────────── content similarity ─────────────
    def content_sims(self, sid: str) -> dict[str, float]:
        """Cosine of `sid` against every show with a content vector (exact, deterministic)."""
        sf = self.shows.get(sid)
        if sf is None or sf.content_vec is None or self.content_mat is None:
            return {}
        sims = mm(self.content_mat, sf.content_vec)
        return {o: float(sims[i]) for i, o in enumerate(self.content_ids)}

    def cos(self, a: str, b: str) -> float | None:
        va, vb = self.shows[a].content_vec, self.shows[b].content_vec
        if va is None or vb is None:
            return None
        from ..intel.linalg import dot
        return dot(va, vb)

    def z(self, cosine: float) -> float | None:
        if self.pair_mean is None or not self.pair_std:
            return None
        return (cosine - self.pair_mean) / self.pair_std

    # ───────────── lazily loaded per-show detail (why-now, evidence) ─────────────
    def episodes(self, s: Session, sid: str, limit: int = 40) -> list[Episode]:
        if sid not in self._episodes:
            self._episodes[sid] = list(s.scalars(select(Episode).where(Episode.show_id == sid, Episode.removed.is_(False),
                                                                       Episode.published_at.is_not(None))
                                                 .order_by(Episode.published_at.desc(), Episode.id).limit(limit)))
        return self._episodes[sid]

    def evidence(self, s: Session, sid: str, kind: str) -> list[Evidence]:
        key = (sid, kind)
        if key not in self._evidence:
            self._evidence[key] = list(s.scalars(select(Evidence).where(Evidence.entity_type == "show", Evidence.entity_id == sid,
                                                                        Evidence.kind == kind).order_by(Evidence.id)))
        return self._evidence[key]


def days_between(a: datetime, b: datetime) -> float:
    return (a - b).total_seconds() / 86400.0


def parse_iso(v: Any) -> datetime | None:
    if not isinstance(v, str):
        return None
    try:
        d = datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        return None
    return d.replace(tzinfo=None) if d.tzinfo else d


def redact(text: str | None) -> str:
    """Never show or derive e-mails: strip anything that looks like an address from text we display."""
    return EMAIL_RX.sub("[email removed]", text or "")


def finite(x: Any) -> float | None:
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None
