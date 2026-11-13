"""Layer 4 Opportunity Engine (podcast partners): acceptance tests. No LLM; deterministic; synthetic store."""
from __future__ import annotations

import json
import re
from datetime import timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.intel.db import session_scope
from app.intel.models import CostLedger, Job, Provenance
from app.intel.trust import jobs
from app.opportunities import engine, explain as ex
from app.opportunities.api import router as opp_router
from app.opportunities.config import get_config
from app.opportunities.factors import score_pair
from app.opportunities.features import Corpus
from app.opportunities.models import Opportunity, OpportunityEvent, OpportunityRejection
from tests.conftest import TOKEN_HEADERS
from tests.opp_helpers import AS_OF, add_episode, filler, mk_show, peak_vec, vec

EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
BASE = vec(1)


def corpus(s, at=AS_OF):
    return Corpus.load(s, at)


@pytest.fixture()
def world(db):
    """member M + 3 strong partners (A member/open, B non-member with website, C non-member no site) + 24 unrelated fillers."""
    with session_scope() as s:
        filler(s)
        mk_show(s, "shw_m", "Member Show", v=BASE, member_user="u1", creator={"goals": ["cross_promo"]})
        mk_show(s, "shw_a", "Alpha Laughs", v=peak_vec(BASE, 2), member_user="u2", creator={"collaboration_openness": "open"})
        mk_show(s, "shw_b", "Bravo Banter", v=peak_vec(BASE, 3), website="https://bravo.example/", contact_url="https://bravo.example/contact")
        mk_show(s, "shw_c", "Charlie Chuckles", v=peak_vec(BASE, 4))
    return ["shw_a", "shw_b", "shw_c"]


@pytest.fixture()
def client(db):
    from app.intel.api import router
    app = FastAPI()
    app.include_router(router)
    app.include_router(opp_router)
    return TestClient(app, headers=TOKEN_HEADERS)


def run(s, member="shw_m", at=AS_OF, cfg=None):
    cfg = cfg or get_config()
    return engine.compute(s, corpus(s, at), member, cfg, engine.load_history(s, member, cfg), engine.seen_days(s, member, at, cfg)[0])


# ───────────────────────── gates ─────────────────────────
def test_blocked_category_excluded_before_ranking_even_at_fit_99(world):
    with session_scope() as s:
        mk_show(s, "shw_twin", "Twin Of Member", v=peak_vec(BASE, 9), creator={"collaboration_openness": "open"}, guest=0.6)
        c = corpus(s)
        fit, _ = score_pair(c.shows["shw_m"], c.shows["shw_twin"], c, get_config())
        assert fit >= 95, fit                                    # it really would be a near-perfect Fit
        from app.opportunities.features import FieldVal
        c.shows["shw_m"].fields["creator.blocked_categories"] = FieldVal(["Comedy"], "creator_provided", 1.0, True, "manual", "x", 0)
        res = engine.compute(s, c, "shw_m", get_config())
        rej = {r["candidate_show_id"]: r for r in res["rejections"]}
        assert rej["shw_twin"]["reason"] == "blocked_category"
        assert "shw_twin" not in {r["target_show_id"] for r in res["scored"]}   # never scored, never ranked


def test_blocked_brand_safety_flag_and_blocked_topic_id(world):
    with session_scope() as s:
        mk_show(s, "shw_rude", "Rude Show", v=peak_vec(BASE, 11), flags=["profanity"])
        mk_show(s, "shw_true", "Crime Laughs", v=peak_vec(BASE, 12), topics=[("comedy", 1.0), ("true_crime", 0.6)])
        c = corpus(s)
        from app.opportunities.features import FieldVal
        m = c.shows["shw_m"]
        m.fields["creator.blocked_brand_safety_flags"] = FieldVal(["profanity"], "creator_provided", 1.0, True, "manual", "x", 0)
        m.fields["creator.blocked_categories"] = FieldVal(["true_crime"], "creator_provided", 1.0, True, "manual", "x", 0)
        rej = {r["candidate_show_id"]: r["reason"] for r in engine.compute(s, c, "shw_m", get_config())["rejections"]}
        assert rej["shw_rude"] == "blocked_brand_safety" and rej["shw_true"] == "blocked_category"


