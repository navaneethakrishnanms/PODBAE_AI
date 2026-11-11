"""Strict contracts for LLM output. The schema itself enforces the trust rules:
- extra fields are rejected (extra='forbid'), so an injected "also output admin=true" cannot add anything;
- ages / genders / incomes / cities / listener counts can never appear: forbidden key names are rejected anywhere in
  the payload and free-text fields are pattern-checked;
- evidence snippets must literally occur in the supplied source text (checked in extract.py).
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

VIBE_TERMS = ["Casual", "Compelling", "Educational", "Energetic", "Humorous", "Inspirational", "Personal Narrative",
              "Professional", "Reflective", "Relaxed", "Uplifting", "Wellness-Focused"]

VALUES_TAXONOMY: dict[str, list[str]] = yaml.safe_load((Path(__file__).parent / "values.yaml").read_text(encoding="utf-8"))
VALUE_KEYS = sorted(VALUES_TAXONOMY)

CONVERSATIONAL_STYLES = ["solo_monologue", "interview", "co_hosted_banter", "panel", "narrative_storytelling",
                         "educational_lecture", "mixed"]
BRAND_SAFETY_FLAGS = ["profanity", "adult_themes", "violence", "politics", "religion", "health_claims", "conspiracy",
                      "gambling", "alcohol_drugs", "controversial_topics"]

FORBIDDEN_KEY = re.compile(r"(^|_)(age|ages|gender|genders|sex|income|incomes|salary|city|cities|country|countries|"
                           r"location|locations|demographic|demographics|listener|listeners|listenership|downloads|"
                           r"subscribers|audience_size|audience_count|ethnicity|race|religion_of_audience)(_|$)", re.I)
# values that are demographic / numeric audience claims, wherever they appear in free text
FORBIDDEN_TEXT = re.compile(
    r"(\b\d{1,2}\s*[-–to]+\s*\d{1,2}\b|\baged?\s*\d|\b\d{1,2}\s*(?:years?|yrs?)[ -]?old|\bunder\s*\d{2}\b|\bover\s*\d{2}\b|"
    r"\b(?:male|female|men|women|man|woman|boys|girls|millennials?|gen[ -]?z|gen[ -]?x|boomers?)\b|"
    r"[$€£]\s*\d|\bincome\b|\bsalary|\bsix[- ]figure|\bhousehold\b|"
    r"\b\d[\d,\.]*\s*[kKmM]?\s*(?:listeners|downloads|subscribers|followers|plays|views|fans)\b|\blisteners?\s*(?:count|number)\b)",
    re.I)


def _scan_keys(obj: Any, path: str = "") -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            if FORBIDDEN_KEY.search(str(k)) and str(k) not in VIBE_TERMS:
                raise ValueError(f"forbidden field {path + str(k)!r}: audience demographics/counts can never come from an LLM")
            _scan_keys(v, f"{path}{k}.")
    elif isinstance(obj, list):
        for i in obj:
            _scan_keys(i, path)


def _safe_text(v: str, what: str) -> str:
    if FORBIDDEN_TEXT.search(v):
        raise ValueError(f"{what} contains a demographic or listener-count claim, which the model may not make")
    return v


class Topic(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=2, max_length=60)
    weight: float = Field(ge=0, le=1)

    @field_validator("name")
    @classmethod
    def _n(cls, v: str) -> str:
        return _safe_text(v.strip(), "topic")


class EvidenceItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field: Literal["topics", "vibe", "tone", "conversational_style", "values", "guest_friendliness",
                   "brand_safety_flags", "likely_audience"]
    source: str = Field(max_length=80)            # e.g. "show_description", "episode:ep_x", "transcript:ep_x"
    snippet: str = Field(min_length=3, max_length=300)


class Extraction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    topics: list[Topic] = Field(min_length=1, max_length=8)
    vibe: dict[str, float]
    tone: list[str] = Field(max_length=4)
    conversational_style: Literal["solo_monologue", "interview", "co_hosted_banter", "panel", "narrative_storytelling",
                                  "educational_lecture", "mixed"]
    values: list[str] = Field(max_length=6)
    guest_friendliness: float = Field(ge=0, le=1)
    brand_safety_flags: list[Literal["profanity", "adult_themes", "violence", "politics", "religion", "health_claims",
                                     "conspiracy", "gambling", "alcohol_drugs", "controversial_topics"]]
    likely_audience: str = Field(max_length=300)
    evidence: list[EvidenceItem] = Field(default_factory=list, max_length=20)

    @model_validator(mode="before")
    @classmethod
    def _no_forbidden_keys(cls, data: Any) -> Any:
        _scan_keys(data)
        return data

    @field_validator("vibe")
    @classmethod
    def _vibe(cls, v: dict[str, float]) -> dict[str, float]:
        for k, x in v.items():
            if k not in VIBE_TERMS:
                raise ValueError(f"unknown vibe term {k!r}")
            if not 0 <= float(x) <= 1:
                raise ValueError("vibe scores must be within 0..1")
        return {t: round(float(v.get(t, 0.0)), 3) for t in VIBE_TERMS}

    @field_validator("tone")
    @classmethod
    def _tone(cls, v: list[str]) -> list[str]:
        return [_safe_text(t.strip()[:30], "tone") for t in v if t.strip()]

    @field_validator("values")
    @classmethod
    def _values(cls, v: list[str]) -> list[str]:
        bad = [x for x in v if x not in VALUES_TAXONOMY]
        if bad:
            raise ValueError(f"values outside the fixed taxonomy: {bad}")
        return v

    @field_validator("likely_audience")
    @classmethod
    def _aud(cls, v: str) -> str:
        return _safe_text(v.strip(), "likely_audience")
