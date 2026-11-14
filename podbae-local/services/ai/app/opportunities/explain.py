"""H. Explanations without an LLM.

An explanation is a list of PARTS. Each part = a fixed template id + slot values copied verbatim from the stored breakdown /
why-now evidence, and its text is exactly the template rendered with those slots. `faithfulness()` re-checks that:
  1. every part's text == its template rendered with its slots (so nothing else can enter the text), and
  2. every slot value (each list element, each number) exists in the opportunity's own record
     (breakdown inputs, why-now evidence, target title, Fit, confidence level), and
  3. every number in the final text comes from a slot (templates contain no digits).

LLM seam (NOT used in this phase): `Phraser.phrase(parts, record) -> str`. A future LLM phraser may reword the text, but its
output must pass the same faithfulness check against the same record or the template text is used instead."""
from __future__ import annotations

import json
import re
from typing import Any, Protocol

TYPE_LABEL = {"cross_promo": "cross-promo", "guest_swap": "guest-swap", "feed_swap": "feed-swap", "sponsor": "sponsorship"}
T = {
    "headline": "{target} could be a good {type_label} partner: Fit {fit}, {level} evidence confidence.",
    "topic_alignment.topics": "You both cover {topics}.",
    "topic_alignment.groups": "You are both in {groups}.",
    "content_similarity.peak": "Your episodes cover closely related ground without being copies: more similar than {percentile}% of show pairs we track.",
    "content_similarity.near": "Your episodes cover related ground: more similar than {percentile}% of show pairs we track.",
    "vibe_compatibility.shared": "Similar feel: you both lean {vibes}.",
    "vibe_compatibility.plain": "Your style and tone signals point the same way.",
    "format_compatibility.both": "Similar format: about {member_minutes} vs {candidate_minutes} minutes per episode.",
    "format_compatibility.cadence": "Similar rhythm: publishing about every {member_cadence_days} vs {candidate_cadence_days} days.",
    "activity_match": "{target} is actively publishing: last episode {days} days ago.",
    "collaboration_openness.stated": "{target} says they are {openness} to collaborations.",
    "collaboration_openness.guests": "{target} features guests in {pct}% of recent episodes.",
    "why.joined_podbae": "Why now: they joined PodBae on {date}.",
    # ── sponsor opportunities (Layer 2 evidence) ──
    "sponsor.lookalike.one": "{target} sponsored {n} show similar to yours: {shows}.",
    "sponsor.lookalike": "{target} sponsored {n} shows similar to yours, including {shows}.",
    "sponsor.quote": "Evidence: \u201c{snippet}\u201d ({show}, {date}).",
    "sponsor.momentum": "Their sponsorship activity is rising: {recent} sponsored episodes in the last {window} days vs {prior} in the {window} before.",
    "sponsor.category": "Their ads fit your category: {category}.",
    "sponsor.breadth.one": "They sponsor {n} show we track.",
    "sponsor.breadth": "They sponsor {n} different shows we track.",
    "sponsor.recency": "Last seen sponsoring a podcast {days} days ago.",
    "why.sponsor_similar_recent.one": "Why now: they sponsored {n} show similar to yours in the last {days} days.",
    "why.sponsor_similar_recent": "Why now: they sponsored {n} shows similar to yours in the last {days} days.",
    "why.sponsor_category_start": "Why now: they started sponsoring {group} shows on {date}.",
    "why.sponsor_rising": "Why now: their sponsorship activity is rising, {recent} episodes in the last {window} days vs {prior} before.",
    "why.sponsor_campaign": "Why now: a matching PodBae advertiser campaign started on {date}.",
    "why.shared_topic_recent": "Why now: they published “{title}” on {date}, on {topic}, a topic you share.",
    "why.recent_guest_episodes.one": "Why now: {n} guest episode in the last {days} days: “{title}” ({date}).",
    "why.recent_guest_episodes": "Why now: {n} guest episodes in the last {days} days, most recently “{title}” ({date}).",
    "why.reactivated": "Why now: they are back after a {gap}-day break with “{title}” ({date}).",
    "why.cadence_increased": "Why now: they are publishing more often, every {recent} days lately vs {prior} before.",
}


