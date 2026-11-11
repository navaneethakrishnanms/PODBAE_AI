"""Phase 1 understanding rules (NO LLM). Pure, deterministic functions over feed text, so every rule is unit-testable:

  declared_topics()   RSS / iTunes categories -> fixed taxonomy (category_map.yaml)            tier verified, method rule
  lexicon_topics()    curated keyword lexicon per taxonomy topic, with the evidence rule:
                      a topic needs >= 2 supporting episodes, or the description + >= 1 episode
  detect_guests()     podcast:person guest tags, title patterns, first-name detection, description cues
  conversational_style()  solo / co-host / interview / panel / narrative, or "unknown" when no rule is confident
  tone / values / brand-safety lexicons (word-boundary matching, >= 2 independent hits)

Model-backed fields (embedding topics, vibe) live in understanding/model_signals.py. Everything here returns its
evidence (verbatim snippets with a locator) so the profile can show WHY a value was produced."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from .rules import SAFETY_LEXICON, STOP, TONE_LEXICON
from .schemas import VALUES_TAXONOMY

HERE = Path(__file__).parent
RULES_VERSION = "rules-v2"
STYLES = ["solo_monologue", "co_hosted_banter", "interview", "panel", "narrative_storytelling"]
GUEST_FRIENDLY_SHARE = 0.30      # >= 30% of recent episodes name a guest -> guest-friendly


# ───────────────────────────── data files ─────────────────────────────
@lru_cache(maxsize=1)
def taxonomy() -> dict[str, dict]:
    return yaml.safe_load((HERE / "taxonomy.yaml").read_text(encoding="utf-8"))["topics"]


@lru_cache(maxsize=1)
def taxonomy_version() -> str:
    return yaml.safe_load((HERE / "taxonomy.yaml").read_text(encoding="utf-8"))["version"]


@lru_cache(maxsize=1)
def category_map() -> dict[str, Any]:
    return yaml.safe_load((HERE / "category_map.yaml").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def first_names() -> frozenset[str]:
    return frozenset(ln.strip().lower() for ln in (HERE / "first_names.txt").read_text(encoding="utf-8").splitlines()
                     if ln.strip() and not ln.startswith("#"))


def kw_pattern(kw: str) -> str:
    """Keywords match at a word start; short keywords (<= 4 letters, e.g. 'art', 'ai', 'eco') must match a whole word,
    so 'eco' never matches 'economy' and 'art' never matches 'start'."""
    k = kw.lower().strip()
    esc = re.escape(k).replace(r"\ ", r"\s+")
    if len(re.sub(r"\W", "", k)) <= 4 or k[-1].isdigit():
        return r"(?<![\w])" + esc + r"(?![\w])"
    return r"(?<![\w])" + esc


@lru_cache(maxsize=None)
def _rx(words: tuple[str, ...]) -> re.Pattern:
    return re.compile("|".join(kw_pattern(w) for w in words if w.strip()), re.I)


def compile_lexicon(words: list[str]) -> re.Pattern:
    return _rx(tuple(sorted({w for w in words if w and w.strip()})))


def norm_category(c: str) -> str:
    return re.sub(r"\s+", " ", c.replace("&amp;", "&").replace(" and ", " & ").strip().lower())


# ───────────────────────────── evidence helpers ─────────────────────────────
def sentence_around(text: str, start: int, end: int, limit: int = 300) -> str:
    a = max(text.rfind(".", 0, start), text.rfind("\n", 0, start), text.rfind("!", 0, start), text.rfind("?", 0, start)) + 1
    ends = [e for e in (text.find(".", end), text.find("\n", end), text.find("!", end), text.find("?", end)) if e >= 0]
    b = min(ends) + 1 if ends else len(text)
    snip = " ".join(text[a:b].split())
    if len(snip) > limit:          # keep the match inside the window
        mid = (start + end) // 2 - a
        lo = max(0, mid - limit // 2)
        snip = snip[lo: lo + limit].strip()
    return snip


@dataclass
class Doc:
    """One unit of text evidence. kind: description | episode."""
    kind: str
    ref: str               # 'show_description' or the episode id
    title: str
    text: str              # title + description (episodes) or the description

    @property
    def locator(self) -> dict:
        return {"part": "show_description"} if self.kind == "description" else {"episode_id": self.ref}


_FOOTERS = re.compile(
    r"(?:see [\w.]+\.(?:com|fm|net)/(?:privacy|listener)[^.]*\.?|[^.]*\bfor (?:more )?information about our collection and use of personal data[^.]*\.?"
    r"|hosted (?:on|by) (?:acast|anchor|buzzsprout|libsyn|podbean|simplecast|transistor|captivate|spreaker|megaphone|omny|redcircle|riverside)[^.]*\.?"
    r"|learn more about your ad[- ]?choices[^.]*\.?|visit podcastchoices\.com[^.]*\.?|(?:support|sponsor) this (?:podcast|show)[^.]*\.?"
    r"|become a (?:supporter|patron|member)[^.]*\.?|this (?:podcast|episode) is (?:powered|brought to you) by [^.]*\.?"
    r"|privacy (?:policy|information)[^.]*\.?|advertising inquiries[^.]*\.?)", re.I)
_SENT = re.compile(r"(?<=[.!?])\s+|\n+")


def strip_boilerplate(descriptions: list[str], min_share: float = 0.4) -> list[str]:
    """Remove (1) known hosting / ad-tech footers and (2) any sentence repeated in >= min_share of this show's episode
    descriptions (show-specific boilerplate such as 'Follow us on Instagram'). Without this, a privacy footer that ends
    every episode ('...use of personal data for advertising') made 'Marketing' a 20-episode topic (Phase 1 finding)."""
    cleaned = [_FOOTERS.sub(" ", d or "") for d in descriptions]
    n = len([d for d in cleaned if d.strip()])
    if n >= 3:
        counts: dict[str, int] = {}
        for d in cleaned:
            for sent in {s.strip().lower() for s in _SENT.split(d) if len(s.strip()) >= 25}:
                counts[sent] = counts.get(sent, 0) + 1
        repeated = {s for s, c in counts.items() if c / n >= min_share}
        if repeated:
            cleaned = [" ".join(s for s in _SENT.split(d) if s.strip().lower() not in repeated) for d in cleaned]
    return [re.sub(r"\s+", " ", d).strip() for d in cleaned]


def make_docs(description: str, episodes: list[tuple[str, str, str]]) -> list[Doc]:
    """episodes = [(episode_id, title, description)] newest first. Episode descriptions are de-boilerplated first."""
    docs = [Doc("description", "show_description", "", _FOOTERS.sub(" ", description or "").strip())] if (description or "").strip() else []
    clean = strip_boilerplate([d for _e, _t, d in episodes])
    docs += [Doc("episode", eid, t or "", f"{t or ''}. {c[:800]}") for (eid, t, _d), c in zip(episodes, clean)]
    return docs


def first_hit(doc: Doc, rx: re.Pattern) -> str | None:
    if doc.kind == "episode":
        m = rx.search(doc.title)
        if m:
            return doc.title[:300]
    m = rx.search(doc.text)
    return sentence_around(doc.text, m.start(), m.end()) if m else None


# ───────────────────────────── topics ─────────────────────────────
def declared_topics(categories: list[str]) -> dict[str, Any]:
    """Publisher-declared categories mapped to the taxonomy. Unmapped categories are reported, never invented."""
    cm = category_map()
    topics: list[str] = []
    groups: list[str] = []
    unmapped: list[str] = []
    tax = taxonomy()
    for c in categories or []:
        k = norm_category(c)
        hit = False
        if k in cm["map"]:
            for t in cm["map"][k]:
                if t in tax and t not in topics:
                    topics.append(t)
                    if tax[t]["group"] not in groups:
                        groups.append(tax[t]["group"])
            hit = True
        if k in cm["groups"]:
            g = cm["groups"][k]
            if g not in groups:
                groups.append(g)
            hit = True
        if not hit:
            unmapped.append(c)
    return {"topics": topics, "groups": groups, "unmapped": unmapped}


@dataclass
class TopicSupport:
    topic: str
    desc: str | None = None                                   # snippet from the description
    episodes: list[tuple[str, str]] = field(default_factory=list)   # (episode_id, snippet)
    basis: set[str] = field(default_factory=set)              # lexicon | model | declared

    def accepted(self) -> bool:
        """THE evidence rule: >= 2 supporting episodes, or description + >= 1 episode."""
        return len(self.episodes) >= 2 or (self.desc is not None and len(self.episodes) >= 1)


def lexicon_topics(docs: list[Doc]) -> dict[str, TopicSupport]:
    out: dict[str, TopicSupport] = {}
    for tid, t in taxonomy().items():
        rx = compile_lexicon(t.get("keywords") or [])
        sup = TopicSupport(tid, basis={"lexicon"})
        for d in docs:
            snip = first_hit(d, rx)
            if snip is None:
                continue
            if d.kind == "description":
                sup.desc = snip
            else:
                sup.episodes.append((d.ref, snip))
        if sup.desc or sup.episodes:
            out[tid] = sup
    return out


def merge_topic_support(*supports: dict[str, TopicSupport]) -> dict[str, TopicSupport]:
    out: dict[str, TopicSupport] = {}
    for sup in supports:
        for tid, s in sup.items():
            cur = out.setdefault(tid, TopicSupport(tid))
            cur.desc = cur.desc or s.desc
            have = {e for e, _ in cur.episodes}
            cur.episodes += [(e, sn) for e, sn in s.episodes if e not in have]
            cur.basis |= s.basis
    return out


def finalize_topics(supports: dict[str, TopicSupport], declared: list[str], max_topics: int = 8) -> tuple[list[dict], list[dict]]:
    """Apply the evidence rule. Returns (accepted topic dicts sorted by weight, dropped topics with the reason)."""
    tax = taxonomy()
    kept, dropped = [], []
    for tid, s in supports.items():
        info = {"id": tid, "name": tax[tid]["label"], "group": tax[tid]["group"], "episodes": len(s.episodes),
                "in_description": s.desc is not None, "basis": sorted(s.basis | ({"declared"} if tid in declared else set()))}
        if not s.accepted():
            dropped.append({**info, "reason": "needs >= 2 episodes, or description + 1 episode"})
            continue
        w = 0.25 + 0.1 * min(6, len(s.episodes)) + (0.15 if s.desc else 0) + (0.15 if tid in declared else 0)
        w -= 0.1 if s.basis == {"model"} else 0          # embedding-only support counts a little less
        info["weight"] = round(max(0.05, min(1.0, w)), 2)
        kept.append(info)
    kept.sort(key=lambda x: (-x["weight"], x["id"]))
    # secondary topics need evidence comparable to the main topic (>= 50% of the top weight); weaker ones are reported
    # as dropped instead of diluting the profile
    if kept:
        floor = 0.5 * kept[0]["weight"]
        dropped += [{**t, "reason": "much weaker evidence than the main topic"} for t in kept if t["weight"] < floor]
        kept = [t for t in kept if t["weight"] >= floor]
    return kept[:max_topics], dropped


# ───────────────────────────── guests ─────────────────────────────
NAME = r"(?:Dr\.?\s+|Prof\.?\s+)?[A-Z][a-zA-Z'’.\-]+(?:\s+(?:[A-Z]\.\s+)?(?:de |van |von |da |del |la |le |al |bin )?[A-Z][a-zA-Z'’\-]+){1,2}"
_WITH = re.compile(r"(?:\bwith\b|\bw/)\s+(" + NAME + ")")                           # 'with X Y': X must be a known first name
_FEAT = re.compile(r"(?:\bfeat\.?|\bft\.|\bfeaturing\b|\bguest:|\bft\b)\s+(" + NAME + ")")  # explicit credit: looser
_PIPE_END = re.compile(r"[|–—]\s*(" + NAME + r")\s*$")
_EP_PREFIX = r"^(?:(?:(?i:ep(?:isode)?)\.?\s*#?\d+|#\d+|\d+)\s*[:.|–—-]\s*)?"
_NAME_ON = re.compile(_EP_PREFIX + r"(" + NAME + r")\s+(?:on|talks|explains|shares|discusses|returns|joins)\b")
_NAME_COLON = re.compile(_EP_PREFIX + r"(" + NAME + r")\s*[:|–—]\s+\S")
_TITLE_CUES = re.compile(r"\b(?:interview(?:s|ed|ing)?|in conversation with|conversation with|chats? with|talks? with|sits? down with|"
                         r"speaks? with|joined by|joins (?:us|me|the show)|special guest|guest (?:episode|host|appearance))\b", re.I)
_DESC_CUES = re.compile(r"\b(?:my guest|our guest|today'?s guest|this week'?s guest|guests? (?:is|are|was|were)|joined by|joins (?:me|us)|"
                        r"i (?:sit|sat) down with|we (?:sit|sat) down with|i (?:talk|chat|speak|spoke|talked|chatted) (?:with|to)|"
                        r"we (?:talk|chat|speak|spoke|talked|chatted) (?:with|to)|interview(?:s|ed)? with|in conversation with|welcome(?:s)? back)\b", re.I)
TITLE_STOP = STOP | {
    "part", "season", "episode", "special", "guest", "live", "show", "podcast", "interview", "update", "edition", "bonus", "finale", "review",
    "recap", "news", "week", "day", "night", "how", "why", "what", "when", "where", "who", "best", "top", "new", "old", "big", "little",
    "great", "good", "bad", "real", "true", "final", "first", "last", "next", "story", "stories", "love", "life", "world", "time", "home",
    "family", "kids", "food", "money", "business", "health", "music", "game", "games", "year", "christmas", "easter", "halloween",
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday", "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december", "spring", "summer", "fall", "autumn", "winter", "mailbag", "listener",
    "questions", "q&a", "ama", "trailer", "intro", "chapter", "lesson", "daily", "weekly", "morning", "evening", "ask", "god", "lord",
    "jesus", "christ", "holy", "spirit", "church", "bible", "book", "books", "movie", "film", "series", "star", "wars", "united", "states",
    "american", "america", "new", "york", "city", "north", "south", "east", "west", "state", "national", "mental", "black", "white"}


def _looks_like_person(name: str, hosts: set[str], strict: bool) -> bool:
    toks = [t.strip(".'’") for t in re.sub(r"^(Dr\.?|Prof\.?)\s+", "", name).split()]
    if len(toks) < 2 or len(toks) > 3:
        return False
    low = [t.lower() for t in toks]
    if any(t in TITLE_STOP for t in low):
        return False
    if " ".join(low) in hosts:          # a host is never counted as a guest
        return False
    if strict:
        return low[0] in first_names()
    return True


def host_names(show_persons: list[dict], author: str | None, recurring: set[str] | None = None) -> set[str]:
    names: set[str] = set()
    for p in show_persons or []:
        if (p.get("role") or "host").lower() in ("host", "co-host", "cohost"):
            names.add(p["name"].lower().strip())
    for part in re.split(r"\s*(?:&|\band\b|,|\+|/|\bwith\b)\s*", author or "", flags=re.I):
        if part.strip():
            names.add(part.strip().lower())
    return names | (recurring or set())


@dataclass
class GuestEpisode:
    episode_id: str
    title: str
    guest: bool
    basis: str | None = None
    name: str | None = None


def detect_guest_episode(eid: str, title: str, desc: str, persons: list[dict], hosts: set[str]) -> GuestEpisode:
    if any((p.get("role") or "").lower() == "guest" for p in persons or []):
        g = next(p["name"] for p in persons if (p.get("role") or "").lower() == "guest")
        return GuestEpisode(eid, title, True, "podcast:person role=guest", g)
    t = title or ""
    for rx, basis, strict in ((_FEAT, "title: feat./ft. + name", False), (_WITH, "title: 'with' + name", True),
                              (_PIPE_END, "title: '| Name'", True),
                              (_NAME_ON, "title: 'Name on topic'", True), (_NAME_COLON, "title: 'Name: topic'", True)):
        m = rx.search(t)
        if m and _looks_like_person(m.group(1), hosts, strict):
            return GuestEpisode(eid, title, True, basis, m.group(1))
    if _TITLE_CUES.search(t):
        return GuestEpisode(eid, title, True, "title: interview / conversation cue")
    for m in re.finditer(NAME, t):
        if _looks_like_person(m.group(0), hosts, strict=True):
            return GuestEpisode(eid, title, True, "title: person name", m.group(0))
    head = (desc or "")[:600]
    if _DESC_CUES.search(head):
        return GuestEpisode(eid, title, True, "description: guest cue")
    return GuestEpisode(eid, title, False)


def detect_guests(episodes: list[tuple[str, str, str, list[dict]]], show_persons: list[dict], author: str | None) -> dict[str, Any]:
    """episodes = [(id, title, description, persons)] newest first. Names that appear in most episodes are treated as
    hosts (a recurring co-host is not a guest)."""
    base_hosts = host_names(show_persons, author)
    counts: dict[str, int] = {}
    for _eid, t, _d, _p in episodes:
        for m in set(re.findall(NAME, t or "")):
            counts[m.lower()] = counts.get(m.lower(), 0) + 1
    n = len(episodes)
    recurring = {k for k, v in counts.items() if n >= 4 and v / n > 0.5}
    hosts = base_hosts | recurring
    res = [detect_guest_episode(eid, t, d, p, hosts) for eid, t, d, p in episodes]
    g = [r for r in res if r.guest]
    share = round(len(g) / n, 2) if n else 0.0
    person_based = sum(1 for r in g if r.basis and r.basis.startswith("podcast:person"))
    return {"share": share, "guest_episodes": len(g), "episodes_checked": n, "guest_friendly": share >= GUEST_FRIENDLY_SHARE,
            "basis": "podcast:person guest tags" if g and person_based >= len(g) / 2 else "title / description rules",
            "person_tagged": person_based, "examples": [{"episode_id": r.episode_id, "title": r.title, "rule": r.basis, "name": r.name}
                                                         for r in g[:3]],
            "hosts_excluded": sorted(h for h in hosts if h)[:6], "threshold": GUEST_FRIENDLY_SHARE}


# ───────────────────────────── conversational style ─────────────────────────────
_CO_HOST = re.compile(r"\b(?:co-?hosts?|co host|cohosted|your hosts|our hosts|two friends|best friends|two (?:guys|girls|moms|dads|sisters|brothers|"
                      r"buddies|comedians|nerds)|the duo|husband and wife|wife and husband|married couple|hosted by \w+ (?:\w+ )?(?:and|&) \w+)\b", re.I)
_PANEL = re.compile(r"\b(?:panel|panelists|roundtable|round table|round-table|the crew|our team of hosts|hosts? \w+, \w+,? (?:and|&) \w+)\b", re.I)
_NARR = re.compile(r"\b(?:true story|documentary|docuseries|narrative|investigative|investigation|audio drama|serialized|limited series|"
                   r"chapter \d+|told in \w+ parts|a story about|the story of|storytelling|unfolds)\b", re.I)
_SOLO_I = re.compile(r"(?:\bI\b|\bI'm\b|\bI’m\b|\bI've\b|\bmy name is\b|\bjoin me\b|\bI share\b|\bmy own\b)")
_WE = re.compile(r"\b(?:we|we're|we’re|our|us)\b", re.I)
_PART = re.compile(r"\b(?:part|pt\.?|chapter)\s*\d+\b", re.I)
_ORG = re.compile(r"\b(?:podcast|podcasts|media|network|productions?|llc|inc\.?|studios?|radio|show|fm|church|ministries|university|"
                  r"college|foundation|institute|group|company|co\.|news|magazine)\b", re.I)


def count_people_in_author(author: str | None) -> int:
    if not author or _ORG.search(author):
        return 0
    parts = [p for p in re.split(r"\s*(?:&|\band\b|,|\+|/)\s*", author, flags=re.I) if p.strip()]
    return len([p for p in parts if re.match(r"^[A-Z][\w'’.-]+", p.strip())])


def conversational_style(*, description: str, episode_titles: list[str], hosts_tagged: int, author: str | None, guest_share: float,
                         avg_minutes: float | None, show_type: str | None) -> dict[str, Any]:
    """Score each style from independent rules; pick the best only if it is confident and clearly ahead, otherwise
    'unknown' (never a guess). Returns value, confidence, scores and the signals that fired."""
    d = description or ""
    sig: dict[str, list[str]] = {s: [] for s in STYLES}
    score = {s: 0.0 for s in STYLES}

    def add(style: str, pts: float, why: str) -> None:
        score[style] += pts
        sig[style].append(why)

    n_author = count_people_in_author(author)
    n_hosts = max(hosts_tagged, n_author)
    if guest_share >= 0.6:
        add("interview", 1.4, f"{int(guest_share * 100)}% of recent episodes name a guest")
    elif guest_share >= 0.4:
        add("interview", 1.0, f"{int(guest_share * 100)}% of recent episodes name a guest")
    if re.search(r"\binterview", d, re.I):
        add("interview", 0.5, "description mentions interviews")
    if n_hosts >= 3:
        add("panel", 1.0, f"{n_hosts} hosts ({'podcast:person' if hosts_tagged >= 3 else 'author field'})")
    if _PANEL.search(d):
        add("panel", 0.8, "description: panel / roundtable cue")
    if n_hosts == 2:
        add("co_hosted_banter", 1.0, f"2 hosts ({'podcast:person' if hosts_tagged == 2 else 'author field'})")
    if _CO_HOST.search(d):
        add("co_hosted_banter", 0.8, "description: co-host cue")
    we, i_ = len(_WE.findall(d)), len(_SOLO_I.findall(d))
    if we >= 3 and we > 2 * i_ and n_hosts != 1:
        add("co_hosted_banter", 0.3, "description written as 'we'")
    if (show_type or "").lower() == "serial":
        add("narrative_storytelling", 1.0, "itunes:type = serial")
    if _NARR.search(d):
        add("narrative_storytelling", 0.7, "description: narrative / documentary cue")
    parts = sum(1 for t in episode_titles if _PART.search(t or ""))
    if episode_titles and parts / len(episode_titles) >= 0.3:
        add("narrative_storytelling", 0.4, f"{parts} of {len(episode_titles)} titles are numbered parts/chapters")
    if i_ >= 2 and i_ >= we and guest_share < 0.25 and n_hosts <= 1:
        add("solo_monologue", 0.9, "description written in first person singular")
    if n_hosts == 1 and guest_share < 0.25:
        add("solo_monologue", 0.4, "one named host")
    if n_author == 1 and hosts_tagged <= 1 and guest_share <= 0.1 and not re.search(r"\b(?:interview|conversation|guests?|co-?host|panel)", d, re.I):
        add("solo_monologue", 0.6, "one person publishes it, almost no guests named, no interview/co-host cues")
    if avg_minutes is not None and avg_minutes < 15 and guest_share < 0.25 and n_hosts <= 1:
        add("solo_monologue", 0.3, f"short episodes (avg {avg_minutes:.0f} min)")
    # strong guest presence beats host-count cues: co-hosted shows that interview guests are interviews
    if guest_share >= 0.4:
        score["solo_monologue"] *= 0.3
    ranked = sorted(score.items(), key=lambda kv: -kv[1])
    (best, s1), (_, s2) = ranked[0], ranked[1]
    if s1 < 1.0 or s1 - s2 < 0.3:
        return {"value": "unknown", "confidence": 0.15, "scores": {k: round(v, 2) for k, v in score.items()},
                "signals": {k: v for k, v in sig.items() if v},
                "reason": "no rule was confident" if s1 < 1.0 else f"tie between {ranked[0][0]} and {ranked[1][0]}"}
    conf = round(min(0.8, 0.45 + 0.12 * (s1 - 1.0) + 0.05 * len(sig[best]) + 0.05 * min(1.0, s1 - s2)), 2)
    return {"value": best, "confidence": conf, "scores": {k: round(v, 2) for k, v in score.items()}, "signals": {k: v for k, v in sig.items() if v}}


# ───────────────────────────── tone / values / brand safety (lexicons) ─────────────────────────────
TONES = list(TONE_LEXICON)


def lexicon_labels(docs: list[Doc], lexicon: dict[str, list[str]], min_docs: int = 2) -> dict[str, list[tuple[Doc, str]]]:
    """label -> [(doc, snippet)] for labels whose words occur in >= min_docs separate docs."""
    out: dict[str, list[tuple[Doc, str]]] = {}
    for label, words in lexicon.items():
        rx = compile_lexicon([w.strip() for w in words])
        hits = [(d, sn) for d in docs if (sn := first_hit(d, rx))]
        if len(hits) >= min_docs:
            out[label] = hits
    return out


def tone_values_safety(docs: list[Doc], explicit: bool | None) -> dict[str, Any]:
    tone = lexicon_labels(docs, TONE_LEXICON)
    values = lexicon_labels(docs, VALUES_TAXONOMY)
    safety = lexicon_labels(docs, SAFETY_LEXICON)
    flags = {k: [(d.locator, sn) for d, sn in v[:2]] for k, v in safety.items()}
    if explicit and "profanity" not in flags:
        flags["profanity"] = [({"part": "itunes:explicit"}, "Feed is marked explicit (itunes:explicit = yes)")]
    return {"tone": {k: [(d.locator, sn) for d, sn in v[:2]] for k, v in sorted(tone.items(), key=lambda kv: -len(kv[1]))[:4]},
            "values": {k: [(d.locator, sn) for d, sn in v[:2]] for k, v in sorted(values.items(), key=lambda kv: -len(kv[1]))[:6]},
            "brand_safety_flags": flags}
