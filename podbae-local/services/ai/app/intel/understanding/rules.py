"""Rules first: facts computed from feed data, no model involved. Plus the heuristic text analyser that backs both the
mock LLM provider and the rules-only fallback (low confidence)."""
from __future__ import annotations

import re
import statistics
from collections import Counter
from datetime import datetime
from typing import Any

from ..normalize import activity_status, cadence_stats
from .schemas import FORBIDDEN_TEXT, VALUES_TAXONOMY, VIBE_TERMS

GUEST_TITLE = re.compile(r"(\bwith\s+[A-Z][\w'’.-]+(?:\s+[A-Z][\w'’.-]+)?|\bfeat(?:uring|\.)\s+[A-Z]|\bft\.?\s+[A-Z]|"
                         r"\binterview\b|\bconversation with\b|\bin conversation\b|\bguest\b|\w+\s+(?:joins|talks|chats)\b|"
                         r"^\s*(?:ep(?:isode)?\.?\s*\d+\s*[:\-–]\s*)?[A-Z][a-z]+ [A-Z][a-z]+\s*[:\-–|])")


def compute_facts(feed_dates: list[datetime | None], durations: list[int | None], titles: list[str],
                  episode_persons: list[list[dict]], show_persons: list[dict], explicit: bool | None,
                  at: datetime | None = None) -> dict[str, Any]:
    dates = [d for d in feed_dates if d]
    st = cadence_stats(dates)
    durs = [d for d in durations if d]
    guest_by_person = sum(1 for p in episode_persons if any((x.get("role") or "").lower() == "guest" for x in p))
    guest_by_title = sum(1 for t in titles if GUEST_TITLE.search(t or ""))
    n = max(1, len(titles))
    facts: dict[str, Any] = {
        "episode_count": len(titles),
        "last_published": st["last_published"].isoformat() + "Z" if st["last_published"] else None,
        "cadence_days": st["median_gap_days"],
        "avg_episode_minutes": round(statistics.mean(durs) / 60, 1) if durs else None,
        "activity_status": activity_status(dates, at),
        "explicit": explicit,
        "hosts": [p["name"] for p in show_persons if (p.get("role") or "host").lower() == "host"][:6] or None,
        "guests_present": None,
    }
    if guest_by_person:
        facts["guests_present"] = {"value": True, "basis": "podcast:person guest tags", "share": round(guest_by_person / n, 2)}
    elif titles:
        share = guest_by_title / n
        facts["guests_present"] = {"value": share >= 0.25, "basis": "title patterns", "share": round(share, 2)}
    return facts


# ───────────────────────────── heuristic text analysis ─────────────────────────────
STOP = set("""the a an and or of to in on for with is are was were be been it this that these those from at by as we you i my our
your they their he she his her its not but so if then than about into out up down over under again more most some any each
just can will would could should have has had do does did what which who whom how why when where all also there here
episode episodes podcast show season new week today us me us get got going really very one two three part live ep
la el los las un una y de del en con por para que es se su sus lo al como mas más pero""".split())

VIBE_LEXICON: dict[str, list[str]] = {
    "Casual": ["chat", "hang out", "hangout", "buddies", "friends", "casual", "banter", "ramble", "bunch of"],
    "Compelling": ["gripping", "mystery", "true crime", "investigat", "untold", "shocking", "unsolved", "story of", "dark"],
    "Educational": ["learn", "explain", "lesson", "guide", "how to", "tutorial", "science", "history", "teach", "course",
                    "beginner", "explore", "understand"],
    "Energetic": ["hype", "energy", "fired up", "pump", "amped", "fast-paced", "high-energy", "intense"],
    "Humorous": ["funny", "comedy", "laugh", "hilarious", "jokes", "humor", "comedian", "sketch", "roast"],
    "Inspirational": ["inspir", "motivat", "success", "dream", "empower", "mindset", "overcome", "purpose"],
    "Personal Narrative": ["my story", "memoir", "personal", "my life", "my journey", "confession", "diary", "i share"],
    "Professional": ["business", "career", "industry", "leadership", "marketing", "strategy", "executive", "ceo", "professional",
                     "enterprise", "b2b"],
    "Reflective": ["reflect", "thoughtful", "philosoph", "contemplat", "essay", "ponder", "meaning of"],
    "Relaxed": ["relax", "calm", "sleep", "soothing", "chill", "gentle", "cozy", "unwind"],
    "Uplifting": ["positive", "joy", "hope", "gratitude", "happy", "uplift", "feel-good", "celebrat"],
    "Wellness-Focused": ["wellness", "health", "fitness", "nutrition", "therapy", "mental health", "yoga", "self-care", "mindful"],
}

TONE_LEXICON = {"warm": ["welcome", "friends", "together", "heart"], "witty": ["funny", "joke", "banter", "comedy"],
                "serious": ["investigat", "crisis", "analysis", "report"], "curious": ["why", "explore", "discover", "wonder"],
                "calm": ["calm", "relax", "gentle", "soothing"], "motivational": ["motivat", "inspir", "success"],
                "conversational": ["chat", "conversation", "talk"], "authoritative": ["expert", "research", "data", "professor"]}