def _join(xs: list[str]) -> str:
    xs = [str(x) for x in xs]
    return xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + " and " + xs[-1]


def _render(tid: str, slots: dict) -> str:
    return T[tid].format(**{k: (_join(v) if isinstance(v, list) else v) for k, v in slots.items()})


def _part(tid: str, **slots) -> dict:
    return {"id": tid, "slots": slots, "text": _render(tid, slots)}


def factor_part(f: dict, target: str) -> dict | None:
    n, i = f["name"], f["inputs"]
    if n == "topic_alignment":
        if i.get("basis") == "topics" and i.get("shared_topics"):
            return _part("topic_alignment.topics", topics=[t["name"] for t in i["shared_topics"][:3]])
        if i.get("shared_groups"):
            return _part("topic_alignment.groups", groups=i["shared_groups"][:2])
        return None
    if n == "content_similarity" and i.get("pair_percentile") is not None:
        return _part("content_similarity.peak" if i.get("band") == "peak" else "content_similarity.near", percentile=i["pair_percentile"])
    if n == "vibe_compatibility":
        return _part("vibe_compatibility.shared", vibes=i["shared_top_vibes"][:3]) if i.get("shared_top_vibes") else _part("vibe_compatibility.plain")
    if n == "format_compatibility":
        if "member_minutes" in i:
            return _part("format_compatibility.both", member_minutes=i["member_minutes"], candidate_minutes=i["candidate_minutes"])
        if "member_cadence_days" in i:
            return _part("format_compatibility.cadence", member_cadence_days=i["member_cadence_days"], candidate_cadence_days=i["candidate_cadence_days"])
        return None
    if n == "activity_match":
        return _part("activity_match", target=target, days=i["candidate_days_since_last_episode"])
    if n == "collaboration_openness":
        if i.get("stated_openness"):
            return _part("collaboration_openness.stated", target=target, openness=i["stated_openness"])
        if i.get("guest_share") is not None and i["guest_share"] > 0:
            return _part("collaboration_openness.guests", target=target, pct=round(100 * i["guest_share"]))
        return None
    return None


def why_part(t: dict) -> dict | None:
    d, ev = t.get("detail") or {}, (t.get("evidence") or [{}])
    e0 = ev[0] if ev else {}
    code = t["code"]
    if code == "joined_podbae":
        return _part("why.joined_podbae", date=d["joined_on"])
    if code == "shared_topic_recent":
        return _part("why.shared_topic_recent", title=e0["title"], date=e0["date"], topic=d["topic_name"])
    if code == "recent_guest_episodes":
        tid = "why.recent_guest_episodes.one" if d["guest_episodes"] == 1 else "why.recent_guest_episodes"
        return _part(tid, n=d["guest_episodes"], days=d["window_days"], title=e0["title"], date=e0["date"])
    if code == "reactivated":
        return _part("why.reactivated", gap=d["gap_days"], title=e0["title"], date=e0["date"])
    if code == "cadence_increased":
        return _part("why.cadence_increased", recent=d["recent_median_gap_days"], prior=d["prior_median_gap_days"])
    return None


def build(record: dict, factor_part_fn=None, why_part_fn=None, max_reasons: int = 3) -> dict:
    """record = {target_title, type, fit, confidence:{level}, factors:[...], why_now:[...]}. Deterministic. Each opportunity
    kind supplies its own factor_part / why_part (partner ones by default); text = templates only, faithfulness-checked."""
    factor_part_fn, why_part_fn = factor_part_fn or factor_part, why_part_fn or why_part
    target = record["target_title"]
    parts = [_part("headline", target=target, type_label=TYPE_LABEL[record["type"]], fit=round(record["fit"]),
                   level=record["confidence"]["level"])]
    used = sorted((f for f in record["factors"] if f["status"] == "used" and f["contribution"] > 0),
                  key=lambda f: (-f["contribution"], f["name"]))
    reasons = [p for p in (factor_part_fn(f, target) for f in used) if p][:max_reasons]
    parts += reasons
    why = next((p for p in (why_part_fn(t) for t in record.get("why_now") or []) if p), None)
    if why:
        parts.append(why)
    text = " ".join(p["text"] for p in parts)
    return {"parts": parts, "text": get_phraser().phrase(parts, record) if _llm_phrasing_enabled() else text,
            "method": "template", "top_factors": [f["name"] for f in used[:3]]}


