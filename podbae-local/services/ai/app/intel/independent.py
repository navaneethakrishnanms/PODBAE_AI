"""The editable definition of an "independent, active" show (services/ai/seed/independent.yaml).
check() returns every failed rule, so seed reports show WHY a show was rejected (not just that it was)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

import yaml

from .models import now

CONFIG_PATH = Path(__file__).resolve().parents[2] / "seed" / "independent.yaml"


@dataclass
class IndependentRules:
    network_blocklist: list[str] = field(default_factory=list)
    host_blocklist: list[str] = field(default_factory=list)
    max_days_since_last_episode: int = 90
    min_episodes: int = 5
    max_episodes: int = 2000
    version: str = "independent-v1"


def load_rules(path: Path = CONFIG_PATH) -> IndependentRules:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return IndependentRules(network_blocklist=[str(x).lower().strip() for x in raw.get("network_blocklist") or []],
                            host_blocklist=[str(x).lower().strip() for x in raw.get("host_blocklist") or []],
                            max_days_since_last_episode=int(raw.get("max_days_since_last_episode", 90)),
                            min_episodes=int(raw.get("min_episodes", 5)), max_episodes=int(raw.get("max_episodes", 2000)),
                            version=str(raw.get("version", "independent-v1")))


def network_match(rules: IndependentRules, names: list[str | None], feed_url: str | None) -> str | None:
    """Return the blocklist entry that matched, else None. Names match on whole words; hosts on domain suffix."""
    for name in names:
        low = (name or "").lower()
        if not low:
            continue
        for term in rules.network_blocklist:
            if re.search(r"(?<![\w])" + re.escape(term) + r"(?![\w])", low):
                return f"publisher '{term}'"
    if feed_url:
        p = urlsplit(feed_url)
        host, path = (p.hostname or "").lower(), (p.path or "").lower()
        for h in rules.host_blocklist:
            dom, _, pre = h.partition("/")
            if (host == dom or host.endswith("." + dom)) and (not pre or path.lstrip("/").startswith(pre)):
                return f"host '{h}'"
    return None


def check(rules: IndependentRules, *, names: list[str | None], feed_url: str | None, last_published: datetime | None,
          episode_count: int | None, at: datetime | None = None) -> list[str]:
    """Empty list = accepted. Otherwise one reason code per failed rule:
    network:<match> | inactive:<days> | no_dated_episodes | too_few_episodes:<n> | too_many_episodes:<n>."""
    reasons: list[str] = []
    m = network_match(rules, names, feed_url)
    if m:
        reasons.append(f"network:{m}")
    if last_published is None:
        reasons.append("no_dated_episodes")
    else:
        age = ((at or now()) - last_published).days
        if age > rules.max_days_since_last_episode:
            reasons.append(f"inactive:{age}d")
    n = episode_count or 0
    if n < rules.min_episodes:
        reasons.append(f"too_few_episodes:{n}")
    elif n > rules.max_episodes:
        reasons.append(f"too_many_episodes:{n}")
    return reasons


def reason_code(reason: str) -> str:
    return reason.split(":", 1)[0]
