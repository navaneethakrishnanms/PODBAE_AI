from __future__ import annotations

import time
from datetime import datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.intel import ingest
from app.intel.connectors.base import InvalidUrl, validate_url
from app.intel.config import get_settings
from app.intel.db import session_scope
from app.intel.models import AuditLog, Episode, Job, Provenance, Show, ShowAlias
from app.intel.profile import build_profile
from app.intel.trust import jobs
from tests.feedgen import make_feed


def n_shows(s) -> int:
    return s.scalar(select(func.count()).select_from(Show).where(Show.merged_into.is_(None)))


# ───────────────────────── URL validation ─────────────────────────
@pytest.mark.parametrize("bad", ["", "not a url", "ftp://example.com/feed", "http://", "http://user:pw@example.com/f", "javascript:alert(1)",
                                 "http://example.com/" + "a" * 3000])
def test_invalid_urls_rejected(db, bad):
    with pytest.raises(InvalidUrl):
        validate_url(bad)


def test_private_addresses_blocked_by_default(db):
    from app.intel.config import reset_settings
    reset_settings(allow_private_urls=False)
    for u in ("http://127.0.0.1/feed", "http://localhost:8000/x", "http://169.254.169.254/latest/meta-data"):
        with pytest.raises(InvalidUrl):
            validate_url(u)


def test_unreachable_new_feed_fails_job_after_backoff_retries(db, server):
    url = server.set("/gone.xml", offline=True)
    with session_scope() as s:
        j = jobs.enqueue(s, "ingest_rss", "k-unreachable", {"rss_url": url})
        jid = j.id
    jobs.run_pending()
    with session_scope() as s:
        j = s.get(Job, jid)
        assert j.status == "failed" and j.attempts == j.max_attempts == 3
        assert "could not fetch feed" in j.last_error
        assert n_shows(s) == 0


# ───────────────────────── offline / stale ─────────────────────────
def test_offline_feed_serves_cached_data_with_freshness_warning(db, server):
    url = server.set("/a.xml", make_feed("Offline Show", 5))
    sid = ingest.run_pipeline(url)["show_id"]
    server.routes["/a.xml"]["offline"] = True
    res = ingest.run_pipeline(url, force=True)
    assert res["feed"]["status"] == "offline_serving_cached"
    with session_scope() as s:
        p = build_profile(s, sid, enqueue_refresh=False)
        assert p["fields"]["title"]["value"] == "Offline Show"          # cached data still served
        assert any(w["code"] == "feed_unreachable" for w in p["warnings"])
        # and values past their freshness window are flagged stale, not silently trusted
        for r in s.scalars(select(Provenance).where(Provenance.entity_id == sid, Provenance.field == "last_published")):
            r.expires_at = datetime.utcnow() - timedelta(hours=1)
    with session_scope() as s:
        p = build_profile(s, sid, enqueue_refresh=True)
        assert p["fields"]["last_published"]["freshness"] == "stale"
        assert any(w["code"] == "stale_fields" for w in p["warnings"])
        assert p["refresh_job"] is not None                              # stale => refresh queued, not ignored


# ───────────────────────── malformed / huge ─────────────────────────
def test_malformed_xml_is_tolerated(db, server):
    url = server.set("/bad.xml", make_feed("Broken Show", 5, malformed=True))
    res = ingest.run_pipeline(url)
    assert res["feed"]["status"] == "ok" and res["feed"]["malformed_xml"] is True
    with session_scope() as s:
        assert s.scalar(select(func.count()).select_from(Episode)) >= 3


def test_not_a_feed_is_an_error(db, server):
    url = server.set("/page.html", "<html><body><h1>hello</h1></body></html>")
    with session_scope() as s:
        jid = jobs.enqueue(s, "ingest_rss", "k-html", {"rss_url": url}, max_attempts=1).id
    jobs.run_pending()
    with session_scope() as s:
        assert s.get(Job, jid).status == "failed"