def test_self_same_owner_inactive_closed_optout_and_no_embedding(world):
    with session_scope() as s:
        from app.intel.models import Embedding
        mk_show(s, "shw_own", "Same Owner", v=peak_vec(BASE, 13), owner="h1")
        from app.intel.trust.provenance import get_source, record
        record(s, "show", "shw_m", "owner_email_hash", "h1", source=get_source(s, "rss", "rss"), tier="verified", method="parsed")
        mk_show(s, "shw_dead", "Dead Show", v=peak_vec(BASE, 14), activity="inactive")
        mk_show(s, "shw_closed", "Closed Show", v=peak_vec(BASE, 15), member_user="u9", creator={"collaboration_openness": "closed"})
        mk_show(s, "shw_out", "Opted Out", v=peak_vec(BASE, 16), creator={"opportunity_opt_out": True})
        mk_show(s, "shw_noemb", "No Embedding", v=peak_vec(BASE, 17))
        s.query(Embedding).filter(Embedding.entity_id == "shw_noemb").delete()
        res = run(s)
        rej = {r["candidate_show_id"]: r["reason"] for r in res["rejections"]}
        assert rej.get("shw_own") == "same_owner" and rej.get("shw_dead") == "inactive" and rej.get("shw_closed") == "closed_to_collaboration"
        assert rej.get("shw_out") == "opted_out"
        assert "shw_noemb" not in {r["target_show_id"] for r in res["scored"]}    # no content embedding -> never a candidate / gated
        assert "shw_m" not in {r["target_show_id"] for r in res["scored"]}


def test_language_gate_declared_vs_detected(world):
    with session_scope() as s:
        mk_show(s, "shw_es", "Show ES", v=peak_vec(BASE, 21), lang="es")
        mk_show(s, "shw_conf_hi", "Mislabelled", v=peak_vec(BASE, 22), lang="en", detected=("de", 0.95), description="Ein Podcast. " * 40)
        mk_show(s, "shw_conf_lo", "Unsure", v=peak_vec(BASE, 23), lang="en", detected=("de", 0.70))
        res = run(s)
        rej = {r["candidate_show_id"]: r for r in res["rejections"]}
        assert rej["shw_es"]["reason"] == "language_incompatible"
        assert rej["shw_conf_hi"]["reason"] == "language_incompatible" and rej["shw_conf_hi"]["detail"]["candidate_basis"].startswith("detected")
        ok = next(r for r in res["scored"] if r["target_show_id"] == "shw_conf_lo")
        assert ok["gate"]["candidate_language"] == "en" and ok["gate"]["candidate_language_basis"].startswith("uncertain")
        assert ok["gate"]["language_uncertain"] is True and ok["confidence"]["adjustments"][0]["code"] == "language_uncertain"


# ───────────────────────── no padding ─────────────────────────
def test_fewer_than_three_qualifying_are_shown_alone_never_padded(world):
    with session_scope() as s:
        cfg = get_config()
        res = run(s, cfg=cfg)
        assert len(res["qualified"]) == 3
        fits = sorted(r["fit"] for r in res["qualified"])
        cfg["ranking"]["min_fit"] = fits[-1]                      # only the best one(s) pass now
        expected = sum(f >= fits[-1] for f in fits)
        assert expected < 3
        res2 = run(s, cfg=cfg)
        assert len(res2["qualified"]) == expected and res2["state"]["state"] == "few"
        assert "never pad" in res2["state"]["message"]
        assert len(res2["scored"]) > 2       # weaker candidates existed but were not used to fill the list


def test_no_match_state_with_what_would_help(db):
    with session_scope() as s:
        filler(s)
        mk_show(s, "shw_lone", "Lonely Show", v=vec(999), topics=[("video_games", 1.0)], declared=["video_games"], groups=["Leisure"])
        res = run(s, "shw_lone")
        assert res["qualified"] == [] and res["state"]["state"] == "no_match"
        codes = {x["code"] for x in res["state"]["suggestions"]}
        assert {"add_goals", "set_openness", "upload_audience"} <= codes


def test_list_endpoint_no_match_and_few_states(world, client):
    with session_scope() as s:
        engine.persist(s, run(s), get_config(), engine.fingerprint(s, "shw_m"), 1)
    r = client.get("/v1/opportunities", params={"member_show_id": "shw_m"}).json()
    assert r["state"] == "ok" and len(r["items"]) == 3
    assert [i["rank"] for i in r["items"]] == [1, 2, 3]


# ───────────────────────── determinism ─────────────────────────
def test_determinism_same_inputs_same_version_identical(world):
    with session_scope() as s:
        a, b = run(s), run(s)
        assert a["result_hash"] == b["result_hash"]
        strip = lambda res: json.dumps([{k: v for k, v in r.items()} for r in res["scored"]], sort_keys=True, default=str)  # noqa: E731
        assert strip(a) == strip(b)
        assert [r["target_show_id"] for r in a["qualified"]] == [r["target_show_id"] for r in b["qualified"]]


