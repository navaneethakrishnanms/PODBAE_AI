"""iTunes Search connector: normalisation, response cache (no second request), rate limiting."""
from __future__ import annotations

import time

import httpx

from app.intel.connectors import directory as d

PAYLOAD = {"resultCount": 2, "results": [
    {"collectionId": 11, "collectionName": "Garden Hour", "feedUrl": "https://feeds.example/garden.xml", "artistName": "Jo Green",
     "genres": ["Home & Garden", "Podcasts", "Leisure"], "genreIds": ["1520", "26", "1502"], "primaryGenreName": "Home & Garden",
     "trackCount": 42, "releaseDate": "2026-11-01T10:00:00Z"},
    {"collectionId": 12, "collectionName": "No Feed", "artistName": "X"}]}


def test_itunes_search_normalises_and_caches(db):
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(str(req.url))
        return httpx.Response(200, json=PAYLOAD)

    with httpx.Client(transport=httpx.MockTransport(handler)) as c:
        it = d.ITunesSearch(c)
        a = it.search("gardening", 50)
        b = it.search("gardening", 50)
    assert len(calls) == 1 and it.cache_hits == 1                     # second identical search served from the store cache
    assert a == b and len(a) == 1                                      # result without a feed URL is skipped
    r = a[0]
    assert r["itunes_id"] == "11" and r["categories"] == ["Home & Garden", "Leisure"] and r["primary_genre"] == "Home & Garden"
    assert r["episode_count"] == 42 and r["latest_release"].startswith("2026-11-01")


def test_rate_limiter_spaces_calls():
    rl = d._RateLimiter()
    t0 = time.monotonic()
    for _ in range(3):
        rl.wait(per_min=600)            # 600/min = one call every 0.1 s
    assert time.monotonic() - t0 >= 0.19
