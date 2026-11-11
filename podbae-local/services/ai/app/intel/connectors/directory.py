"""Directory connectors: Podcast Index (free key), iTunes Search (no key, discovery fallback), Taddy (optional)."""
from __future__ import annotations

import hashlib
import time
from typing import Any

import httpx

from ..config import get_settings
from .base import ConnectorResult, Timer

PI_BASE = "https://api.podcastindex.org/api/1.0"
ITUNES_SEARCH = "https://itunes.apple.com/search"
TADDY_URL = "https://api.taddy.com/"


# ───────────────────────────── Podcast Index ─────────────────────────────
class PodcastIndex:
    name = "podcastindex"
    kind = "podcastindex"
    expected_fields = ["podcastindex_id", "itunes_id", "podcast_guid", "title", "description", "categories", "language",
                       "episode_count", "last_update", "feed_url"]

    def __init__(self, client: httpx.Client, key: str | None = None, secret: str | None = None):
        cfg = get_settings()
        self.client, self.key, self.secret = client, key or cfg.pi_key, secret or cfg.pi_secret

    @property
    def available(self) -> bool:
        return bool(self.key and self.secret)

    def _headers(self) -> dict[str, str]:
        ts = str(int(time.time()))
        auth = hashlib.sha1((self.key + self.secret + ts).encode()).hexdigest()  # noqa: S324 - mandated by the API
        return {"X-Auth-Date": ts, "X-Auth-Key": self.key or "", "Authorization": auth, "User-Agent": "PodBaeIntel/0.1"}

    def _get(self, path: str, params: dict) -> dict:
        r = self.client.get(f"{PI_BASE}{path}", params=params, headers=self._headers())
        r.raise_for_status()
        return r.json()

    @staticmethod
    def _norm(feed: dict) -> dict[str, Any]:
        cats = feed.get("categories") or {}
        return {
            "podcastindex_id": str(feed["id"]) if feed.get("id") is not None else None,
            "itunes_id": str(feed["itunesId"]) if feed.get("itunesId") else None,
            "podcast_guid": feed.get("podcastGuid") or None, "title": feed.get("title"), "description": feed.get("description"),
            "categories": sorted(cats.values()) if isinstance(cats, dict) else None, "language": feed.get("language") or None,
            "episode_count": feed.get("episodeCount"), "last_update": feed.get("lastUpdateTime"),
            "feed_url": feed.get("url") or feed.get("originalUrl"),
        }

    def lookup(self, *, feed_url: str | None = None, itunes_id: str | None = None) -> ConnectorResult:
        res = ConnectorResult(connector=self.name)
        with Timer() as t:
            try:
                if feed_url:
                    data = self._get("/podcasts/byfeedurl", {"url": feed_url})
                else:
                    data = self._get("/podcasts/byitunesid", {"id": itunes_id})
                feed = data.get("feed")
                if feed:
                    res.fields = self._norm(feed)
            except (httpx.HTTPError, ValueError, KeyError) as exc:
                res.ok, res.error = False, f"{type(exc).__name__}: {exc}"[:300]
        res.duration_ms = t.ms
        return res

    def search(self, query: str, limit: int = 20) -> list[dict]:
        data = self._get("/search/byterm", {"q": query, "max": limit, "similar": "false"})
        return [self._norm(f) for f in data.get("feeds", [])]


# ───────────────────────────── iTunes Search (no key) ─────────────────────────────
class ITunesSearch:
    name = "itunes_search"
    kind = "itunes"
    expected_fields = ["itunes_id", "title", "feed_url", "categories", "episode_count", "author"]

    def __init__(self, client: httpx.Client):
        self.client = client

    def search(self, term: str, limit: int = 50, country: str = "US") -> list[dict]:
        r = self.client.get(ITUNES_SEARCH, params={"term": term, "media": "podcast", "entity": "podcast", "limit": limit,
                                                   "country": country})
        r.raise_for_status()
        out = []
        for it in r.json().get("results", []):
            if not it.get("feedUrl"):
                continue
            out.append({"itunes_id": str(it.get("collectionId")), "title": it.get("collectionName") or it.get("trackName"),
                        "feed_url": it["feedUrl"], "categories": it.get("genres") or [], "episode_count": it.get("trackCount"),
                        "author": it.get("artistName"), "language": None})
        return out


# ───────────────────────────── gPodder directory (public, no key) ─────────────────────────────
class GPodderSearch:
    """gpodder.net public directory API (no key). Discovery fallback when there is no Podcast Index key and iTunes is unreachable.
    Entries can be stale: dead feeds are expected and are reported as ingestion failures, never papered over."""
    name = "gpodder_search"
    kind = "gpodder"
    expected_fields = ["title", "feed_url", "author", "subscribers"]

    def __init__(self, client: httpx.Client):
        self.client = client

    def search(self, term: str, limit: int = 50) -> list[dict]:
        r = self.client.get("https://gpodder.net/search.json", params={"q": term})
        r.raise_for_status()
        return [{"feed_url": it["url"], "title": it.get("title"), "author": it.get("author"), "subscribers": it.get("subscribers", 0),
                 "categories": [], "language": None, "itunes_id": None} for it in r.json()[:limit] if it.get("url")]


# ───────────────────────────── Taddy (optional, feature-flagged) ─────────────────────────────
class Taddy:
    """Episodes + transcripts. OFF unless INTEL_TADDY_ENABLED=true and keys exist. Each request is budgeted by the
    caller (units=requests). NOTE: written against Taddy's public GraphQL docs; not exercised without keys."""
    name = "taddy"
    kind = "taddy"
    expected_fields = ["title", "description", "episodes", "episode_transcripts", "language", "itunes_id", "podcast_guid"]
    QUERY = """query($url:String){ getPodcastSeries(rssUrl:$url){ uuid name description language itunesId
        episodes(limitPerPage:10){ uuid name description datePublished taddyTranscribeStatus transcript } } }"""

    def __init__(self, client: httpx.Client):
        cfg = get_settings()
        self.client, self.user, self.key, self.enabled = client, cfg.taddy_user, cfg.taddy_key, cfg.taddy_enabled

    @property
    def available(self) -> bool:
        return bool(self.enabled and self.user and self.key)

    def lookup(self, feed_url: str) -> ConnectorResult:
        res = ConnectorResult(connector=self.name)
        with Timer() as t:
            try:
                r = self.client.post(TADDY_URL, json={"query": self.QUERY, "variables": {"url": feed_url}},
                                     headers={"X-USER-ID": self.user or "", "X-API-KEY": self.key or ""})
                r.raise_for_status()
                s = (r.json().get("data") or {}).get("getPodcastSeries")
                if s:
                    eps = s.get("episodes") or []
                    res.fields = {"title": s.get("name"), "description": s.get("description"), "language": s.get("language"),
                                  "itunes_id": s.get("itunesId"), "episodes": len(eps) or None,
                                  "episode_transcripts": any(e.get("transcript") for e in eps) or None,
                                  "_raw_episodes": eps}
            except (httpx.HTTPError, ValueError) as exc:
                res.ok, res.error = False, f"{type(exc).__name__}: {exc}"[:300]
        res.duration_ms = t.ms
        return res