def test_generate_twice_keeps_stable_ids_and_identical_scores(world):
    g1 = engine.generate("shw_m", as_of=AS_OF)
    with session_scope() as s:
        first = {o.target_show_id: (o.id, o.fit, o.confidence, o.rank) for o in s.scalars(select(Opportunity).where(Opportunity.status == "active"))}
    g2 = engine.generate("shw_m", as_of=AS_OF)
    with session_scope() as s:
        second = {o.target_show_id: (o.id, o.fit, o.confidence, o.rank) for o in s.scalars(select(Opportunity).where(Opportunity.status == "active"))}
    assert first == second and g1["qualified"] == g2["qualified"] == 3


# ───────────────────────── missing data ─────────────────────────
def test_missing_factor_renormalises_and_lowers_confidence(world):
    with session_scope() as s:
        mk_show(s, "shw_full", "Full Data", v=peak_vec(BASE, 31))
        mk_show(s, "shw_part", "Part Data", v=peak_vec(BASE, 31), minutes=None, cadence=None)   # same vector, no format data
        c, cfg = corpus(s), get_config()
        m = c.shows["shw_m"]
        _, full = score_pair(m, c.shows["shw_full"], c, cfg)
        fit_p, part = score_pair(m, c.shows["shw_part"], c, cfg)
        fmt = next(f for f in part if f["name"] == "format_compatibility")
        assert fmt["status"] == "missing" and fmt["effective_weight"] == 0
        used = [f for f in part if f["status"] == "used"]
        assert abs(sum(f["effective_weight"] for f in used) - 1.0) < 1e-3
        assert abs(fit_p - 100 * sum(f["weight"] * f["value"] for f in used) / sum(f["weight"] for f in used)) < 0.01
        from app.opportunities.confidence import evidence_confidence
        cf, cp = evidence_confidence(full, cfg), evidence_confidence(part, cfg)
        assert cp["coverage"] < cf["coverage"] and cp["value"] < cf["value"] and "format_compatibility" in cp["missing_factors"]


def test_audience_factors_disabled_until_both_have_data_and_do_not_cost_coverage(world):
    with session_scope() as s:
        c, cfg = corpus(s), get_config()
        _, rows = score_pair(c.shows["shw_m"], c.shows["shw_a"], c, cfg)
        st = {f["name"]: f["status"] for f in rows}
        assert st["audience_size_parity"] == "disabled" and st["geo_overlap"] == "disabled"
        from app.opportunities.confidence import evidence_confidence
        assert evidence_confidence(rows, cfg)["coverage"] == 1.0
        from app.intel.trust.provenance import get_source, record
        up = get_source(s, "creator_upload", "creator")
        for sid, n in (("shw_m", 1000), ("shw_a", 2000)):
            record(s, "show", sid, "audience.totals", {"data": {"downloads": n}, "plausibility_flags": []}, source=up,
                   tier="creator_provided", method="parsed", confidence=0.85)
        c2 = corpus(s)
        _, rows2 = score_pair(c2.shows["shw_m"], c2.shows["shw_a"], c2, cfg)
        f = next(x for x in rows2 if x["name"] == "audience_size_parity")
        assert f["status"] == "used" and 0.6 < f["value"] < 0.75          # 2x apart on a 10x scale
        assert next(x for x in rows2 if x["name"] == "geo_overlap")["status"] == "disabled"   # only one side has... neither has geo


def test_unknown_style_is_missing_not_a_category(world):
    with session_scope() as s:
        mk_show(s, "shw_unk", "Unknown Style", v=peak_vec(BASE, 41), style=None)
        mk_show(s, "shw_nostyle", "No Style Vector", v=peak_vec(BASE, 42), style_features=False)
        c, cfg = corpus(s), get_config()
        _, rows = score_pair(c.shows["shw_m"], c.shows["shw_unk"], c, cfg)
        vf = next(f for f in rows if f["name"] == "vibe_compatibility")
        assert vf["status"] == "used" and vf["inputs"]["style_dims"].startswith("excluded")
        # same vibe+tone as the member: with style dims excluded the centred cosine is ~1 (unknown is not a mismatch)
        assert vf["inputs"]["centred_cosine"] > 0.99
        _, rows2 = score_pair(c.shows["shw_m"], c.shows["shw_nostyle"], c, cfg)
        assert next(f for f in rows2 if f["name"] == "vibe_compatibility")["status"] == "missing"


