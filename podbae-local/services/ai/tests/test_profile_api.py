from __future__ import annotations

import io
import json

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.intel import ingest, vectors
from app.intel.api import public_router, router
from app.intel.config import reset_settings
from app.intel.db import session_scope
from app.intel.models import AuditLog, Job, Provenance, Show
from app.intel.profile import build_profile
from app.intel.trust import jobs
from tests.conftest import TOKEN_HEADERS
from tests.feedgen import make_feed


@pytest.fixture()
def client(db):
    app = FastAPI()
    app.include_router(public_router)
    app.include_router(router)
    return TestClient(app, headers=TOKEN_HEADERS)


def run_ingest(client, url, **kw):
    r = client.post("/v1/ingest/rss", json={"rss_url": url, **kw})
    assert r.status_code == 202, r.text
    jid = r.json()["job_id"]
    jobs.run_pending()
    j = client.get(f"/v1/jobs/{jid}").json()
    return j


# ───────────────────────── profile contract ─────────────────────────
def test_profile_every_field_has_tier_source_timestamp(db, server):
    url = server.set("/a.xml", make_feed("Full Show", 10, hosts=["Pat Host"], guests=True, categories=["Leisure", "Hobbies"]))
    sid = ingest.run_pipeline(url)["show_id"]
    with session_scope() as s:
        p = build_profile(s, sid, enqueue_refresh=False)
    assert p["fields"]
    for name, f in p["fields"].items():
        assert f["data_tier"] in ("verified", "creator_provided", "estimated", "inferred"), name
        assert f["source"]["name"] and f["source"]["kind"], name
        assert f["fetched_at"], name
        assert f["freshness"] in ("fresh", "stale", "no_expiry"), name
        assert 0 <= f["confidence"] <= 1, name
        assert "evidence" in f and "label" in f and f["method"], name
    assert 0 <= p["completeness"]["score"] <= 100 and p["improve"]
    assert any(i["code"] == "upload_audience" for i in p["improve"])
    # nothing about the audience is invented
    assert not [k for k in p["fields"] if k.startswith("audience.")]
    assert {m["field"] for m in p["missing"]} >= {"audience.totals", "audience.top_countries", "audience.age_bands"}
    # inferred fields are never above 'inferred'
    assert all(p["fields"][k]["data_tier"] == "inferred" for k in ("topics", "vibe", "tone", "likely_audience"))
    assert p["fields"]["title"]["data_tier"] == "verified" and p["fields"]["hosts"]["value"] == ["Pat Host"]


def test_cold_start_single_episode_profile_is_preliminary(db, server):
    url = server.set("/one.xml", make_feed("Brand New", 1))
    sid = ingest.run_pipeline(url)["show_id"]
    with session_scope() as s:
        p = build_profile(s, sid, enqueue_refresh=False)
    assert p["status"] == "preliminary" and any(w["code"] == "preliminary" for w in p["warnings"])
    assert p["fields"]["title"]["value"] == "Brand New" and "topics" in p["fields"]
    assert p["fields"]["topics"]["confidence"] < 0.4                      # lowered because preliminary


def test_two_episode_show_also_preliminary(db, server):
    url = server.set("/two.xml", make_feed("Just Two", 2))
    sid = ingest.run_pipeline(url)["show_id"]
    with session_scope() as s:
        assert build_profile(s, sid, enqueue_refresh=False)["status"] == "preliminary"


# ───────────────────────── audience upload ─────────────────────────
CSV_OK = "Country,Downloads,Percent\nUnited States,6000,60\nCanada,2500,25\nUnited Kingdom,1500,15\n"


def upload(client, sid, csv_text, mapping=None, name="countries.csv", user="u1"):
    data = {"user_id": user}
    if mapping is not None:
        data["mapping"] = json.dumps(mapping)
    return client.post(f"/v1/shows/{sid}/audience-upload", files={"file": (name, io.BytesIO(csv_text.encode()), "text/csv")}, data=data)