def test_5000_episode_feed_is_incremental_and_bounded(db, server):
    body = make_feed("Huge Show", 5000, gap_days=0.2)
    url = server.set("/huge.xml", body, etag='"v1"')
    t0 = time.perf_counter()
    r1 = ingest.run_pipeline(url)
    first = time.perf_counter() - t0
    assert first < 60
    assert r1["feed"]["episodes"]["in_feed"] == 5000 and r1["feed"]["episodes"]["stored_window"] == get_settings().keep_episodes == 200
    sid = r1["show_id"]
    with session_scope() as s:
        assert s.scalar(select(func.count()).select_from(Episode).where(Episode.show_id == sid)) == 200
    # conditional GET: 304, nothing re-parsed, almost free
    t0 = time.perf_counter()
    r2 = ingest.run_pipeline(url)
    assert r2["feed"]["status"] == "not_modified" and time.perf_counter() - t0 < first
    # forced re-fetch: no duplicates, no changes
    r3 = ingest.run_pipeline(url, force=True)
    assert r3["feed"]["episodes"]["added"] == 0 and r3["feed"]["episodes"]["changed"] == 0
    with session_scope() as s:
        assert s.scalar(select(func.count()).select_from(Episode).where(Episode.show_id == sid)) == 200


def test_oversized_feed_rejected(db, server):
    from app.intel.config import reset_settings
    reset_settings(allow_private_urls=True, max_feed_bytes=2000, backoff_base_seconds=0.0)
    url = server.set("/big.xml", make_feed("Big", 50))
    with session_scope() as s:
        jid = jobs.enqueue(s, "ingest_rss", "k-big", {"rss_url": url}, max_attempts=1).id
    jobs.run_pending()
    with session_scope() as s:
        assert s.get(Job, jid).status == "failed" and "exceeds" in s.get(Job, jid).last_error


# ───────────────────────── identity ─────────────────────────
def test_duplicate_feeds_collapse_to_one_show_via_podcast_guid(db, server):
    g = "917393e3-1b1e-5cef-ace4-edaa54e1f810"
    a = server.set("/a.xml", make_feed("Dup Show", 6, podcast_guid=g))
    b = server.set("/mirror/b.xml", make_feed("Dup Show (mirror)", 6, podcast_guid=g))
    s1 = ingest.run_pipeline(a)["show_id"]
    s2 = ingest.run_pipeline(b)["show_id"]
    assert s1 == s2
    with session_scope() as s:
        assert n_shows(s) == 1
        assert s.scalar(select(func.count()).select_from(Episode)) == 6


def test_duplicate_feeds_without_guid_collapse_by_title_and_episode_overlap(db, server):
    a = server.set("/orig.xml", make_feed("Same Show", 8))
    b = server.set("/feedburner.xml", make_feed("Same Show", 8))
    assert ingest.run_pipeline(a)["show_id"] == ingest.run_pipeline(b)["show_id"]


def test_url_variants_are_one_identity(db, server):
    a = server.set("/feed.xml", make_feed("Variant Show", 5))
    s1 = ingest.run_pipeline(a)["show_id"]
    s2 = ingest.run_pipeline(a + "?utm_source=x")["show_id"]
    assert s1 == s2


def test_different_shows_do_not_collapse(db, server):
    a = server.set("/one.xml", make_feed("Show One", 6, guid_prefix="one"))
    b = server.set("/two.xml", make_feed("Show Two", 6, guid_prefix="two"))
    assert ingest.run_pipeline(a)["show_id"] != ingest.run_pipeline(b)["show_id"]


def test_changed_feed_url_keeps_identity_via_new_feed_url(db, server):
    old = server.set("/old.xml", make_feed("Mover", 6, podcast_guid="g-mover"))
    sid = ingest.run_pipeline(old)["show_id"]
    new_url = server.base + "/new.xml"
    server.set("/old.xml", make_feed("Mover", 6, podcast_guid="g-mover", new_feed_url=new_url))
    server.set("/new.xml", make_feed("Mover", 6, podcast_guid="g-mover"))
    assert ingest.run_pipeline(old, force=True)["show_id"] == sid
    assert ingest.run_pipeline(new_url)["show_id"] == sid
    with session_scope() as s:
        assert s.get(Show, sid).canonical_feed_url == new_url
        assert n_shows(s) == 1
        assert s.scalar(select(AuditLog.id).where(AuditLog.action == "feed_url_changed"))