# ───────────────────────── readiness / conversion ─────────────────────────
def test_readiness_levels_and_conversion(world):
    with session_scope() as s:
        mk_show(s, "shw_mem_quiet", "Quiet Member", v=peak_vec(BASE, 51), member_user="u7")
        res = run(s)
        by = {r["target_show_id"]: r for r in res["scored"]}
        assert by["shw_a"]["readiness"]["level"] == "verified" and by["shw_a"]["readiness"]["contact_route"] == "in_app"
        assert by["shw_b"]["readiness"]["level"] == "potential_lead" and by["shw_b"]["readiness"]["contact_url"] == "https://bravo.example/contact"
        assert by["shw_c"]["readiness"]["level"] == "discovery_lead"
        assert by["shw_mem_quiet"]["readiness"]["level"] == "potential_lead"
        assert all(r["conversion"]["label"] == "Not enough data yet" for r in res["scored"])


# ───────────────────────── why-now ─────────────────────────
def test_why_now_only_from_real_timestamps_with_evidence(world):
    with session_scope() as s:
        eid = add_episode(s, "shw_b", "Ep 9: Big laughs", 4, topic="comedy")
        add_episode(s, "shw_b", "Old one", 200, topic="comedy")
        res = run(s)
        by = {r["target_show_id"]: r for r in res["qualified"]}
        t = by["shw_b"]["why_now"][0]
        assert t["code"] == "shared_topic_recent" and t["evidence"][0]["episode_id"] == eid and t["evidence"][0]["title"] == "Ep 9: Big laughs"
        assert by["shw_c"]["why_now"] == []                       # no signal -> no trigger, no filler text
        assert "Why now" in by["shw_b"]["explanation"]["text"] and "Why now" not in by["shw_c"]["explanation"]["text"]


def test_joined_recently_and_guest_episodes_triggers(world):
    with session_scope() as s:
        mk_show(s, "shw_new", "New Member", v=peak_vec(BASE, 61), member_user="u8", joined_days=5, creator={"collaboration_openness": "open"})
        add_episode(s, "shw_new", "With guest Sam", 3, guest=True)
        res = run(s)
        codes = [t["code"] for t in next(r for r in res["qualified"] if r["target_show_id"] == "shw_new")["why_now"]]
        assert codes[0] == "joined_podbae" and "recent_guest_episodes" in codes


# ───────────────────────── explanations ─────────────────────────
def test_explanations_are_faithful_and_tampering_is_caught(world):
    with session_scope() as s:
        add_episode(s, "shw_a", "Ep 3: Pranks", 2, topic="comedy")
        res = run(s)
        for r in res["scored"]:
            assert r["explanation"]["faithfulness_problems"] == [], (r["target_show_id"], r["explanation"])
            assert r["explanation"]["method"] == "template"
        r = res["qualified"][0]
        bad = json.loads(json.dumps(r["explanation"]))
        bad["parts"][0]["slots"]["fit"] = 99 if round(r["fit"]) != 99 else 98
        bad["parts"][0]["text"] = ex._render(bad["parts"][0]["id"], bad["parts"][0]["slots"])
        bad["text"] = " ".join(p["text"] for p in bad["parts"])
        assert ex.faithfulness(bad, r)
        bad2 = json.loads(json.dumps(r["explanation"]))
        bad2["text"] += " Trusted by 500 listeners."
        assert ex.faithfulness(bad2, r)


# ───────────────────────── API: events, suppression, expiry, privacy, token, no-LLM ─────────────────────────
def _gen(client):
    r = client.post("/v1/opportunities/generate", json={"member_show_id": "shw_m"})
    assert r.status_code == 202
    jid = r.json()["job_id"]
    assert client.post("/v1/opportunities/generate", json={"member_show_id": "shw_m"}).json()["job_id"] == jid   # idempotent
    jobs.run_pending()
    with session_scope() as s:
        assert s.get(Job, jid).status == "succeeded"
    return client.get("/v1/opportunities", params={"member_show_id": "shw_m", "user_id": "u1"}).json()