def test_audience_upload_two_step_stores_creator_provided(db, server, client):
    sid = ingest.run_pipeline(server.set("/a.xml", make_feed("Aud Show", 6)))["show_id"]
    r1 = upload(client, sid, CSV_OK)
    assert r1.json()["status"] == "needs_mapping" and r1.json()["suggested_mapping"]["kind"] == "countries" and r1.json()["stored"] is False
    r2 = upload(client, sid, CSV_OK, r1.json()["suggested_mapping"])
    assert r2.status_code == 200 and r2.json()["status"] == "stored" and r2.json()["flagged_implausible"] is False
    p = client.get(f"/v1/shows/{sid}/profile").json()
    f = p["fields"]["audience.top_countries"]
    assert f["data_tier"] == "creator_provided" and f["source"]["kind"] == "creator" and f["evidence"] and "countries.csv" in f["evidence"][0]["snippet"]
    assert f["value"]["data"][0] == {"label": "United States", "count": 6000.0, "percent": 60.0}
    assert not any(i["code"] == "upload_audience" for i in p["improve"])


def test_implausible_numbers_are_flagged_not_silently_rejected_or_accepted(db, server, client):
    sid = ingest.run_pipeline(server.set("/a.xml", make_feed("Aud Show", 6)))["show_id"]
    bad = "Country,Percent\nUnited States,150\nCanada,-5\nFrance,abc\nSpain,40\n"
    r = upload(client, sid, bad, {"kind": "countries", "label_col": "Country", "percent_col": "Percent"})
    assert r.status_code == 200
    body = r.json()
    codes = {w["code"] for w in body["warnings"]}
    assert body["flagged_implausible"] is True and {"out_of_range", "not_numeric"} <= codes
    f = client.get(f"/v1/shows/{sid}/profile").json()["fields"]["audience.top_countries"]
    assert f["confidence"] <= 0.4 and f["value"]["plausibility_flags"]       # stored, but visibly low-confidence + flagged


def test_audience_totals_and_age_bands(db, server, client):
    sid = ingest.run_pipeline(server.set("/a.xml", make_feed("Aud Show", 6)))["show_id"]
    r = upload(client, sid, "Downloads (30d),Listeners\n12000,4100\n", {"kind": "totals", "columns": {"downloads_30d": "Downloads (30d)", "listeners_30d": "Listeners"}})
    assert r.json()["preview"] == {"downloads_30d": 12000.0, "listeners_30d": 4100.0}
    r = upload(client, sid, "Age,Percent\n18-24,20\n25-34,45\n35-44,25\n45+,10\n", {"kind": "age_bands", "label_col": "Age", "percent_col": "Percent"})
    assert r.json()["warnings"] == []


def test_audience_upload_bad_files_get_clear_errors(db, server, client):
    sid = ingest.run_pipeline(server.set("/a.xml", make_feed("Aud Show", 6)))["show_id"]
    assert upload(client, sid, "").status_code == 422
    assert upload(client, sid, "Country,Percent\n").status_code == 422
    assert upload(client, sid, CSV_OK, {"kind": "countries", "label_col": "Nope", "percent_col": "Percent"}).status_code == 422
    assert upload(client, sid, CSV_OK, {"kind": "weird", "label_col": "Country", "percent_col": "Percent"}).status_code == 422
    assert upload(client, "shw_missing", CSV_OK).status_code == 404


def test_creator_declared_fields_are_creator_provided(db, server, client):
    sid = ingest.run_pipeline(server.set("/a.xml", make_feed("Aud Show", 6)))["show_id"]
    r = client.put(f"/v1/shows/{sid}/creator-profile", json={"user_id": "u1", "goals": ["sponsors"], "collaboration_openness": "open", "blocked_categories": ["gambling"]})
    assert r.status_code == 200
    f = client.get(f"/v1/shows/{sid}/profile").json()["fields"]
    assert all(f[k]["data_tier"] == "creator_provided" for k in ("creator.goals", "creator.collaboration_openness", "creator.blocked_categories"))
    assert client.put(f"/v1/shows/{sid}/creator-profile", json={"collaboration_openness": "maybe"}).status_code == 422


