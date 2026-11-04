"""PLACEHOLDER matcher: weighted Jaccard tag overlap. Deterministic. Replaced in a later phase."""

from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from .schemas import (
    Candidate,
    Evidence,
    Explanation,
    MatchRequest,
    MatchResponse,
    MatchResult,
    ScoreBreakdown,
    Subject,
)

UTC = timezone.utc
CONFIG_PATH = Path(__file__).with_name("weights.yaml")
COMPONENTS = ["genreScore", "locationScore", "toneScore", "keywordScore", "vibeScore", "performanceScore"]


@lru_cache(maxsize=1)
def load_config() -> dict[str, Any]:
    with CONFIG_PATH.open() as f:
        return yaml.safe_load(f)  # type: ignore[no-any-return]


def _norm(tags: list[str]) -> set[str]:
    return {t.strip().lower() for t in tags if t and t.strip()}


def jaccard(a: list[str], b: list[str]) -> float:
    sa, sb = _norm(a), _norm(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def location_score(a: str | None, b: str | None) -> float:
    if not a or not b:
        return 0.0
    ta = [t.strip().lower() for t in a.split(",") if t.strip()]
    tb = [t.strip().lower() for t in b.split(",") if t.strip()]
    if not ta or not tb:
        return 0.0
    if ta[0] == tb[0]:
        return 1.0
    return 0.5 if set(ta) & set(tb) else 0.0


def _parse(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        d = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=UTC)


def _days_since(ts: str | None, now: datetime) -> int | None:
    d = _parse(ts)
    if d is None:
        return None
    return max(int((now - d).total_seconds() // 86400), 0)


def performance_score(c: Candidate, now: datetime, cfg: dict[str, Any]) -> float:
    """Episode recency (exp. decay) + frequency. Non-podcast targets get a neutral 0.5."""
    if c.type not in ("podcast", "collaborator"):
        return 0.5
    days = _days_since(c.last_episode_at, now)
    if days is None:
        return 0.0
    half = float(cfg["performance"]["recency_half_life_days"])
    recency = 0.5 ** (days / half)
    freq = min((c.episode_count or 0) / 24, 1.0)
    return round(0.7 * recency + 0.3 * freq, 6)


def _shared(a: list[str], b: list[str]) -> list[str]:
    sb = _norm(b)
    seen: list[str] = []
    for t in a:
        if t.strip().lower() in sb and t not in seen:
            seen.append(t)
    return seen


def score_one(subject: Subject, c: Candidate, now: datetime, cfg: dict[str, Any]) -> MatchResult:
    weights: dict[str, float] = cfg["weights"]
    parts = {
        "genreScore": jaccard(subject.categories, c.categories),
        "locationScore": location_score(subject.location, c.location),
        "toneScore": jaccard(subject.tone_tags, c.tone_tags),
        "keywordScore": jaccard(subject.keywords, c.keywords),
        "vibeScore": jaccard(subject.vibe_tags, c.vibe_tags),
        "performanceScore": performance_score(c, now, cfg),
        "listenScore": 0.0,
    }
    wsum = sum(weights.values()) or 1.0
    total = round(sum(weights.get(k, 0.0) * v for k, v in parts.items()) / wsum * 100, 2)
    parts = {k: round(v, 4) for k, v in parts.items()}
    breakdown = ScoreBreakdown(
        genre_score=parts["genreScore"],
        location_score=parts["locationScore"],
        tone_score=parts["toneScore"],
        keyword_score=parts["keywordScore"],
        vibe_score=parts["vibeScore"],
        performance_score=parts["performanceScore"],
        listen_score=parts["listenScore"],
        weights=weights,
        total=total,
    )
    return MatchResult(
        target_type=c.type,
        target_id=c.id,
        total_score=total,
        score_breakdown=breakdown,
        explanation=explain(subject, c, parts, weights, total, now),
    )


def _reason(key: str, subject: Subject, c: Candidate, now: datetime) -> str:
    if key == "genreScore":
        return f"Shared categories: {', '.join(_shared(subject.categories, c.categories))}."
    if key == "locationScore":
        same_city = location_score(subject.location, c.location) >= 1
        return f"Both based in {c.location}." if same_city else "Overlapping region."
    if key == "toneScore":
        return f"Similar tone: {', '.join(_shared(subject.tone_tags, c.tone_tags))}."
    if key == "keywordScore":
        return f"Common keywords: {', '.join(_shared(subject.keywords, c.keywords))}."
    if key == "vibeScore":
        return f"Shared vibe: {', '.join(_shared(subject.vibe_tags, c.vibe_tags))}."
    days = _days_since(c.last_episode_at, now)
    return f"Actively publishing (last episode {days} day(s) ago)."


def explain(
    subject: Subject,
    c: Candidate,
    parts: dict[str, float],
    weights: dict[str, float],
    total: float,
    now: datetime,
) -> Explanation:
    """Templated from the breakdown only: top 2 contributing reasons + why-now from episode recency."""
    keys = [
        k for k in COMPONENTS
        if parts[k] > 0 and not (k == "performanceScore" and c.type not in ("podcast", "collaborator"))
    ]
    keys.sort(key=lambda k: (-weights.get(k, 0.0) * parts[k], COMPONENTS.index(k)))
    top = keys[:2]
    reasons = [_reason(k, subject, c, now) for k in top] or ["Low overlap; included as a stretch match."]
    label = {"genreScore": "genre", "locationScore": "location", "toneScore": "tone",
             "keywordScore": "keywords", "vibeScore": "vibe", "performanceScore": "activity"}
    lead = f" — strongest on {label[top[0]]}" if top else ""
    days = _days_since(subject.last_episode_at, now)
    if days is None:
        why_now = "Publish an episode to keep your matches fresh."
    elif days <= 14:
        why_now = f"You published {days} day(s) ago — momentum is high, a good time to reach out."
    else:
        why_now = f"It's been {days} days since your last episode — a new partnership could re-engage listeners."
    return Explanation(
        summary=f"{c.name} is a {total:.0f}% match{lead}.",
        reasons=reasons,
        why_now=why_now,
        evidence=[Evidence(source=f"db:{c.type}", ref=str(c.id), fetched_at=now.isoformat())],
    )


def match(req: MatchRequest) -> MatchResponse:
    cfg = load_config()
    now = _parse(req.as_of) or datetime.now(UTC)
    results = [score_one(req.podcast, c, now, cfg) for c in req.candidates if c.type in req.target_types]
    results.sort(key=lambda r: (-r.total_score, r.target_type, r.target_id))  # deterministic
    return MatchResponse(matches=results[: req.limit])
