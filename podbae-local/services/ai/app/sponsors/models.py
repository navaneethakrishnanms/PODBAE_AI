"""Layer 2 Sponsor Intelligence tables (intelligence store, same Base / migrations as Layers 1 and 4)."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..intel.models import Base, new_id, now

EVIDENCE_CLASSES = ("declared_sponsorship", "likely_sponsorship", "affiliate", "podcast_promo", "self_promotion", "network_disclosure",
                    "organic_mention", "uncertain")
HISTORY_CLASSES = ("declared_sponsorship", "likely_sponsorship")       # + reviewed_ok uncertain
VERIFICATION = ("auto", "reviewed_ok", "reviewed_rejected")


class Brand(Base):
    __tablename__ = "brands"
    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("brd"))
    name: Mapped[str] = mapped_column(String(200))
    name_key: Mapped[str] = mapped_column(String(200))             # normalised name (identity only for name-only brands)
    primary_domain: Mapped[str | None] = mapped_column(String(200), nullable=True, unique=True)
    identity: Mapped[str] = mapped_column(String(20), default="domain")   # domain | name_only | manual
    aliases: Mapped[list] = mapped_column(JSON, default=list)
    parent_brand_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    status: Mapped[str] = mapped_column(String(10), default="unknown")   # active | inactive | unknown
    categories: Mapped[list] = mapped_column(JSON, default=list)          # [{id, label, score, method, tier, sensitive}]
    category_method: Mapped[str] = mapped_column(String(20), default="none")  # inferred | manual | override | none
    domain_verified: Mapped[bool] = mapped_column(Boolean, default=False)   # no fetching in Phase 3: always False (seam)
    first_seen: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_seen: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    n_shows: Mapped[int] = mapped_column(Integer, default=0)
    n_events: Mapped[int] = mapped_column(Integer, default=0)
    merged_into: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # Phase 4: LLM suggestions, stored NEXT TO the rule values; applied only while the LLM is active (manual edits always win)
    llm_categories: Mapped[list | None] = mapped_column(JSON, nullable=True)     # [{id,label,sensitive,quote,method:'llm',...}]
    llm_categories_version: Mapped[str | None] = mapped_column(String(120), nullable=True)
    name_suggestion: Mapped[str | None] = mapped_column(String(200), nullable=True)
    name_suggestion_status: Mapped[str | None] = mapped_column(String(20), nullable=True)  # auto_applied | pending | approved | rejected
    name_suggestion_support: Mapped[int] = mapped_column(Integer, default=0)       # snippets containing the exact string
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)
    __table_args__ = (Index("ix_brand_name_key", "name_key"),)


class BrandDomain(Base):
    __tablename__ = "brand_domains"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    domain: Mapped[str] = mapped_column(String(200), unique=True)
    brand_id: Mapped[str] = mapped_column(ForeignKey("brands.id"))
    source: Mapped[str] = mapped_column(String(20), default="detected")   # detected | alias_seed | manual
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class SponsorshipEvent(Base):
    """One detection in one episode (or transcript). EVERY class is stored, so exclusions are auditable; only
    declared/likely (and reviewed_ok uncertain) count as sponsorship history."""
    __tablename__ = "sponsorship_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(64), unique=True)            # sha of (episode, source, class, identity, rule)
    show_id: Mapped[str] = mapped_column(String(40))
    episode_id: Mapped[str] = mapped_column(String(40))
    episode_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    source: Mapped[str] = mapped_column(String(20), default="show_notes")   # show_notes | transcript
    cls: Mapped[str] = mapped_column(String(30))
    rule: Mapped[str] = mapped_column(String(60))
    snippet: Mapped[str] = mapped_column(String(300))
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    domain: Mapped[str | None] = mapped_column(String(200), nullable=True)
    brand_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    brand_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    promo_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    method: Mapped[str] = mapped_column(String(80))                       # rules | rules+gliner:<model>@<ver>
    model_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    detector_version: Mapped[str] = mapped_column(String(30))
    verification_status: Mapped[str] = mapped_column(String(20), default="auto")
    reviewed_class: Mapped[str | None] = mapped_column(String(30), nullable=True)
    sample_bucket: Mapped[int] = mapped_column(Integer, default=0)        # deterministic 0-99, for the stratified review sample
    # Phase 4 LLM second opinion (kept next to the rule class; used only while the LLM is active; humans still decide)
    llm_cls: Mapped[str | None] = mapped_column(String(30), nullable=True)      # effective class the LLM verdict maps to
    llm_raw_cls: Mapped[str | None] = mapped_column(String(30), nullable=True)  # what the model said (before the declared->likely cap)
    llm_reason: Mapped[str | None] = mapped_column(String(300), nullable=True)
    llm_quote: Mapped[str | None] = mapped_column(String(300), nullable=True)   # verbatim from the snippet / context sent
    llm_task: Mapped[str | None] = mapped_column(String(30), nullable=True)     # uncertain_classify | organic_audit
    llm_version: Mapped[str | None] = mapped_column(String(120), nullable=True) # model/prompt_version
    llm_flag: Mapped[bool] = mapped_column(Boolean, default=False)              # promoted by the LLM -> review first
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    __table_args__ = (Index("ix_spev_show", "show_id"), Index("ix_spev_brand", "brand_id", "cls"), Index("ix_spev_cls", "cls"),
                      Index("ix_spev_episode", "episode_id"))


class SponsorReview(Base):
    """A human verdict on one detection. Stored per reviewer; the event's verification_status follows the latest verdict."""
    __tablename__ = "sponsor_reviews"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[int] = mapped_column(Integer)
    reviewer: Mapped[str] = mapped_column(String(80))
    verdict: Mapped[str] = mapped_column(String(10))       # ok | reject
    correct_class: Mapped[str | None] = mapped_column(String(30), nullable=True)
    original_class: Mapped[str] = mapped_column(String(30))
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)
    __table_args__ = (UniqueConstraint("event_id", "reviewer", name="uq_sponsor_review"),)


class BrandRegistration(Base):
    """A brand that is a REGISTERED PodBae advertiser (synced from the app). Only this makes a sponsor 'Verified'.
    Linked by registrable domain or by an explicit admin mapping, never by name similarity."""
    __tablename__ = "brand_registrations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    brand_id: Mapped[str] = mapped_column(String(40))
    advertiser_ref: Mapped[str] = mapped_column(String(60))           # app advertiser id
    active_campaign: Mapped[bool] = mapped_column(Boolean, default=False)
    campaign_categories: Mapped[list] = mapped_column(JSON, default=list)
    campaign_started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    linked_by: Mapped[str] = mapped_column(String(20), default="domain")   # domain | admin
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)
    __table_args__ = (UniqueConstraint("brand_id", "advertiser_ref", name="uq_brand_registration"),)


class SponsorScanRun(Base):
    __tablename__ = "sponsor_scan_runs"
    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("sscan"))
    detector_version: Mapped[str] = mapped_column(String(30))
    method: Mapped[str] = mapped_column(String(80))
    shows: Mapped[int] = mapped_column(Integer, default=0)
    episodes: Mapped[int] = mapped_column(Integer, default=0)
    transcripts: Mapped[int] = mapped_column(Integer, default=0)
    events: Mapped[int] = mapped_column(Integer, default=0)
    by_class: Mapped[dict] = mapped_column(JSON, default=dict)
    seconds: Mapped[float] = mapped_column(Float, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