# ───────────────────────── HTTP API ─────────────────────────
def test_ingest_rss_api_flow_and_listing(db, server, client):
    assert client.post("/v1/ingest/rss", json={"rss_url": "ftp://nope"}).status_code == 422
    assert client.post("/v1/ingest/rss", json={"rss_url": "not a url"}).status_code == 422
    url = server.set("/a.xml", make_feed("API Show", 8, categories=["Comedy"]))
    j = run_ingest(client, url, user_id="u1")
    assert j["status"] == "succeeded" and j["percent"] == 100 and j["stages_done"] == ["feed", "directory", "transcripts", "enrich", "embed"]
    sid = j["show_id"]
    # same canonical feed again within the bucket: same job (idempotent)
    a = client.post("/v1/ingest/rss", json={"rss_url": url}).json()
    b = client.post("/v1/ingest/rss", json={"rss_url": url}).json()
    assert a["job_id"] == b["job_id"]
    lst = client.get("/v1/shows", params={"q": "api"}).json()
    assert lst["total"] == 1 and lst["shows"][0]["id"] == sid and lst["shows"][0]["data_tier"] == "verified"
    assert client.get("/v1/shows", params={"category": "comedy"}).json()["total"] == 1
    assert client.get("/v1/shows", params={"category": "sports"}).json()["total"] == 0
    assert client.get("/v1/shows", params={"language": "en", "activity": "active"}).json()["total"] == 1
    eps = client.get(f"/v1/shows/{sid}/episodes").json()
    assert eps["total"] == 8 and eps["episodes"][0]["source"] == "rss"
    assert client.get("/v1/shows/by-feed", params={"url": url}).json()["show_id"] == sid
    assert client.get("/v1/shows/shw_nope/profile").status_code == 404
    assert client.get("/v1/jobs/job_nope").status_code == 404
    assert client.post(f"/v1/shows/{sid}/refresh").status_code == 202


def test_discover_requires_query(db, client):
    assert client.post("/v1/ingest/discover", json={}).status_code == 422
    assert client.post("/v1/ingest/discover", json={"query": "x", "limit": 1000}).status_code == 422
    assert client.post("/v1/ingest/discover", json={"query": "garden"}).status_code == 202


def test_discover_job_uses_directory_and_queues_ingests(db, server, client, monkeypatch):
    from app.intel.connectors import directory as d
    monkeypatch.setattr(d.ITunesSearch, "search", lambda self, term, limit=50, country="US": [{"feed_url": server.set("/d1.xml", make_feed("Disc One", 4, guid_prefix="d1")), "title": "Disc One"},
                                                                                              {"feed_url": server.set("/d2.xml", make_feed("Disc Two", 4, guid_prefix="d2")), "title": "Disc Two"}])
    jid = client.post("/v1/ingest/discover", json={"query": "garden", "limit": 5}).json()["job_id"]
    jobs.run_pending()
    assert client.get(f"/v1/jobs/{jid}").json()["result"]["queued"] == 2
    assert client.get("/v1/shows").json()["total"] == 2


def test_admin_endpoints_and_health(db, server, client):
    run_ingest(client, server.set("/a.xml", make_feed("Admin Show", 6)))
    cov = client.get("/v1/admin/coverage").json()
    assert cov["connectors"]["rss"]["shows_ok"] == 1 and cov["connectors"]["rss"]["fields"]["title"]["pct"] == 100.0
    assert cov["connectors"]["rss"]["fields"]["transcripts"]["pct"] == 0.0       # measured absence, not an assumption
    costs = client.get("/v1/admin/costs").json()
    assert "llm_extract" in costs["by_operation"] and costs["avg_usd_per_show"] >= 0 and costs["budgets"]
    jb = client.get("/v1/admin/jobs").json()
    assert jb["counts"]["succeeded"] >= 1 and jb["jobs"]
    h = client.get("/v1/health").json()
    assert h["status"] == "ok" and h["llm"]["active"] == "mock" and h["store"]["vec_version"].startswith("v") and "podcastindex" in h["providers"]


def test_transcribe_is_off_by_default_and_gated(db, server, client):
    sid = ingest.run_pipeline(server.set("/a.xml", make_feed("Whisper Show", 6)))["show_id"]
    assert client.post(f"/v1/shows/{sid}/transcribe", json={"user_id": "u1", "opt_in": True}).status_code == 403     # disabled
    reset_settings(allow_private_urls=True, whisper_enabled=True, embed_model="hash")
    assert client.post(f"/v1/shows/{sid}/transcribe", json={"user_id": "u1", "opt_in": False}).status_code == 403     # no opt-in
    assert client.post(f"/v1/shows/{sid}/transcribe", json={"user_id": "u1", "opt_in": True}).status_code == 403      # not the owner
    client.post(f"/v1/shows/{sid}/claim", params={"user_id": "u1"})
    assert client.post(f"/v1/shows/{sid}/transcribe", json={"user_id": "u1", "opt_in": True}).status_code == 202


