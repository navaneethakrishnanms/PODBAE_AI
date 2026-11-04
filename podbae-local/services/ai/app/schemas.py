"""Pydantic mirror of packages/contracts (camelCase on the wire)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

TargetType = Literal["podcast", "sponsor", "guest", "venue", "collaborator"]


class Camel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class Evidence(Camel):
    source: str
    ref: str
    fetched_at: str


class Explanation(Camel):
    summary: str
    reasons: list[str]
    why_now: str | None = None
    evidence: list[Evidence]


class ScoreBreakdown(Camel):
    genre_score: float
    location_score: float
    tone_score: float
    keyword_score: float
    vibe_score: float
    performance_score: float
    listen_score: float
    weights: dict[str, float]
    total: float


class Subject(Camel):
    id: int
    user_id: int | None = None
    name: str
    categories: list[str] = Field(default_factory=list)
    location: str | None = None
    vibe_tags: list[str] = Field(default_factory=list)
    tone_tags: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    last_episode_at: str | None = None
    episode_count: int | None = None


class Candidate(Subject):
    type: TargetType


class MatchRequest(Camel):
    podcast: Subject
    candidates: list[Candidate]
    target_types: list[TargetType] = Field(
        default_factory=lambda: ["podcast", "sponsor", "guest", "venue", "collaborator"]
    )
    limit: int = 50
    as_of: str | None = None  # ISO timestamp; pass for fully reproducible output


class MatchResult(Camel):
    target_type: TargetType
    target_id: int
    total_score: float
    score_breakdown: ScoreBreakdown
    explanation: Explanation


class MatchResponse(Camel):
    matches: list[MatchResult]


class ChatRequest(Camel):
    message: str
    context: dict[str, Any] = Field(default_factory=dict)
    history: list[dict[str, str]] = Field(default_factory=list)


class ChatResponse(Camel):
    reply: str
    provider: str