def test_permanent_redirect_keeps_identity(db, server):
    url = server.set("/before.xml", make_feed("Redirected", 6))
    sid = ingest.run_pipeline(url)["show_id"]
    server.set("/before.xml", b"", status=301, headers={"Location": server.base + "/after.xml"})
    server.set("/after.xml", make_feed("Redirected", 6))
    assert ingest.run_pipeline(url, force=True)["show_id"] == sid
    with session_scope() as s:
        assert n_shows(s) == 1
        assert s.get(Show, sid).canonical_feed_url.endswith("/after.xml")


# ───────────────────────── episodes ─────────────────────────
def test_deleted_episode_is_marked_removed_not_deleted(db, server):
    url = server.set("/a.xml", make_feed("Del Show", 6))
    sid = ingest.run_pipeline(url)["show_id"]
    server.set("/a.xml", make_feed("Del Show", 6, skip_guids={"ep-2"}))
    r = ingest.run_pipeline(url, force=True)
    assert r["feed"]["episodes"]["removed"] == 1
    with session_scope() as s:
        ep = s.scalar(select(Episode).where(Episode.show_id == sid, Episode.guid == "ep-2"))
        assert ep is not None and ep.removed and ep.removed_at is not None
        assert s.scalar(select(func.count()).select_from(Episode).where(Episode.show_id == sid)) == 6
    server.set("/a.xml", make_feed("Del Show", 6))                       # comes back
    assert ingest.run_pipeline(url, force=True)["feed"]["episodes"]["revived"] == 1


def test_non_english_show_detected(db, server):
    es = "Un podcast semanal sobre cocina, jardinería y la vida en comunidad con vecinos y amigos de la ciudad."
    url = server.set("/es.xml", make_feed("Cocina y Jardín", 5, lang=None, desc=es, ep_desc=lambda i: f"En este episodio hablamos de recetas tradicionales y de cómo cultivar tomates en casa, número {i}.",
                                          ep_title=lambda i: f"Episodio {i}: recetas de la abuela"))
    sid = ingest.run_pipeline(url)["show_id"]
    with session_scope() as s:
        p = build_profile(s, sid, enqueue_refresh=False)
        assert p["fields"]["language"]["value"] == "es"
        assert p["fields"]["language"]["data_tier"] == "estimated"        # detected, not declared


def test_declared_language_beats_detected_and_conflict_is_recorded(db, server):
    es = "Un podcast semanal sobre cocina, jardinería y la vida en comunidad con vecinos y amigos de la ciudad."
    url = server.set("/c.xml", make_feed("Conflict", 5, lang="en", desc=es, ep_desc=lambda i: es, ep_title=lambda i: f"Episodio {i}: recetas"))
    sid = ingest.run_pipeline(url)["show_id"]
    with session_scope() as s:
        p = build_profile(s, sid, enqueue_refresh=False)
        f = p["fields"]["language"]
        assert f["value"] == "en" and f["data_tier"] == "verified" and f["conflict"] is True
        assert f["alternatives"][0]["value"] == "es"
        assert s.scalar(select(AuditLog.id).where(AuditLog.action == "conflict", AuditLog.entity_id == sid))


def test_inactive_show_flagged(db, server):
    url = server.set("/old.xml", make_feed("Dormant", 8, newest=datetime.utcnow() - timedelta(days=500)))
    sid = ingest.run_pipeline(url)["show_id"]
    with session_scope() as s:
        assert s.get(Show, sid).activity == "inactive"
        p = build_profile(s, sid, enqueue_refresh=False)
        assert p["fields"]["activity_status"]["value"] == "inactive"
        assert any(w["code"] == "show_inactive" for w in p["warnings"])