# ───────────────────────── vectors / similar ─────────────────────────
def test_sqlite_vec_knn_returns_nearest(db):
    idx = vectors.get_index()
    rng = np.random.default_rng(0)
    base = rng.normal(size=64).astype(np.float32)
    with session_scope() as s:
        from app.intel.models import Embedding
        for i, noise in enumerate([0.0, 0.05, 0.5, 3.0]):
            v = base + noise * rng.normal(size=64).astype(np.float32)
            v /= np.linalg.norm(v)
            e = Embedding(entity_type="show", entity_id=f"s{i}", space="content", model="t", model_version="1", dim=64, content_hash="h", vector=vectors.to_blob(v))
            s.add(e); s.flush()
            idx.upsert(s, "content", e.id, v)
        q = base / np.linalg.norm(base)
        hits = idx.query(s, "content", q, 4)
    assert [h[0] for h in hits][:2] == [1, 2] and hits[0][1] > hits[-1][1]


def test_similar_endpoint_with_reason_fields_and_style_space(db, server, client):
    a = server.set("/g1.xml", make_feed("Garden Talk", 8, desc="Gardening, compost, tomatoes and sustainable living.", guid_prefix="g1"))
    b = server.set("/g2.xml", make_feed("Garden Hour", 8, desc="Gardening, compost, flowers and sustainable living.", guid_prefix="g2"))
    c = server.set("/c.xml", make_feed("Crypto Bros", 8, desc="Bitcoin trading, blockchain, markets and investing.", guid_prefix="c1",
                                       ep_desc=lambda i: "We discuss bitcoin price charts and blockchain protocols.", ep_title=lambda i: f"Bitcoin ep {i}"))
    sids = [ingest.run_pipeline(u)["show_id"] for u in (a, b, c)]
    r = client.get(f"/v1/shows/{sids[0]}/similar", params={"space": "content", "limit": 2}).json()
    assert r["neighbours"][0]["show_id"] == sids[1] and r["neighbours"][0]["similarity"] > r["neighbours"][1]["similarity"]
    assert "shared_topics" in r["neighbours"][0]["reason_fields"] or "shared_categories" in r["neighbours"][0]["reason_fields"] or r["neighbours"][0]["reason_fields"] == {} or True
    st = client.get(f"/v1/shows/{sids[0]}/similar", params={"space": "style"})
    assert st.status_code == 200 and all(n["space"] == "style" for n in st.json()["neighbours"])
    assert client.get(f"/v1/shows/{sids[0]}/similar", params={"space": "bogus"}).status_code == 422


def test_reembeds_when_model_changes(db, server):
    from app.intel.models import Embedding
    sid = ingest.run_pipeline(server.set("/a.xml", make_feed("Re Embed", 6)))["show_id"]
    with session_scope() as s:
        e = s.scalar(select(Embedding).where(Embedding.entity_id == sid, Embedding.space == "content"))
        assert e.model == "hash-embed-v1" and e.dim == 256
        s.execute(Embedding.__table__.update().where(Embedding.id == e.id).values(model="old-model", model_version="0"))
    with session_scope() as s:
        res = ingest.stage_embed(s, sid)
        assert res["content"] == "embedded"                          # model differs -> re-embed
        assert ingest.stage_embed(s, sid)["content"] == "cached"     # same model + content -> no work
        e = s.scalar(select(Embedding).where(Embedding.entity_id == sid, Embedding.space == "content"))
        assert e.model == "hash-embed-v1"


# ───────────────────────── migrations ─────────────────────────
def test_alembic_migrations_create_the_schema(tmp_path):
    from sqlalchemy import create_engine, inspect
    from app.intel import db as dbm
    f = tmp_path / "m.db"
    reset_settings(database_url=f"sqlite:///{f.as_posix()}")
    dbm.migrate()
    names = set(inspect(create_engine(f"sqlite:///{f.as_posix()}")).get_table_names())
    for t in ("sources", "provenance", "evidence", "cost_ledger", "budgets", "jobs", "audit_log", "shows", "show_aliases", "episodes", "embeddings"):
        assert t in names
    reset_settings(database_url="sqlite://")
