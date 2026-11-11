"""Intelligence-store schema. Portable SQL types only (String/Integer/Float/JSON/DateTime/LargeBinary)."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (JSON, Boolean, CheckConstraint, DateTime, Float, ForeignKey, Index, Integer, LargeBinary,
                        String, Text, UniqueConstraint)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

UTC = timezone.utc


def now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)  # naive UTC everywhere (SQLite-safe)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class Base(DeclarativeBase):
    pass


SOURCE_KINDS = ("rss", "podcastindex", "taddy", "itunes", "creator", "llm", "manual")
DATA_TIERS = ("verified", "creator_provided", "estimated", "inferred")
METHODS = ("parsed", "api", "llm", "model", "rule", "manual")
JOB_STATUSES = ("queued", "running", "succeeded", "failed", "cancelled")


# ───────────────────────────── Trust spine ─────────────────────────────
class Source(Base):
    __tablename__ = "sources"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    kind: Mapped[str] = mapped_column(String(20))
    terms_note: Mapped[str | None] = mapped_column(Text, nullable=True)


class Provenance(Base):
    __tablename__ = "provenance"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(20))
    entity_id: Mapped[str] = mapped_column(String(40))
    field: Mapped[str] = mapped_column(String(60))
    value_json: Mapped[object] = mapped_column(JSON)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"))
    source_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    data_tier: Mapped[str] = mapped_column(String(20))
    method: Mapped[str] = mapped_column(String(10))
    model_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    superseded_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    __table_args__ = (
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_prov_conf"),
        CheckConstraint("data_tier IN ('verified','creator_provided','estimated','inferred')", name="ck_prov_tier"),
        Index("ix_prov_entity_field", "entity_type", "entity_id", "field"),
    )


class Evidence(Base):
    __tablename__ = "evidence"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(20))
    entity_id: Mapped[str] = mapped_column(String(40))
    kind: Mapped[str] = mapped_column(String(30))
    snippet: Mapped[str] = mapped_column(String(300))
    locator: Mapped[dict] = mapped_column(JSON, default=dict)  # {episode_id, timestamp|url}
    source_id: Mapped[int | None] = mapped_column(ForeignKey("sources.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    __table_args__ = (Index("ix_evidence_entity", "entity_type", "entity_id"),)


class CostLedger(Base):
    __tablename__ = "cost_ledger"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=now)
    operation: Mapped[str] = mapped_column(String(40))
    provider: Mapped[str] = mapped_column(String(60))
    units: Mapped[float] = mapped_column(Float, default=0)
    unit_cost_estimate: Mapped[float] = mapped_column(Float, default=0)
    cost_estimate_usd: Mapped[float] = mapped_column(Float, default=0)
    podcast_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    user_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    cache_hit: Mapped[bool] = mapped_column(Boolean, default=False)
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)


class Budget(Base):
    __tablename__ = "budgets"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scope: Mapped[str] = mapped_column(String(10))   # global|podcast|user|tier
    key: Mapped[str] = mapped_column(String(60))      # "*" = default applied to every key in scope
    period: Mapped[str] = mapped_column(String(10))   # day|month
    limit_usd: Mapped[float] = mapped_column(Float)
    used_usd: Mapped[float] = mapped_column(Float, default=0)
    period_start: Mapped[datetime] = mapped_column(DateTime, default=now)
    __table_args__ = (UniqueConstraint("scope", "key", "period", name="uq_budget"),)


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("job"))
    type: Mapped[str] = mapped_column(String(40))
    idempotency_key: Mapped[str] = mapped_column(String(300), unique=True)
    status: Mapped[str] = mapped_column(String(12), default="queued")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    checkpoint: Mapped[dict] = mapped_column(JSON, default=dict)   # completed stages (resume)
    run_after: Mapped[datetime] = mapped_column(DateTime, default=now)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)
    __table_args__ = (Index("ix_jobs_status", "status", "run_after"),)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=now)
    actor: Mapped[str] = mapped_column(String(60))
    action: Mapped[str] = mapped_column(String(60))
    entity_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    entity_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)


# ───────────────────────────── Domain: shows ─────────────────────────────
class Show(Base):
    __tablename__ = "shows"
    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("shw"))
    canonical_feed_url: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text, default="")
    language: Mapped[str | None] = mapped_column(String(10), nullable=True)
    activity: Mapped[str | None] = mapped_column(String(12), nullable=True)  # active|slowing|inactive
    merged_into: Mapped[str | None] = mapped_column(String(40), nullable=True)
    last_fetch_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_fetch_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    last_fetch_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    etag: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_modified: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)


class ShowAlias(Base):
    __tablename__ = "show_aliases"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    show_id: Mapped[str] = mapped_column(ForeignKey("shows.id"))
    kind: Mapped[str] = mapped_column(String(20))   # rss_url|podcastindex_id|itunes_id|guid
    value: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    __table_args__ = (UniqueConstraint("kind", "value", name="uq_alias"), Index("ix_alias_show", "show_id"))


class ShowClaim(Base):
    __tablename__ = "show_claims"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    show_id: Mapped[str] = mapped_column(ForeignKey("shows.id"))
    user_id: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    __table_args__ = (UniqueConstraint("show_id", "user_id", name="uq_claim"),)


class Episode(Base):
    __tablename__ = "episodes"
    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("ep"))
    show_id: Mapped[str] = mapped_column(ForeignKey("shows.id"))
    guid: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text, default="")
    description: Mapped[str] = mapped_column(Text, default="")   # sanitized
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duration_sec: Mapped[int | None] = mapped_column(Integer, nullable=True)
    explicit: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    language: Mapped[str | None] = mapped_column(String(10), nullable=True)
    audio_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    transcript_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    persons: Mapped[list] = mapped_column(JSON, default=list)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    removed: Mapped[bool] = mapped_column(Boolean, default=False)
    removed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    __table_args__ = (UniqueConstraint("show_id", "guid", name="uq_episode_guid"),
                      Index("ix_ep_show_pub", "show_id", "published_at"))


class Transcript(Base):
    __tablename__ = "transcripts"
    episode_id: Mapped[str] = mapped_column(ForeignKey("episodes.id"), primary_key=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    fmt: Mapped[str | None] = mapped_column(String(30), nullable=True)
    text: Mapped[str] = mapped_column(Text, default="")
    word_count: Mapped[int] = mapped_column(Integer, default=0)
    quality: Mapped[dict] = mapped_column(JSON, default=dict)
    origin: Mapped[str] = mapped_column(String(20), default="provided")   # provided|taddy|whisper
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class EnrichmentCache(Base):
    __tablename__ = "enrichment_cache"
    cache_key: Mapped[str] = mapped_column(String(64), primary_key=True)  # sha256(content_hash|prompt_version|model_version)
    show_id: Mapped[str] = mapped_column(String(40))
    output: Mapped[dict] = mapped_column(JSON)
    prompt_version: Mapped[str] = mapped_column(String(40))
    model_version: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Embedding(Base):
    """Source of truth for vectors. The vector index is derived and can always be rebuilt from here."""
    __tablename__ = "embeddings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(20))
    entity_id: Mapped[str] = mapped_column(String(60))
    space: Mapped[str] = mapped_column(String(20))   # content|style|chunks
    model: Mapped[str] = mapped_column(String(120))
    model_version: Mapped[str] = mapped_column(String(40))
    dim: Mapped[int] = mapped_column(Integer)
    content_hash: Mapped[str] = mapped_column(String(64))
    vector: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    __table_args__ = (UniqueConstraint("entity_type", "entity_id", "space", name="uq_embedding"),)


class AudienceUpload(Base):
    __tablename__ = "audience_uploads"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    show_id: Mapped[str] = mapped_column(String(40))
    user_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    filename: Mapped[str] = mapped_column(String(200))
    file_sha256: Mapped[str] = mapped_column(String(64))
    mapping: Mapped[dict] = mapped_column(JSON, default=dict)
    parsed: Mapped[dict] = mapped_column(JSON, default=dict)
    warnings: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class ConnectorRun(Base):
    """One row per connector call per show: which fields it actually returned (feeds the coverage matrix)."""
    __tablename__ = "connector_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=now)
    connector: Mapped[str] = mapped_column(String(30))
    show_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    ok: Mapped[bool] = mapped_column(Boolean, default=True)
    fields_returned: Mapped[list] = mapped_column(JSON, default=list)
    fields_expected: Mapped[list] = mapped_column(JSON, default=list)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Phase 1: per-feed failure diagnosis. target = the URL attempted (also for feeds that never became a show);
    # error_kind = dns|timeout|http_4xx|http_5xx|tls|invalid_xml|empty|too_large|ssrf_blocked|connection|redirects|other
    target: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_kind: Mapped[str | None] = mapped_column(String(30), nullable=True)
    __table_args__ = (Index("ix_runs_conn_show", "connector", "show_id"),)


# ───────────────────────────── Phase 1: calibration, caches, human labels ─────────────────────────────
class CorpusStat(Base):
    """Corpus-level statistics used by deterministic calibration (vibe z-scores, style-vector centering).
    Keyed by name + model, so stats computed for one embedding model are never applied to another."""
    __tablename__ = "corpus_stats"
    key: Mapped[str] = mapped_column(String(120), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON, default=dict)
    n: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)


class ApiCache(Base):
    """Response cache for keyless public APIs (iTunes Search) so repeated searches cost no requests."""
    __tablename__ = "api_cache"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)    # sha256(provider|url|params)
    provider: Mapped[str] = mapped_column(String(30))
    response: Mapped[dict] = mapped_column(JSON, default=dict)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class LabelItem(Base):
    """The fixed set of shows humans label (admin /admin/labels). Order is stable."""
    __tablename__ = "label_items"
    show_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    position: Mapped[int] = mapped_column(Integer)
    category: Mapped[str | None] = mapped_column(String(60), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class EvalLabel(Base):
    """One labeler's judgement of one show. Labels are evaluation data only: they never feed a profile."""
    __tablename__ = "eval_labels"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    show_id: Mapped[str] = mapped_column(String(40))
    labeler: Mapped[str] = mapped_column(String(80))
    topics: Mapped[list] = mapped_column(JSON, default=list)          # taxonomy topic ids
    vibes: Mapped[list] = mapped_column(JSON, default=list)           # exactly 3 of the 12 vibe terms
    style: Mapped[str] = mapped_column(String(30))
    guest_friendly: Mapped[bool] = mapped_column(Boolean)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)
    __table_args__ = (UniqueConstraint("show_id", "labeler", name="uq_label_show_labeler"),)