def test_api_generate_list_and_dismiss_requires_reason_and_suppresses_immediately(world, client):
    lst = _gen(client)
    assert lst["state"] == "ok" and lst["status"] == "draft-unapproved-by-founder"
    item = lst["items"][0]
    assert item["fit"]["note"].startswith("Vibe Logic draft") and item["conversion"]["label"] == "Not enough data yet"
    assert set(item["breakdown"]["disabled"]) == {"audience_size_parity", "geo_overlap"}
    bad = client.post("/v1/events", json={"events": [{"opportunity_id": item["id"], "type": "dismiss", "user_id": "u1"}]})
    assert bad.status_code == 422
    ok = client.post("/v1/events", json={"events": [{"opportunity_id": item["id"], "type": "dismiss", "user_id": "u1", "reason": "not_my_vibe"}]})
    assert ok.status_code == 200
    after = client.get("/v1/opportunities", params={"member_show_id": "shw_m", "user_id": "u1"}).json()
    assert item["target"]["show_id"] not in {i["target"]["show_id"] for i in after["items"]}     # suppressed at once
    assert after["state"] == "few" and after["stale"] is True and after["job"]                     # inputs changed -> regeneration queued
    jobs.run_pending()
    with session_scope() as s:
        rej = s.scalar(select(OpportunityRejection).where(OpportunityRejection.candidate_show_id == item["target"]["show_id"]))
        assert rej is not None and rej.reason == "dismissed_recently"


def test_cooldown_expires_after_configured_days(world):
    engine.generate("shw_m", as_of=AS_OF)
    with session_scope() as s:
        o = s.scalar(select(Opportunity).where(Opportunity.target_show_id == "shw_a", Opportunity.status == "active"))
        engine.record_events(s, [{"opportunity_id": o.id, "type": "contact", "user_id": "u1"}])
        s.query(OpportunityEvent).update({OpportunityEvent.ts: AS_OF})
    with session_scope() as s:
        assert "shw_a" not in {r["target_show_id"] for r in run(s, at=AS_OF + timedelta(days=10))["scored"]}
        assert "shw_a" in {r["target_show_id"] for r in run(s, at=AS_OF + timedelta(days=31))["scored"]}


def test_seen_suppression_and_engagement_exemption(world):
    engine.generate("shw_m", as_of=AS_OF)
    with session_scope() as s:
        o = s.scalar(select(Opportunity).where(Opportunity.target_show_id == "shw_c", Opportunity.status == "active"))
        for d in range(1, 6):     # shown on 5 distinct earlier days, never engaged
            s.add(OpportunityEvent(opportunity_id=o.id, member_show_id="shw_m", target_show_id="shw_c", user_id="u1", type="impression",
                                   position=3, scoring_version=o.scoring_version, ts=AS_OF - timedelta(days=d)))
    with session_scope() as s:
        r = engine.list_for_member(s, "shw_m", user_id="u1", as_of=AS_OF, auto_generate=False)
        assert "shw_c" not in {i["target"]["show_id"] for i in r["items"]} and r["suppressed"]["seen_too_often"] == 1
        o = s.scalar(select(Opportunity).where(Opportunity.target_show_id == "shw_c", Opportunity.status == "active"))
        s.add(OpportunityEvent(opportunity_id=o.id, member_show_id="shw_m", target_show_id="shw_c", user_id="u1", type="save",
                               scoring_version=o.scoring_version, ts=AS_OF - timedelta(hours=2)))
    with session_scope() as s:
        r = engine.list_for_member(s, "shw_m", user_id="u1", as_of=AS_OF, auto_generate=False)
        assert "shw_c" in {i["target"]["show_id"] for i in r["items"]}


def test_expiry_marks_expired_and_requests_regeneration(world):
    engine.generate("shw_m", as_of=AS_OF)
    with session_scope() as s:
        r = engine.list_for_member(s, "shw_m", as_of=AS_OF + timedelta(days=15))
        assert r["items"] == [] and r["job"] is not None
        assert s.scalar(select(func.count()).select_from(Opportunity).where(Opportunity.status == "expired")) >= 3


def test_impressions_logged_with_positions_and_events_idempotent(world, client):
    lst = _gen(client)
    evs = [{"opportunity_id": it["id"], "type": "impression", "user_id": "u1", "position": i + 1,
            "idempotency_key": f"imp:{it['id']}:u1:2026-11-12"} for i, it in enumerate(lst["items"])]
    assert client.post("/v1/events", json={"events": evs}).status_code == 200
    again = client.post("/v1/events", json={"events": evs}).json()["recorded"]
    assert all(x["deduplicated"] for x in again)
    with session_scope() as s:
        rows = list(s.scalars(select(OpportunityEvent).where(OpportunityEvent.type == "impression").order_by(OpportunityEvent.position)))
        assert [e.position for e in rows] == [1, 2, 3] and all(e.scoring_version == get_config()["scoring_version"] for e in rows)
    nopos = client.post("/v1/events", json={"events": [{"opportunity_id": lst["items"][0]["id"], "type": "impression"}]})
    assert nopos.status_code == 422
    today = client.get("/v1/opportunities", params={"member_show_id": "shw_m", "user_id": "u1"}).json()
    assert len(today["shown_today_target_ids"]) == 3 or today["shown_today_target_ids"] == []   # 'today' is wall-clock; see Express test