def part(tid: str, **slots) -> dict:
    """Public helper for other opportunity kinds' template parts."""
    return _part(tid, **slots)


# ───────────────────────── faithfulness ─────────────────────────
NUM_RX = re.compile(r"\d+(?:\.\d+)?")


def _flatten(x: Any, strs: set[str], nums: list[float]) -> None:
    if isinstance(x, dict):
        for v in x.values():
            _flatten(v, strs, nums)
    elif isinstance(x, (list, tuple)):
        for v in x:
            _flatten(v, strs, nums)
    elif isinstance(x, bool) or x is None:
        return
    elif isinstance(x, (int, float)):
        nums.append(float(x))
    else:
        s = str(x)
        strs.add(s.lower())
        for n in NUM_RX.findall(s):
            nums.append(float(n))


def _num_forms(nums: list[float]) -> set[float]:
    """Every number in the record plus the roundings a template may legitimately show (integer, 1 decimal, as a percent)."""
    out: set[float] = set()
    for n in nums:
        out.update((n, float(round(n)), round(n, 1), float(round(100 * n))))
    return out


def _num_ok(v: float, forms: set[float]) -> bool:
    return float(v) in forms


def faithfulness(explanation: dict, record: dict) -> list[str]:
    """Return a list of problems ([] = faithful). Checked against the factor INPUTS (what was measured), why-now evidence,
    the target title, Fit and the confidence level."""
    strs: set[str] = set()
    raw: list[float] = []
    _flatten({"inputs": [f.get("inputs") for f in record["factors"]], "why_now": record.get("why_now"), "target": record["target_title"],
              "fit": record["fit"], "level": record["confidence"]["level"], "type_label": TYPE_LABEL[record["type"]]}, strs, raw)
    nums = _num_forms(raw)
    problems: list[str] = []
    slot_nums: list[float] = []
    for p in explanation["parts"]:
        if p["id"] not in T:
            problems.append(f"unknown template {p['id']}")
            continue
        if _render(p["id"], p["slots"]) != p["text"]:
            problems.append(f"text of {p['id']} differs from its template")
        for k, v in p["slots"].items():
            for item in (v if isinstance(v, list) else [v]):
                if isinstance(item, (int, float)) and not isinstance(item, bool):
                    slot_nums.append(float(item))
                    if not _num_ok(float(item), nums):
                        problems.append(f"{p['id']}.{k}: number {item} not in the breakdown/evidence")
                elif str(item).lower() not in strs:
                    problems.append(f"{p['id']}.{k}: '{item}' not in the breakdown/evidence")
                else:
                    slot_nums += [float(n) for n in NUM_RX.findall(str(item))]
    for n in NUM_RX.findall(explanation["text"]):
        if not any(abs(float(n) - x) < 1e-9 for x in slot_nums):
            problems.append(f"number {n} in the text does not come from a slot")
    return problems


# ───────────────────────── LLM seam (unused in this phase) ─────────────────────────
class Phraser(Protocol):
    def phrase(self, parts: list[dict], record: dict) -> str: ...


class TemplatePhraser:
    def phrase(self, parts: list[dict], record: dict) -> str:
        return " ".join(p["text"] for p in parts)


_phraser: Phraser = TemplatePhraser()


def register_phraser(p: Phraser) -> None:   # pragma: no cover - seam for the later LLM phase
    global _phraser
    _phraser = p


def get_phraser() -> Phraser:
    return _phraser


def _llm_phrasing_enabled() -> bool:
    return False   # Phase 2: always templates. A later phase flips this behind a flag + the same faithfulness check.


def dumps(x: Any) -> str:
    return json.dumps(x, sort_keys=True, default=str)