def test_active_and_slowing(db, server):
    a = server.set("/act.xml", make_feed("Active One", 8, newest=datetime.utcnow() - timedelta(days=2), guid_prefix="a"))
    sl = server.set("/slow.xml", make_feed("Slow One", 8, newest=datetime.utcnow() - timedelta(days=60), guid_prefix="s"))
    ia, isl = ingest.run_pipeline(a)["show_id"], ingest.run_pipeline(sl)["show_id"]
    with session_scope() as s:
        assert s.get(Show, ia).activity == "active"
        assert s.get(Show, isl).activity == "slowing"


# ───────────────────────── idempotency / resume ─────────────────────────
def test_rerunning_ingestion_creates_no_duplicates(db, server):
    url = server.set("/a.xml", make_feed("Rerun", 7))
    ingest.run_pipeline(url)
    with session_scope() as s:
        before = (s.scalar(select(func.count()).select_from(Episode)), s.scalar(select(func.count()).select_from(ShowAlias)),
                  s.scalar(select(func.count()).select_from(Provenance).where(Provenance.superseded_by.is_(None))), n_shows(s))
    for _ in range(3):
        ingest.run_pipeline(url, force=True)
    with session_scope() as s:
        after = (s.scalar(select(func.count()).select_from(Episode)), s.scalar(select(func.count()).select_from(ShowAlias)),
                 s.scalar(select(func.count()).select_from(Provenance).where(Provenance.superseded_by.is_(None))), n_shows(s))
    assert before == after


def test_job_enqueue_is_idempotent(db):
    with session_scope() as s:
        a = jobs.enqueue(s, "ingest_rss", "same-key", {"rss_url": "http://x"})
        b = jobs.enqueue(s, "ingest_rss", "same-key", {"rss_url": "http://x"})
        assert a.id == b.id


def test_killed_job_resumes_and_completes(db, server):
    url = server.set("/k.xml", make_feed("Killable", 6, transcripts={0: server.base + "/t0.txt"}))
    server.set("/t0.txt", "hello world " * 200)
    with session_scope() as s:
        jid = jobs.enqueue(s, "ingest_rss", "k-kill", {"rss_url": url}).id

    def die_after_feed(stage: str) -> None:
        if stage == "feed":
            raise ingest.SimulatedCrash()

    ingest.STAGE_HOOK = die_after_feed
    with pytest.raises(ingest.SimulatedCrash):
        jobs.run_one()                                                   # process "killed" after the feed stage
    with session_scope() as s:
        j = s.get(Job, jid)
        assert j.status == "running" and j.checkpoint.get("feed") and not j.checkpoint.get("enrich")
        n_eps = s.scalar(select(func.count()).select_from(Episode))
    ingest.STAGE_HOOK = None
    assert jobs.recover_stale(lease_seconds=0) == 1                       # worker restart recovers the orphan
    jobs.run_pending()
    with session_scope() as s:
        j = s.get(Job, jid)
        assert j.status == "succeeded"
        assert all(j.checkpoint.get(st) for st in ("feed", "directory", "transcripts", "enrich", "embed"))
        assert s.scalar(select(func.count()).select_from(Episode)) == n_eps    # no duplicates after resume
    assert server.hits["/k.xml"] == 1                                    # feed stage was NOT redone on resume


def test_transcript_ingested_and_quality_checked(db, server):
    good = "welcome to the show today we talk about gardens and community " * 120
    url = server.set("/t.xml", make_feed("Talky", 4, transcripts={0: server.base + "/good.txt", 1: server.base + "/bad.txt"}, duration="00:10:00"))
    server.set("/good.txt", good)
    server.set("/bad.txt", "%%%### " * 300)
    sid = ingest.run_pipeline(url)["show_id"]
    from app.intel.models import Transcript
    with session_scope() as s:
        qs = sorted((t.quality["score"], t.quality["usable"]) for t in s.scalars(select(Transcript)))
        assert len(qs) == 2 and qs[0][1] is False and qs[1][1] is True
        p = build_profile(s, sid, enqueue_refresh=False)
        assert p["fields"]["transcripts_available"]["value"]["episodes_with_transcript"] == 2