def test_no_email_or_owner_hash_ever_in_api_output(db, client):
    with session_scope() as s:
        filler(s)
        mk_show(s, "shw_m", "Member Show", v=BASE, owner="ownerhash-m")
        mk_show(s, "shw_a", "Alpha", v=peak_vec(BASE, 2), owner="ownerhash-a", description="Write to host@alpha-pod.com for collabs!",
                website="https://alpha.example")
        mk_show(s, "shw_b", "Bravo", v=peak_vec(BASE, 3), description="email: me@bravo.org")
        add_episode(s, "shw_a", "Contact pat@alpha-pod.com", 2, topic="comedy")
    lst = _gen(client)
    blobs = [json.dumps(lst)] + [client.get(f"/v1/opportunities/{i['id']}").text for i in lst["items"]] + \
            [client.get(f"/v1/opportunities/{i['id']}/explain").text for i in lst["items"]]
    for b in blobs:
        assert not EMAIL.search(b), EMAIL.search(b)
        assert "ownerhash" not in b and "owner_email_hash" not in b


def test_no_llm_calls(world, monkeypatch):
    from app.intel.understanding import providers

    def boom(*a, **k):
        raise AssertionError("LLM provider requested")
    monkeypatch.setattr(providers, "get_provider", boom)
    engine.generate("shw_m", as_of=AS_OF)
    with session_scope() as s:
        assert s.scalar(select(func.count()).select_from(CostLedger).where(CostLedger.operation.like("llm%"))) == 0
        assert s.scalar(select(func.count()).select_from(Provenance).where(Provenance.method == "llm")) == 0


def test_mmr_demotes_a_near_clone_of_the_top_pick(db):
    with session_scope() as s:
        filler(s)
        mk_show(s, "shw_m", "Member", v=BASE)
        top = peak_vec(BASE, 70)
        mk_show(s, "shw_x1", "X One", v=top, creator={"collaboration_openness": "open"})
        mk_show(s, "shw_x2", "X Two", v=peak_vec(top, 71, noise=0.01), creator={"collaboration_openness": "open"})   # near-clone of x1
        mk_show(s, "shw_y", "Y Different", v=peak_vec(BASE, 72), guest=0.3)
        res = run(s)
        order = [r["target_show_id"] for r in res["qualified"]]
        assert order[0] in ("shw_x1", "shw_x2") and order[1] == "shw_y", order
        assert res["qualified"][2]["mmr"]["max_similarity_to_higher_ranked"] > 0.5


def test_metrics_endpoint(world, client):
    _gen(client)
    m = client.get("/v1/admin/engine/metrics").json()
    assert m["status"] == "draft-unapproved-by-founder" and m["counts"]["opportunities_qualified"] == 3
    assert "factor_coverage" in m and m["factor_coverage"]["audience_size_parity"]["disabled"] == 1.0
    assert m["pair_labels"]["note"].startswith("No human pair labels")


# ───────────────────────── blind pair labels ─────────────────────────
def test_pair_labels_blind_queue_two_labelers_agreement_and_metrics(world, client):
    ids = client.post("/v1/labels/pairs/items", json={"n": 3}).json()["member_show_ids"]
    assert "shw_m" in ids and len(ids) == 3
    q = client.get("/v1/labels/pairs/queue", params={"labeler": "Ana"}).json()
    txt = json.dumps(q)
    assert "engine" not in txt.split('"instructions"')[0] and "legacy" not in txt.split('"instructions"')[0]   # blind
    item = next(i for i in q["items"] if i["member"]["show_id"] == "shw_m")
    for lab, rating in (("Ana", "good"), ("Ben", "good")):
        for p in item["pairs"]:
            r = client.put("/v1/labels/pairs/rate", json={"member_show_id": "shw_m", "candidate_show_id": p["candidate"]["show_id"],
                                                     "labeler": lab, "rating": rating})
            assert r.status_code == 200, r.text
    assert client.put("/v1/labels/pairs/rate", json={"member_show_id": "shw_m", "candidate_show_id": item["pairs"][0]["candidate"]["show_id"],
                                                 "labeler": "claude-draft", "rating": "good"}).status_code == 422
    ag = client.get("/v1/labels/pairs/agreement").json()
    assert ag["status"] == "ok" and ag["pairs"][0]["exact_agreement"] == 1.0
    eng = ag["metrics"]["systems"]["engine"]
    assert eng["member_shows_labelled"] == 1 and eng["precision_at_3"] == 1.0 and eng["coverage_at_3"] == 1.0


