"""Phase 4 tables: the LLM output cache (content hash -> validated output) and the per-call log (tokens, latency, status).
Thinking text is never stored. Prompts are not stored either: only their hash (the cache key) and version."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..intel.models import Base, now


class LlmCache(Base):
    __tablename__ = "llm_cache"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)     # sha256(task|prompt_version|model|system|prompt)
    task: Mapped[str] = mapped_column(String(40))
    prompt_version: Mapped[str] = mapped_column(String(40))
    model: Mapped[str] = mapped_column(String(80))
    entity_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    entity_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    output: Mapped[dict] = mapped_column(JSON)                          # schema-validated output (before evidence checks)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    __table_args__ = (Index("ix_llm_cache_task", "task", "prompt_version"),)


class LlmCall(Base):
    __tablename__ = "llm_calls"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=now)
    task: Mapped[str] = mapped_column(String(40))
    provider: Mapped[str] = mapped_column(String(30))                    # ollama-local | ollama-cloud | mock-test
    model: Mapped[str] = mapped_column(String(80))
    prompt_version: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20))      # ok | cache | invalid | error | rate_limited | unavailable | privacy | budget
    cache_hit: Mapped[bool] = mapped_column(Boolean, default=False)
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    entity_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    entity_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    __table_args__ = (Index("ix_llm_calls_task", "task", "ts"),)
