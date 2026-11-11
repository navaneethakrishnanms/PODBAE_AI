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
class _RateLimiter:
    """Process-wide spacing between calls (thread-safe). Apple asks for about 20 Search API calls per minute."""

    def __init__(self) -> None:
        import threading
        self._lock = threading.Lock()
        self._next = 0.0

    def wait(self, per_min: float) -> float:
        gap = 60.0 / max(0.1, per_min)
        with self._lock:
            t = time.monotonic()
            delay = max(0.0, self._next - t)
            self._next = max(t, self._next) + gap
        if delay:
            time.sleep(delay)
        return delay


ITUNES_LIMITER = _RateLimiter()


class ITunesSearch:
    """Apple iTunes Search API: no key. Rate-limited (INTEL_ITUNES_RATE_PER_MIN) and cached in the store's api_cache
    table (INTEL_ITUNES_CACHE_HOURS), so re-running a seed costs no requests. Returns directory metadata only:
    feed URL, title, publisher name, genres, episode count and the latest release date (all 'estimated' tier)."""
    name = "itunes_search"
    kind = "itunes"
    expected_fields = ["itunes_id", "title", "feed_url", "categories", "episode_count", "author", "latest_release"]

    def __init__(self, client: httpx.Client, *, use_cache: bool = True):
        self.client, self.use_cache = client, use_cache
        self.calls = self.cache_hits = 0

    def _get_json(self, url: str, params: dict) -> dict:
        from datetime import timedelta

        from ..db import session_scope
        from ..models import ApiCache, now
        cfg = get_settings()
        key = hashlib.sha256(f"itunes|{url}|{sorted(params.items())}".encode()).hexdigest()
        if self.use_cache:
            try:
                with session_scope() as s:
                    row = s.get(ApiCache, key)
                    if row is not None and now() - row.fetched_at < timedelta(hours=cfg.itunes_cache_hours):
                        self.cache_hits += 1
                        return row.response
            except Exception:  # noqa: BLE001 - cache is best-effort (e.g. store not initialised in a script)
                pass
        ITUNES_LIMITER.wait(cfg.itunes_rate_per_min)
        self.calls += 1
        r = self.client.get(url, params=params)
        if r.status_code in (403, 429):        # Apple throttles with 403/429: back off once, then give up
            time.sleep(30)
            r = self.client.get(url, params=params)
        r.raise_for_status()
        data = r.json()
        if self.use_cache:
            try:
                with session_scope() as s:
                    s.merge(ApiCache(key=key, provider="itunes", response=data, fetched_at=now()))
            except Exception:  # noqa: BLE001
                pass
        return data

    @staticmethod
    def _norm(it: dict) -> dict:
        return {"itunes_id": str(it.get("collectionId")), "title": it.get("collectionName") or it.get("trackName"),
                "feed_url": it.get("feedUrl"), "categories": [g for g in (it.get("genres") or []) if g != "Podcasts"],
                "genre_ids": [str(g) for g in (it.get("genreIds") or [])], "primary_genre": it.get("primaryGenreName"),
                "episode_count": it.get("trackCount"), "author": it.get("artistName"), "latest_release": it.get("releaseDate"),
                "country": it.get("country"), "explicit": it.get("collectionExplicitness"), "language": None}

    def search(self, term: str, limit: int = 50, country: str | None = None, genre_id: str | int | None = None) -> list[dict]:
        params: dict[str, Any] = {"term": term, "media": "podcast", "entity": "podcast", "limit": min(200, limit),
                                  "country": country or get_settings().itunes_country}
        if genre_id:
            params["genreId"] = str(genre_id)
        data = self._get_json(ITUNES_SEARCH, params)
        return [self._norm(it) for it in data.get("results", []) if it.get("feedUrl")]

    def lookup(self, itunes_id: str) -> dict | None:
        data = self._get_json("https://itunes.apple.com/lookup", {"id": str(itunes_id), "entity": "podcast"})
        res = [it for it in data.get("results", []) if it.get("feedUrl")]
        return self._norm(res[0]) if res else None


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
