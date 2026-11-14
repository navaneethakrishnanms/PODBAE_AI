"""Settings for the intelligence store + Layer 1 pipeline. All env-driven; zero keys needed."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]


def _b(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    return default if v is None else v.strip().lower() in ("1", "true", "yes", "on")


def _f(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


@dataclass
class Settings:
    database_url: str = field(default_factory=lambda: os.environ.get("INTEL_DATABASE_URL") or f"sqlite:///{(REPO_ROOT / 'data' / 'intel.db').as_posix()}")
    vector_backend: str = field(default_factory=lambda: os.environ.get("INTEL_VECTOR_BACKEND", "sqlite-vec"))  # sqlite-vec | pgvector
    # networking / safety
    allow_private_urls: bool = field(default_factory=lambda: _b("INTEL_ALLOW_PRIVATE_URLS", False))
    http_timeout: float = field(default_factory=lambda: _f("INTEL_HTTP_TIMEOUT", 20))
    max_feed_bytes: int = field(default_factory=lambda: int(_f("INTEL_MAX_FEED_BYTES", 25_000_000)))
    max_transcript_bytes: int = field(default_factory=lambda: int(_f("INTEL_MAX_TRANSCRIPT_BYTES", 2_000_000)))
    keep_episodes: int = 200          # metadata rows stored per show
    deep_episodes: int = 20           # episodes processed deeply (description + transcript + embeddings)
    transcript_episodes: int = 5      # max transcripts fetched per show
    # providers
    llm_provider: str = field(default_factory=lambda: os.environ.get("LLM_PROVIDER", "mock"))
    openai_key: str | None = field(default_factory=lambda: os.environ.get("OPENAI_API_KEY") or None)
    anthropic_key: str | None = field(default_factory=lambda: os.environ.get("ANTHROPIC_API_KEY") or None)
    openai_model: str = field(default_factory=lambda: os.environ.get("INTEL_OPENAI_MODEL", "gpt-4o-mini"))
    anthropic_model: str = field(default_factory=lambda: os.environ.get("INTEL_ANTHROPIC_MODEL", "claude-haiku-4-5"))
    pi_key: str | None = field(default_factory=lambda: os.environ.get("PODCASTINDEX_API_KEY") or None)
    pi_secret: str | None = field(default_factory=lambda: os.environ.get("PODCASTINDEX_API_SECRET") or None)
    taddy_user: str | None = field(default_factory=lambda: os.environ.get("TADDY_USER_ID") or None)
    taddy_key: str | None = field(default_factory=lambda: os.environ.get("TADDY_API_KEY") or None)
    taddy_enabled: bool = field(default_factory=lambda: _b("INTEL_TADDY_ENABLED", False))
    whisper_enabled: bool = field(default_factory=lambda: _b("INTEL_WHISPER_ENABLED", False))
    # embeddings
    embed_model: str = field(default_factory=lambda: os.environ.get("INTEL_EMBED_MODEL", "intfloat/multilingual-e5-small"))
    # economics (estimates, USD) - all overridable
    budget_global_monthly: float = field(default_factory=lambda: _f("INTEL_BUDGET_GLOBAL_MONTHLY_USD", 5.0))
    budget_podcast_monthly: float = field(default_factory=lambda: _f("INTEL_BUDGET_PODCAST_MONTHLY_USD", 0.10))
    cost_taddy_request: float = field(default_factory=lambda: _f("INTEL_COST_TADDY_REQUEST_USD", 0.002))
    cost_gpu_second: float = field(default_factory=lambda: _f("INTEL_COST_GPU_SECOND_USD", 0.0003))
    cost_whisper_audio_minute: float = field(default_factory=lambda: _f("INTEL_COST_WHISPER_MIN_USD", 0.003))
    # service auth: every /v1 route (except /v1/health) requires X-Service-Token == this. Empty = fail closed (401).
    service_token: str = field(default_factory=lambda: os.environ.get("INTEL_SERVICE_TOKEN", "").strip())
    # salt for one-way hashes of identifying values (owner e-mail); raw values are never stored, logged or exported
    hash_salt: str = field(default_factory=lambda: os.environ.get("INTEL_HASH_SALT", "podbae-intel-owner-v1"))
    # HTTP politeness / rate limits
    user_agent: str = field(default_factory=lambda: os.environ.get(
        "INTEL_USER_AGENT", "Mozilla/5.0 (compatible; PodBaeIntel/0.3; podcast metadata reader; +https://podbae.love)"))
    http_connect_timeout: float = field(default_factory=lambda: _f("INTEL_HTTP_CONNECT_TIMEOUT", 10))
    feed_retries: int = field(default_factory=lambda: int(_f("INTEL_FEED_RETRIES", 1)))   # extra tries on timeout / 5xx
    itunes_rate_per_min: float = field(default_factory=lambda: _f("INTEL_ITUNES_RATE_PER_MIN", 20))
    itunes_cache_hours: float = field(default_factory=lambda: _f("INTEL_ITUNES_CACHE_HOURS", 24))
    itunes_country: str = field(default_factory=lambda: os.environ.get("INTEL_ITUNES_COUNTRY", "US"))
    # feature flags
    # LLM refinement (Phase 4). OFF unless INTEL_LLM_REFINE=true AND LLM_PROVIDER is a real provider (not mock).
    # Either kill switch (LLM_PROVIDER=mock or INTEL_LLM_REFINE=false) restores exact Phase 3 behaviour: no LLM calls, and
    # every stored LLM value is ignored by every reader (it stays in the store for audit / comparison).
    llm_refine_enabled: bool = field(default_factory=lambda: _b("INTEL_LLM_REFINE", False))
    # Ollama (local or cloud model behind the local Ollama daemon)
    ollama_base_url: str = field(default_factory=lambda: os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/"))
    ollama_model: str = field(default_factory=lambda: os.environ.get("OLLAMA_MODEL", "gpt-oss:120b-cloud"))
    llm_timeout: float = field(default_factory=lambda: _f("LLM_TIMEOUT_SECONDS", 180))
    llm_think: str = field(default_factory=lambda: os.environ.get("LLM_THINK", "low"))   # only sent to models that can think
    llm_num_ctx: int = field(default_factory=lambda: int(_f("LLM_NUM_CTX", 8192)))
    llm_rate_per_min: float = field(default_factory=lambda: _f("LLM_RATE_PER_MIN", 30))   # client-side limiter; 0 = off
    llm_max_retries: int = field(default_factory=lambda: int(_f("LLM_MAX_RETRIES", 2)))   # invalid output -> at most 3 calls
    llm_backoff_base: float = field(default_factory=lambda: _f("LLM_BACKOFF_BASE", 2.0))
    llm_backoff_max: float = field(default_factory=lambda: _f("LLM_BACKOFF_MAX", 60.0))
    llm_http_retries: int = field(default_factory=lambda: int(_f("LLM_HTTP_RETRIES", 3)))  # 429 / 5xx retries before pausing
    llm_conf_cap: float = field(default_factory=lambda: _f("LLM_CONFIDENCE_CAP", 0.6))     # max confidence of any LLM value
    llm_organic_sample: int = field(default_factory=lambda: int(_f("LLM_ORGANIC_SAMPLE", 1500)))   # organic_mention audit size
    llm_phrase_daily_calls: int = field(default_factory=lambda: int(_f("LLM_PHRASE_DAILY_CALLS", 300)))
    llm_phrasing_enabled: bool = field(default_factory=lambda: _b("INTEL_LLM_PHRASING", True))  # extra switch for card text only
    # job worker
    worker_enabled: bool = field(default_factory=lambda: _b("INTEL_WORKER", True))
    max_attempts: int = 3
    backoff_base_seconds: float = field(default_factory=lambda: _f("INTEL_BACKOFF_BASE", 2.0))
    job_lease_seconds: int = 300


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reset_settings(**overrides) -> Settings:
    """Re-read env and apply overrides (tests)."""
    global _settings
    _settings = Settings()
    for k, v in overrides.items():
        setattr(_settings, k, v)
    return _settings
