"""RSS connector: httpx + feedparser (core fields) + tolerant lxml pass (podcast: namespace)."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

import feedparser
import httpx
from lxml import etree

from ..config import get_settings
from ..trust.sanitize import clean_text, clean_title
from .base import ConnectorResult, FeedTooLarge, Timer, fetch_bytes, validate_url

NAME = "rss"
KIND = "rss"
EXPECTED_FIELDS = ["title", "description", "language", "link", "image", "author", "categories", "explicit",
                   "podcast_guid", "new_feed_url", "episodes", "episode_dates", "episode_durations",
                   "episode_descriptions", "transcripts", "persons"]


@dataclass
class ParsedEpisode:
    guid: str
    title: str
    description: str
    published_at: datetime | None
    duration_sec: int | None
    explicit: bool | None
    audio_url: str | None
    transcript_url: str | None
    transcript_type: str | None
    persons: list[dict]
    season: int | None = None
    episode_no: int | None = None

    def content_hash(self) -> str:
        raw = "|".join([self.title, self.description, str(self.duration_sec), self.audio_url or "", self.transcript_url or ""])
        return hashlib.sha256(raw.encode()).hexdigest()


@dataclass
class ParsedFeed:
    title: str = ""
    description: str = ""
    language: str | None = None
    link: str | None = None
    image: str | None = None
    author: str | None = None
    categories: list[str] = field(default_factory=list)
    explicit: bool | None = None
    podcast_guid: str | None = None
    new_feed_url: str | None = None
    persons: list[dict] = field(default_factory=list)
    episodes: list[ParsedEpisode] = field(default_factory=list)
    total_items_in_feed: int = 0
    malformed: bool = False


@dataclass
class FetchOutcome:
    status: str                       # ok | not_modified | error
    result: ConnectorResult
    feed: ParsedFeed | None = None
    final_url: str | None = None
    permanent_redirect_to: str | None = None
    etag: str | None = None
    last_modified: str | None = None
    body_hash: str | None = None


def _dur(v: Any) -> int | None:
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    try:
        if ":" in s:
            parts = [int(float(p)) for p in s.split(":")]
            sec = 0
            for p in parts[-3:]:
                sec = sec * 60 + p
            return sec if sec > 0 else None
        n = int(float(s))
        return n if n > 0 else None
    except ValueError:
        return None


def _explicit(v: Any) -> bool | None:
    if v is None:
        return None
    s = str(v).strip().lower()
    if s in ("yes", "true", "explicit"):
        return True
    if s in ("no", "false", "clean"):
        return False
    return None


def _dt(entry: Any) -> datetime | None:
    p = entry.get("published_parsed") or entry.get("updated_parsed")
    if p:
        try:
            return datetime(*p[:6])
        except (TypeError, ValueError):
            pass
    raw = entry.get("published") or entry.get("updated")
    if raw:
        try:
            d = parsedate_to_datetime(raw)
            return d.astimezone(timezone.utc).replace(tzinfo=None) if d.tzinfo else d
        except (TypeError, ValueError):
            return None
    return None


def _local(tag: Any) -> tuple[str, str]:
    if not isinstance(tag, str):
        return "", ""
    if tag.startswith("{"):
        ns, _, name = tag[1:].partition("}")
        return ns, name
    return "", tag


def _is_podcast_ns(ns: str) -> bool:
    return "podcastindex" in ns.lower() or "podcast-namespace" in ns.lower()


def _podcast_namespace_pass(content: bytes) -> tuple[dict, dict[str, dict]]:
    """Tolerant (recover=True) extraction of podcast: tags, keyed by item guid. Returns (channel, items)."""
    parser = etree.XMLParser(recover=True, resolve_entities=False, no_network=True, huge_tree=True, remove_comments=True)
    chan: dict = {"persons": [], "guid": None, "new_feed_url": None}
    items: dict[str, dict] = {}
    try:
        root = etree.fromstring(content, parser=parser)
    except etree.XMLSyntaxError:
        return chan, items
    if root is None:
        return chan, items
    channel = root.find("channel")
    if channel is None:
        channel = next((c for c in root.iter() if _local(c.tag)[1] == "channel"), None)
    if channel is None:
        return chan, items
    for el in channel:
        ns, name = _local(el.tag)
        if _is_podcast_ns(ns) and name == "guid" and el.text:
            chan["guid"] = el.text.strip()
        elif "itunes" in ns and name == "new-feed-url" and el.text:
            chan["new_feed_url"] = el.text.strip()
        elif _is_podcast_ns(ns) and name == "person" and el.text:
            chan["persons"].append({"name": clean_title(el.text), "role": el.get("role") or "host"})
        elif name == "item":
            guid = None
            rec: dict = {"persons": [], "transcripts": []}
            for sub in el:
                sns, sname = _local(sub.tag)
                if sname == "guid" and sub.text:
                    guid = sub.text.strip()
                elif _is_podcast_ns(sns) and sname == "transcript" and sub.get("url"):
                    rec["transcripts"].append({"url": sub.get("url"), "type": sub.get("type")})
                elif _is_podcast_ns(sns) and sname == "person" and sub.text:
                    rec["persons"].append({"name": clean_title(sub.text), "role": sub.get("role") or "guest"})
            if guid:
                items[guid] = rec
    return chan, items


def parse_feed_bytes(content: bytes) -> ParsedFeed:
    cfg = get_settings()
    d = feedparser.parse(content)
    feed = d.get("feed", {}) or {}
    entries = d.get("entries", []) or []
    if not entries and not feed.get("title"):
        raise ValueError("not a podcast/RSS feed (no channel title or items found)")
    chan, ns_items = _podcast_namespace_pass(content)
    cats: list[str] = []
    for t in feed.get("tags", []) or []:
        term = (t.get("term") or "").strip()
        if term and term not in cats:
            cats.append(clean_title(term))
    pf = ParsedFeed(
        title=clean_title(feed.get("title")), description=clean_text(feed.get("subtitle") or feed.get("summary") or feed.get("description")),
        language=(feed.get("language") or "").strip().lower() or None, link=feed.get("link"),
        image=(feed.get("image") or {}).get("href") if isinstance(feed.get("image"), dict) else None,
        author=clean_title(feed.get("author") or feed.get("itunes_author")) or None, categories=cats[:10],
        explicit=_explicit(feed.get("itunes_explicit")), podcast_guid=chan["guid"],
        new_feed_url=chan["new_feed_url"] or feed.get("itunes_new_feed_url"), persons=chan["persons"],
        total_items_in_feed=len(entries), malformed=bool(d.get("bozo")))
    for e in entries:
        audio = next((en.get("href") for en in e.get("enclosures", []) if "audio" in (en.get("type") or "audio") or en.get("href")), None)
        guid = e.get("id") or e.get("guid") or audio or e.get("link") or hashlib.sha1(((e.get("title") or "") + str(e.get("published"))).encode()).hexdigest()
        content_html = ""
        if e.get("content"):
            content_html = e["content"][0].get("value", "")
        raw_desc = content_html if len(content_html) > len(e.get("summary") or "") else (e.get("summary") or "")
        ns = ns_items.get(guid, {"persons": [], "transcripts": []})
        tr = ns["transcripts"][0] if ns["transcripts"] else {}
        pf.episodes.append(ParsedEpisode(
            guid=str(guid)[:500], title=clean_title(e.get("title")), description=clean_text(raw_desc), published_at=_dt(e),
            duration_sec=_dur(e.get("itunes_duration")), explicit=_explicit(e.get("itunes_explicit")), audio_url=audio,
            transcript_url=tr.get("url"), transcript_type=tr.get("type"), persons=ns["persons"],
            season=int(e["itunes_season"]) if str(e.get("itunes_season", "")).isdigit() else None,
            episode_no=int(e["itunes_episode"]) if str(e.get("itunes_episode", "")).isdigit() else None))
    # newest first, keep the latest N (metadata window); undated items sink
    pf.episodes.sort(key=lambda x: x.published_at or datetime.min, reverse=True)
    pf.episodes = pf.episodes[: cfg.keep_episodes]
    return pf


def _fields_of(pf: ParsedFeed) -> dict[str, Any]:
    eps = pf.episodes
    return {
        "title": pf.title, "description": pf.description, "language": pf.language, "link": pf.link, "image": pf.image,
        "author": pf.author, "categories": pf.categories, "explicit": pf.explicit, "podcast_guid": pf.podcast_guid,
        "new_feed_url": pf.new_feed_url, "persons": pf.persons or any(e.persons for e in eps) or None,
        "episodes": len(eps) or None,
        "episode_dates": any(e.published_at for e in eps) or None,
        "episode_durations": any(e.duration_sec for e in eps) or None,
        "episode_descriptions": any(len(e.description) > 40 for e in eps) or None,
        "transcripts": any(e.transcript_url for e in eps) or None,
    }


def fetch_feed(client: httpx.Client, url: str, *, etag: str | None = None, last_modified: str | None = None) -> FetchOutcome:
    cfg = get_settings()
    res = ConnectorResult(connector=NAME)
    with Timer() as t:
        try:
            validate_url(url)
            headers = {}
            if etag:
                headers["If-None-Match"] = etag
            if last_modified:
                headers["If-Modified-Since"] = last_modified
            resp, body = fetch_bytes(client, url, max_bytes=cfg.max_feed_bytes, headers=headers)
            final = str(resp.url)
            perm = None
            for h in resp.history:
                if h.status_code in (301, 308):
                    perm = str(h.headers.get("location") or "") or None
            if perm and perm.startswith("/"):
                perm = final
            if resp.status_code == 304:
                res.fields = {}
                out = FetchOutcome("not_modified", res, None, final, perm, etag, last_modified)
            elif resp.status_code >= 400:
                raise RuntimeError(f"HTTP {resp.status_code}")
            else:
                pf = parse_feed_bytes(body)
                res.fields = _fields_of(pf)
                out = FetchOutcome("ok", res, pf, final, perm, resp.headers.get("etag"), resp.headers.get("last-modified"),
                                   hashlib.sha256(body).hexdigest())
        except (httpx.HTTPError, ValueError, RuntimeError, FeedTooLarge) as exc:
            res.ok, res.error = False, f"{type(exc).__name__}: {exc}"[:300]
            out = FetchOutcome("error", res)
    res.duration_ms = t.ms
    return out


_SRT_TS = re.compile(r"^\d{1,2}:\d\d:\d\d[,.]\d{1,3}\s*-->.*$|^\d+$|^WEBVTT.*$|^NOTE\b.*$", re.M)
_TAG = re.compile(r"<[^>]+>")


def parse_transcript(body: bytes, content_type: str | None, declared_type: str | None) -> tuple[str, str]:
    """Return (plain_text, format). Supports text/plain, SRT, VTT, HTML, podcast-namespace JSON."""
    raw = body.decode("utf-8", errors="replace")
    t = (declared_type or content_type or "").lower()
    if "json" in t or raw.lstrip().startswith("{"):
        import json
        try:
            data = json.loads(raw)
            segs = data.get("segments", data if isinstance(data, list) else [])
            text = " ".join(str(s.get("body", s.get("text", ""))) for s in segs if isinstance(s, dict))
            return clean_text(text, 200_000), "json"
        except ValueError:
            pass
    if "vtt" in t or "srt" in t or "-->" in raw[:2000]:
        return clean_text(_SRT_TS.sub("", raw).replace("\r", ""), 200_000), "subtitle"
    if "html" in t or "<html" in raw[:500].lower():
        return clean_text(raw, 200_000), "html"
    return clean_text(raw, 200_000), "text"