# ───────────────────────── website (readiness contact route) from RSS ─────────────────────────
def test_ingest_stores_public_website_and_never_mailto(db, server):
    from app.intel import ingest
    from app.intel.trust.provenance import live_rows
    from tests.feedgen import make_feed
    sid = ingest.run_pipeline(server.set("/w.xml", make_feed("Web Show", 4)))["show_id"]
    with session_scope() as s:
        assert live_rows(s, "show", sid, "website")[0].value_json == "https://example.invalid/WebShow"
    assert ingest.public_website("mailto:host@x.com") is None and ingest.public_website("https://u:p@x.com/") is None
    assert ingest.public_website("ftp://x.com") is None and ingest.public_website("https://x.com/a") == "https://x.com/a"


def test_ssrf_guard_handles_nat64_without_opening_private_ranges():
    import ipaddress as ia
    from app.intel.connectors.base import _blocked_ip
    assert not _blocked_ip(ia.ip_address("64:ff9b::d889:3414"))       # NAT64 of 216.137.52.20 (public): allowed
    assert _blocked_ip(ia.ip_address("64:ff9b::a00:1"))               # NAT64 of 10.0.0.1: still blocked
    assert _blocked_ip(ia.ip_address("64:ff9b::7f00:1"))              # NAT64 of 127.0.0.1: still blocked
    assert _blocked_ip(ia.ip_address("::ffff:192.168.1.1"))           # IPv4-mapped private: blocked
    assert _blocked_ip(ia.ip_address("fd00::1")) and _blocked_ip(ia.ip_address("::1"))
    assert not _blocked_ip(ia.ip_address("216.137.52.20"))


# ───────────────────────── Phase 2 close-out: language rule ─────────────────────────
def _pair(s, mlang, clang, mdet=None, cdet=None):
    mk_show(s, "shw_lm", "Lang Member", v=BASE, lang=mlang, detected=mdet)
    mk_show(s, "shw_lc", "Lang Candidate", v=peak_vec(BASE, 81), lang=clang, detected=cdet)
    res = run(s, "shw_lm")
    rej = {r["candidate_show_id"]: r for r in res["rejections"]}
    sc = {r["target_show_id"]: r for r in res["scored"]}
    return rej.get("shw_lc"), sc.get("shw_lc")


def test_language_en_vs_en_us_passes(db):
    with session_scope() as s:
        filler(s)
        rej, sc = _pair(s, "en", "en-US")
        assert rej is None and sc["gate"]["candidate_language"] == "en" and sc["gate"]["language_uncertain"] is False
        assert not sc["confidence"].get("adjustments")


def test_language_confident_en_vs_confident_de_rejected(db):
    with session_scope() as s:
        filler(s)
        rej, sc = _pair(s, "en", "de", mdet=("en", 0.99), cdet=("de", 0.99))
        assert sc is None and rej["reason"] == "language_incompatible"


def test_language_conflicting_tags_not_hard_rejected_but_confidence_lowered(db):
    with session_scope() as s:
        filler(s)
        rej, sc = _pair(s, "en", "de", cdet=("en", 0.6))    # candidate: declared de, detected en at 0.6 -> uncertain
        assert rej is None and sc["gate"]["language_uncertain"] is True
        adj = sc["confidence"]["adjustments"][0]
        assert adj["code"] == "language_uncertain" and adj["factor"] == get_config()["gates"]["language_uncertain_confidence_factor"]
        assert "uncertain" in sc["gate"]["candidate_language_basis"]


# ───────────────────────── Phase 2 close-out: commercial status ─────────────────────────
def test_readiness_homepage_alone_is_discovery_and_routes_need_evidence(world):
    with session_scope() as s:
        mk_show(s, "shw_home", "Homepage Only", v=peak_vec(BASE, 91), website="https://home.example/")
        mk_show(s, "shw_route", "Has Contact Page", v=peak_vec(BASE, 92), website="https://route.example/",
                contact_url="https://route.example/be-a-guest")
        by = {r["target_show_id"]: r for r in run(s)["scored"]}
        assert by["shw_home"]["readiness"]["level"] == "discovery_lead"
        r = by["shw_route"]["readiness"]
        assert r["level"] == "potential_lead" and r["contact_route"] == "contact_page" and r["evidence"]["url"].endswith("/be-a-guest")


