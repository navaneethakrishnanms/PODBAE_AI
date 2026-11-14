"""Engine configuration: one versioned YAML (config.yaml). The config hash is stored with every run and opportunity so a
score can always be traced back to the exact weights that produced it."""
from __future__ import annotations

import copy
import hashlib
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

CONFIG_PATH = Path(__file__).with_name("config.yaml")
FACTORS = ["topic_alignment", "content_similarity", "vibe_compatibility", "format_compatibility", "activity_match",
           "collaboration_openness", "audience_size_parity", "geo_overlap"]
# factors that need data no public source provides: they switch on automatically when both shows have it
AUTO_DISABLED = {"audience_size_parity", "geo_overlap"}
EVENT_TYPES = ("impression", "open", "save", "unsave", "dismiss", "contact", "reply", "meeting", "partnership", "invite")
DISMISS_REASONS = ("not_my_vibe", "wrong_topic", "too_big", "too_small", "already_know_them", "other",
                   # sponsor opportunities
                   "not_my_audience", "category_conflict", "already_contacted")
SPONSOR_DISMISS_REASONS = ("not_my_audience", "category_conflict", "too_big", "already_contacted", "other")
OPP_TYPES = ("cross_promo", "guest_swap", "feed_swap")


@lru_cache(maxsize=1)
def _load() -> dict[str, Any]:
    cfg = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    validate(cfg)
    return cfg


def validate(cfg: dict[str, Any]) -> None:
    for k in ("scoring_version", "status", "candidates", "gates", "factors", "confidence", "why_now", "ranking"):
        if k not in cfg:
            raise ValueError(f"engine config missing '{k}'")
    missing = [f for f in FACTORS if f not in cfg["factors"]]
    if missing:
        raise ValueError(f"engine config missing factors {missing}")
    for f, c in cfg["factors"].items():
        if not 0 <= float(c.get("weight", -1)) <= 1:
            raise ValueError(f"factor {f}: weight must be in [0,1]")


def get_config() -> dict[str, Any]:
    return copy.deepcopy(_load())


def config_hash(cfg: dict[str, Any] | None = None) -> str:
    return hashlib.sha256(json.dumps(cfg or _load(), sort_keys=True).encode()).hexdigest()[:16]


def scoring_version(cfg: dict[str, Any] | None = None) -> str:
    return (cfg or _load())["scoring_version"]


def reload() -> None:
    _load.cache_clear()
