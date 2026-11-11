"""Provenance: every stored fact has a source, a data tier, a timestamp, a confidence.

- `record()` writes a fact. Same value from the same source just refreshes fetched_at/expires_at; a changed
  value supersedes the previous row (history kept).
- `resolve()` picks the display value among conflicting live values: tier priority
  (verified > creator_provided > estimated > inferred), then freshness; all alternatives are returned and a
  conflict is written to the audit log (once per distinct set of values).
- `freshness()` implements the field-level freshness policy; stale values are flagged, never silently trusted.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import AuditLog, Evidence, Provenance, Source, now

TIER_RANK = {"verified": 0, "creator_provided": 1, "estimated": 2, "inferred": 3}

# field -> time-to-live. Anything not listed uses DEFAULT_TTL. None = does not expire.
FRESHNESS_POLICY: dict[str, timedelta | None] = {
    "episodes": timedelta(hours=24),
    "episode_count": timedelta(hours=24),
    "last_published": timedelta(hours=24),
    "activity_status": timedelta(hours=24),
    "cadence_days": timedelta(hours=24),
    "avg_episode_minutes": timedelta(days=7),
    "title": timedelta(days=7),
    "description": timedelta(days=7),
    "language": timedelta(days=7),
    "categories": timedelta(days=7),
    "explicit": timedelta(days=7),
    "hosts": timedelta(days=7),
    "guests_present": timedelta(days=7),
    "transcripts_available": timedelta(days=7),
    "topics": timedelta(days=30),
    "vibe": timedelta(days=30),
    "tone": timedelta(days=30),
    "conversational_style": timedelta(days=30),
    "values": timedelta(days=30),
    "guest_friendliness": timedelta(days=30),
    "brand_safety_flags": timedelta(days=30),
    "likely_audience": timedelta(days=30),
    "audience.": timedelta(days=180),      # prefix: creator-uploaded analytics
    "creator.": None,                      # self-declared: valid until the creator changes it
}
DEFAULT_TTL = timedelta(days=7)


def ttl_for(field: str) -> timedelta | None:
    if field in FRESHNESS_POLICY:
        return FRESHNESS_POLICY[field]
    for k, v in FRESHNESS_POLICY.items():
        if k.endswith(".") and field.startswith(k):
            return v
    return DEFAULT_TTL


def get_source(s: Session, name: str, kind: str, terms_note: str | None = None) -> Source:
    src = s.scalar(select(Source).where(Source.name == name))
    if src is None:
        src = Source(name=name, kind=kind, terms_note=terms_note)
        s.add(src)
        s.flush()
    return src


def _same(a: Any, b: Any) -> bool:
    return json.dumps(a, sort_keys=True, default=str) == json.dumps(b, sort_keys=True, default=str)


def record(s: Session, entity_type: str, entity_id: str, field: str, value: Any, *, source: Source, tier: str,
           method: str, confidence: float = 1.0, source_ref: str | None = None, model_version: str | None = None,
           ttl: timedelta | None | str = "policy", at: datetime | None = None) -> Provenance:
    if tier not in TIER_RANK:
        raise ValueError(f"bad data tier {tier!r}")
    at = at or now()
    life = ttl_for(field) if ttl == "policy" else ttl
    expires = (at + life) if isinstance(life, timedelta) else None
    prev = s.scalar(select(Provenance).where(
        Provenance.entity_type == entity_type, Provenance.entity_id == entity_id, Provenance.field == field,
        Provenance.source_id == source.id, Provenance.superseded_by.is_(None)))
    if prev is not None and _same(prev.value_json, value) and prev.data_tier == tier:
        prev.fetched_at, prev.expires_at, prev.confidence = at, expires, confidence
        prev.source_ref, prev.model_version = source_ref or prev.source_ref, model_version or prev.model_version
        return prev
    row = Provenance(entity_type=entity_type, entity_id=entity_id, field=field, value_json=value, source_id=source.id,
                     source_ref=source_ref, data_tier=tier, method=method, model_version=model_version,
                     fetched_at=at, expires_at=expires, confidence=max(0.0, min(1.0, confidence)))
    s.add(row)
    s.flush()
    if prev is not None:
        prev.superseded_by = row.id
    return row


def add_evidence(s: Session, entity_type: str, entity_id: str, kind: str, snippet: str, locator: dict,
                 source: Source | None = None) -> Evidence:
    ev = Evidence(entity_type=entity_type, entity_id=entity_id, kind=kind, snippet=snippet[:300], locator=locator,
                  source_id=source.id if source else None)
    s.add(ev)
    s.flush()
    return ev


def freshness(row: Provenance, at: datetime | None = None) -> str:
    """fresh | stale | no_expiry"""
    at = at or now()
    if row.expires_at is None:
        return "no_expiry"
    return "fresh" if row.expires_at > at else "stale"


def live_rows(s: Session, entity_type: str, entity_id: str, field: str | None = None) -> list[Provenance]:
    q = select(Provenance).where(Provenance.entity_type == entity_type, Provenance.entity_id == entity_id,
                                 Provenance.superseded_by.is_(None))
    if field:
        q = q.where(Provenance.field == field)
    return list(s.scalars(q))


def resolve(s: Session, rows: list[Provenance], *, log_conflict: bool = True) -> tuple[Provenance | None, list[Provenance]]:
    """Pick the display row; return (winner, alternatives). Conflicts are recorded, not hidden."""
    if not rows:
        return None, []
    ordered = sorted(rows, key=lambda r: (TIER_RANK[r.data_tier], -(r.fetched_at.timestamp()), -r.confidence))
    winner, others = ordered[0], ordered[1:]
    differing = [r for r in others if not _same(r.value_json, winner.value_json)]
    if differing and log_conflict:
        sig = hashlib.sha1(json.dumps(sorted([f"{r.source_id}:{json.dumps(r.value_json, sort_keys=True, default=str)}"
                                              for r in ordered])).encode()).hexdigest()[:16]
        exists = s.scalar(select(AuditLog.id).where(AuditLog.action == "conflict", AuditLog.entity_id == winner.entity_id,
                                                    AuditLog.detail["sig"].as_string() == sig))
        if not exists:
            s.add(AuditLog(actor="resolver", action="conflict", entity_type=winner.entity_type, entity_id=winner.entity_id,
                           detail={"field": winner.field, "sig": sig, "winner_provenance_id": winner.id,
                                   "values": [{"provenance_id": r.id, "source_id": r.source_id, "tier": r.data_tier,
                                               "value": r.value_json} for r in ordered]}))
    return winner, others