SAFETY_LEXICON = {"profanity": ["fuck", "shit", "damn", "bitch", "explicit language"], "adult_themes": ["sex", "erotic", "nsfw", "adult"],
                  "violence": ["murder", "killer", "violent", "war crime", "homicide"], "politics": ["election", "politic", "congress", "democrat", "republican", "liberal", "conservative"],
                  "religion": ["church", "bible", "religio", "quran", "prayer"], "health_claims": ["cure", "detox", "miracle", "supplement"],
                  "conspiracy": ["conspiracy", "cover-up", "deep state", "illuminati", "flat earth"], "gambling": ["betting", "casino", "gambl", "sportsbook"],
                  "alcohol_drugs": ["alcohol", "cocktail", "drunk", "weed", "marijuana", "psychedelic", "drug"],
                  "controversial_topics": ["controvers", "cancel culture", "culture war"]}

STYLE_HINTS = [("narrative_storytelling", ["true crime", "story of", "narrat", "documentary", "episodes tell", "storytelling"]),
               ("educational_lecture", ["lecture", "lesson", "course", "tutorial", "explained", "explains", "how to"]),
               ("panel", ["panel", "roundtable", "round table", "our hosts", "the crew"]),
               ("interview", ["interview", "guests", "conversations with", "sit down with", "talks to", "chats with"]),
               ("co_hosted_banter", ["co-host", "cohost", "co host", "banter", "your hosts", "we chat", "best friends", "duo"])]


def _hits(text: str, words: list[str]) -> int:
    return sum(text.count(w) for w in words)


def tokens(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-zA-ZÀ-ÿ][a-zA-ZÀ-ÿ']{3,}(?:-[a-zA-ZÀ-ÿ']{2,})*", text.lower()) if w not in STOP and not FORBIDDEN_TEXT.search(w)]


def heuristic_analysis(*, title: str, description: str, categories: list[str], episode_titles: list[str],
                       episode_texts: list[str], guest_share: float, n_hosts: int) -> dict[str, Any]:
    """Deterministic analysis of show text. Returns a dict shaped like `Extraction` (minus evidence)."""
    body = " ".join([title, description, " ".join(episode_titles), " ".join(episode_texts)]).lower()
    # topics: categories first, then frequent content words (bigram-ish via simple frequency)
    topics: list[tuple[str, float]] = []
    for c in categories[:4]:
        if not FORBIDDEN_TEXT.search(c):
            topics.append((c.strip()[:60], 0.8))
    freq = Counter(tokens(" ".join([title, description, " ".join(episode_titles)])))
    for w, c in freq.most_common(8):
        if c >= 2 and not any(w in t[0].lower() for t in topics) and len(topics) < 6:
            topics.append((w, round(min(0.6, 0.15 + 0.08 * c), 2)))
    if not topics:
        topics = [("general interest", 0.3)]
    vibe = {v: 0.0 for v in VIBE_TERMS}
    for v, words in VIBE_LEXICON.items():
        vibe[v] = round(min(1.0, _hits(body, words) / 4), 3)
    tone = [t for t, ws in TONE_LEXICON.items() if _hits(body, ws) >= 1][:4]
    style = "mixed"
    scores = {s: _hits(body, ws) for s, ws in STYLE_HINTS}
    if guest_share >= 0.4:
        style = "interview"
    elif max(scores.values()) > 0:
        style = max(scores, key=lambda k: scores[k])
    elif n_hosts == 1 and guest_share < 0.15:
        style = "solo_monologue"
    elif n_hosts >= 2:
        style = "co_hosted_banter"
    values = [k for k, ws in VALUES_TAXONOMY.items() if _hits(body, [w.strip() for w in ws]) >= 1][:6]
    flags = [f for f, ws in SAFETY_LEXICON.items() if _hits(body, ws) >= 1]
    top = [t[0] for t in topics[:2]]
    aud = f"People interested in {' and '.join(top)}." if top else "General-interest listeners."
    return {"topics": [{"name": n, "weight": w} for n, w in topics[:8]], "vibe": vibe, "tone": tone,
            "conversational_style": style, "values": values, "guest_friendliness": round(min(1.0, guest_share * 1.5), 2),
            "brand_safety_flags": flags, "likely_audience": _clean_aud(aud)}


def _sentence_around(text: str, needle: str) -> str | None:
    i = text.lower().find(needle.lower())
    if i < 0:
        return None
    start = max(text.rfind(".", 0, i), text.rfind("\n", 0, i)) + 1
    ends = [e for e in (text.find(".", i), text.find("\n", i)) if e >= 0]
    end = min(ends) + 1 if ends else len(text)
    snip = " ".join(text[start:end].split())
    return snip[:300] if len(snip) >= 3 else None


def find_evidence(sources: dict[str, str], analysis: dict[str, Any], limit: int = 12) -> list[dict[str, str]]:
    """Real snippets (verbatim substrings of the supplied text) that support each inferred field."""
    out: list[dict[str, str]] = []

    def cite(field: str, words: list[str]) -> None:
        for label, text in sources.items():
            for w in words:
                snip = _sentence_around(text, w)
                if snip:
                    out.append({"field": field, "source": label, "snippet": snip})
                    return

    for v, score in analysis["vibe"].items():
        if score >= 0.25:
            cite("vibe", VIBE_LEXICON[v])
    for k in analysis["values"]:
        cite("values", [w.strip() for w in VALUES_TAXONOMY[k]])
    for f in analysis["brand_safety_flags"]:
        cite("brand_safety_flags", SAFETY_LEXICON[f])
    for t in analysis["topics"][:2]:
        cite("topics", [t["name"]])
    return out[:limit]


def _clean_aud(s: str) -> str:
    return s if not FORBIDDEN_TEXT.search(s) else "Listeners interested in this show's topics."