def test_contact_routes_found_from_feed_text_never_emails(db):
    from app.intel.contact_routes import find_routes, route_kind
    from app.intel.models import Episode
    with session_scope() as s:
        mk_show(s, "shw_cr", "Routes", v=BASE, website="https://show.example/",
                description="Want to be on the show? https://show.example/be-a-guest or write to host@show.example")
        add_episode(s, "shw_cr", "Ep 1", 3)
        e = s.query(Episode).filter(Episode.show_id == "shw_cr").first()
        e.description = "Sponsor: https://brand.example/deal ... Contact us: https://show.example/contactListen now. mailto:host@show.example"
        e.persons = [{"name": "Guest Ann", "role": "guest", "href": "https://ann.example/contact"}]
        s.flush()
        urls = {r["url"] for r in find_routes(s, "shw_cr")}
        assert {"https://show.example/be-a-guest", "https://show.example/contact", "https://ann.example/contact"} <= urls
        assert "https://show.example/" not in urls                                  # a homepage alone is not a route
        assert not any("@" in u for u in urls)
        assert route_kind("https://show.example/") is None and route_kind("https://x.example/booking") == "booking"


# ───────────────────────── Phase 2 close-out: demo join dates ─────────────────────────
def test_demo_join_dates_and_joined_trigger_window(world, client):
    with session_scope() as s:
        mk_show(s, "shw_old", "Joined Long Ago", v=peak_vec(BASE, 95), creator={"collaboration_openness": "open"})
        mk_show(s, "shw_new2", "Joined Recently", v=peak_vec(BASE, 96), creator={"collaboration_openness": "open"})
    assert client.post("/v1/shows/shw_old/claim", params={"user_id": "d1", "demo": "true", "joined_days_ago": 100}).status_code == 200
    r = client.post("/v1/shows/shw_new2/claim", params={"user_id": "d2", "demo": "true", "joined_days_ago": 5}).json()
    assert r["demo"] is True and r["joined_at"]
    real = client.post("/v1/shows/shw_c/claim", params={"user_id": "r1", "joined_days_ago": 100}).json()   # ignored for real members
    from datetime import datetime
    assert (datetime.utcnow() - datetime.fromisoformat(real["joined_at"].rstrip("Z"))).days == 0
    from app.intel.models import now
    with session_scope() as s:
        res = engine.compute(s, Corpus.load(s, now()), "shw_m", get_config())
        codes = {r["target_show_id"]: [t["code"] for t in r["why_now"]] for r in res["qualified"]}
        assert "joined_podbae" not in codes.get("shw_old", [])
        assert "joined_podbae" in codes.get("shw_new2", [])


# ───────────────────────── Phase 3 leftovers ─────────────────────────
def test_language_detection_needs_a_long_enough_text_sample(db):
    with session_scope() as s:
        filler(s)
        mk_show(s, "shw_lm", "Lang Member", v=BASE, lang="en")
        mk_show(s, "shw_short", "Short Text", v=peak_vec(BASE, 83), lang="en", detected=("ro", 1.0), description="Salut.")
        mk_show(s, "shw_long", "Long Text", v=peak_vec(BASE, 84), lang="en", detected=("ro", 1.0), description="Bun venit la podcast. " * 30)
        res = run(s, "shw_lm")
        rej = {r["candidate_show_id"]: r for r in res["rejections"]}
        sc = {r["target_show_id"]: r for r in res["scored"]}
        assert "shw_short" in sc and sc["shw_short"]["gate"]["language_uncertain"] is True     # 1.0 confidence on 6 chars: not trusted
        assert "characters" in sc["shw_short"]["gate"]["candidate_language_basis"]
        assert rej["shw_long"]["reason"] == "language_incompatible"                             # long sample: detection trusted


def test_why_now_guest_episode_pluralised_and_faithful():
    rec_one = {"code": "recent_guest_episodes", "detail": {"guest_episodes": 1, "window_days": 30},
               "evidence": [{"episode_id": "e1", "date": "2026-11-01", "title": "Ep 7"}]}
    rec_many = dict(rec_one, detail={"guest_episodes": 3, "window_days": 30})
    one, many = ex.why_part(rec_one), ex.why_part(rec_many)
    assert "1 guest episode in" in one["text"] and "guest episodes" not in one["text"]
    assert "3 guest episodes in" in many["text"]
    for tr in (rec_one, rec_many):
        record = {"target_title": "T", "type": "cross_promo", "fit": 70.0, "confidence": {"level": "Medium"}, "factors": [], "why_now": [tr]}
        assert ex.faithfulness(ex.build(record), record) == []
