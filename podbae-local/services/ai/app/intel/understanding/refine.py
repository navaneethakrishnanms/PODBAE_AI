"""LLM refinement SEAM (Phase 1: disabled, nothing registered).

Phase 1 produces every field with rules or local models. A later phase can add an LLM (e.g. a local "ollama" provider
behind understanding/providers.py) that REFINES specific fields without replacing the rules:

    @register_refiner("conversational_style")
    def refine_style(ctx: RefineContext) -> RefineResult | None: ...

A refiner receives the rule/model value, its confidence and the sanitised source texts, and may return a new value.
Its output must go through the existing trust wrapper (understanding/extract.py: data blocks, strict schema, evidence
must be verbatim, budget + cache), is stored as method='llm', tier='inferred', and NEVER overwrites a verified or
creator-provided value. Fields where a refiner is expected to help most (see PHASE1_REPORT.md):
  - conversational_style when the rules say "unknown"
  - guest detection (is "with Jane Smith" a guest or a co-host?) and guest names
  - topics outside the lexicon (sub-topics, niche subjects)
  - vibe (text-grounded instead of embedding-only)
  - likely_audience wording, brand-safety context (organic mention vs endorsement)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from ..config import get_settings


@dataclass
class RefineContext:
    show_id: str
    field: str
    value: Any
    confidence: float
    sources: dict[str, str] = field(default_factory=dict)


@dataclass
class RefineResult:
    value: Any
    confidence: float
    evidence: list[dict] = field(default_factory=list)


Refiner = Callable[[RefineContext], RefineResult | None]
REFINERS: dict[str, Refiner] = {}


def register_refiner(field_name: str) -> Callable[[Refiner], Refiner]:
    def deco(fn: Refiner) -> Refiner:
        REFINERS[field_name] = fn
        return fn
    return deco


def refine_enabled() -> bool:
    """True only if the flag is on AND at least one refiner exists. Phase 1: always False."""
    return bool(get_settings().llm_refine_enabled and REFINERS)
