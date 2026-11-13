"""Opportunity Engine tables, stored in the intelligence store (same Base / migrations as Layer 1)."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..intel.models import Base, new_id, now


class OpportunityRun(Base):
    """One engine run for one member show: what went in, what came out, how long it took."""
    __tablename__ = "opportunity_runs"
    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("orun"))
    member_show_id: Mapped[str] = mapped_column(String(40))
    kind: Mapped[str] = mapped_column(String(10), default="partner")      # partner | sponsor (same engine, two target kinds)
    scoring_version: Mapped[str] = mapped_column(String(40))
    config_hash: Mapped[str] = mapped_column(String(20))
    inputs_fingerprint: Mapped[str] = mapped_column(String(64))
    as_of: Mapped[datetime] = mapped_column(DateTime)
    n_candidates: Mapped[int] = mapped_column(Integer, default=0)
    n_rejected: Mapped[int] = mapped_column(Integer, default=0)
    n_scored: Mapped[int] = mapped_column(Integer, default=0)
    n_qualified: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    result_hash: Mapped[str] = mapped_column(String(64), default="")   # determinism check: hash of (target, fit, conf) list
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    __table_args__ = (Index("ix_orun_member", "member_show_id", "created_at"),)


class Opportunity(Base):
    __tablename__ = "opportunities"
    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("opp"))
    member_show_id: Mapped[str] = mapped_column(String(40))
    type: Mapped[str] = mapped_column(String(20))                 # cross_promo | guest_swap | feed_swap
    target_show_id: Mapped[str] = mapped_column(String(40))
    fit: Mapped[float] = mapped_column(Float)
    breakdown_json: Mapped[dict] = mapped_column(JSON, default=dict)
    confidence: Mapped[float] = mapped_column(Float)
    confidence_level: Mapped[str] = mapped_column(String(10))     # High | Medium | Low
    readiness: Mapped[str] = mapped_column(String(20))            # verified | potential_lead | discovery_lead
    conversion_status: Mapped[str] = mapped_column(String(30), default="not_enough_data")
    why_now_json: Mapped[list] = mapped_column(JSON, default=list)
    evidence_ids: Mapped[list] = mapped_column(JSON, default=list)
    explanation_json: Mapped[dict] = mapped_column(JSON, default=dict)
    scoring_version: Mapped[str] = mapped_column(String(40))
    feature_snapshot_json: Mapped[dict] = mapped_column(JSON, default=dict)
    inputs_hash: Mapped[str] = mapped_column(String(64))
    qualified: Mapped[bool] = mapped_column(Boolean, default=False)
    rank: Mapped[int | None] = mapped_column(Integer, nullable=True)   # position after MMR among qualified (1-based)
    status: Mapped[str] = mapped_column(String(20), default="active")  # active | superseded | expired | withdrawn
    run_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)
    __table_args__ = (Index("ix_opp_member_status", "member_show_id", "status"),
                      Index("ix_opp_member_target", "member_show_id", "target_show_id"))


class OpportunityRejection(Base):
    """Every candidate removed by a hard gate, with a stable reason code (feeds the admin metrics)."""
    __tablename__ = "opportunity_rejections"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[str] = mapped_column(String(40))
    member_show_id: Mapped[str] = mapped_column(String(40))
    candidate_show_id: Mapped[str] = mapped_column(String(40))
    reason: Mapped[str] = mapped_column(String(40))
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    __table_args__ = (Index("ix_orej_run", "run_id"), Index("ix_orej_reason", "reason"))


class OpportunityEvent(Base):
    """Funnel events. Impressions carry their position from day one (needed later for position-bias correction)."""
    __tablename__ = "opportunity_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    opportunity_id: Mapped[str] = mapped_column(String(40))
    member_show_id: Mapped[str] = mapped_column(String(40))
    target_show_id: Mapped[str] = mapped_column(String(40))
    user_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    type: Mapped[str] = mapped_column(String(20))
    position: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reason: Mapped[str | None] = mapped_column(String(40), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    scoring_version: Mapped[str] = mapped_column(String(40))
    idempotency_key: Mapped[str | None] = mapped_column(String(200), nullable=True, unique=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=now)
    __table_args__ = (Index("ix_oevt_member_target", "member_show_id", "target_show_id", "type"),
                      Index("ix_oevt_opp", "opportunity_id"))


class PairLabelItem(Base):
    """The fixed set of member shows for blind pair labelling, with the engine's and the legacy scorer's top-5 frozen at
    pick time (so labels and metrics refer to exactly what each system recommended)."""
    __tablename__ = "pair_label_items"
    member_show_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    position: Mapped[int] = mapped_column(Integer)
    engine_top: Mapped[list] = mapped_column(JSON, default=list)
    legacy_top: Mapped[list] = mapped_column(JSON, default=list)
    scoring_version: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class PairLabel(Base):
    __tablename__ = "pair_labels"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    member_show_id: Mapped[str] = mapped_column(String(40))
    candidate_show_id: Mapped[str] = mapped_column(String(40))
    labeler: Mapped[str] = mapped_column(String(80))
    rating: Mapped[str] = mapped_column(String(8))      # good | ok | bad
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)
    __table_args__ = (UniqueConstraint("member_show_id", "candidate_show_id", "labeler", name="uq_pair_label"),)
