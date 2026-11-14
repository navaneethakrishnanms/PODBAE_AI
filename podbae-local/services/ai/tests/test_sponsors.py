"""Layer 2 Sponsor Intelligence + sponsor opportunities: acceptance tests (rules-only NER, synthetic store, no LLM)."""
from __future__ import annotations

import json
import os
import re
from datetime import timedelta

os.environ["SPONSOR_NER"] = "rules"          # tests never load GLiNER (GPU); production records which extractor ran

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.intel.db import session_scope
from app.intel.models import CostLedger, Episode, Provenance
from app.intel.trust.provenance import get_source, record
from app.opportunities import explain as ex
from app.opportunities.features import Corpus
from app.sponsors import opportunities as sp
from app.sponsors import review as rv
from app.sponsors.api import router as sponsors_router
from app.sponsors.detect import ShowContext, detect
from app.sponsors.models import Brand, BrandDomain, SponsorshipEvent
from app.sponsors.scan import scan_all
from tests.conftest import TOKEN_HEADERS
from tests.opp_helpers import AS_OF, filler, mk_show, peak_vec, vec

EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
BASE = vec(1)
R = lambda ws: [__import__("app.sponsors.ner", fromlist=["rule_names"]).rule_names(w) for w in ws]  # noqa: E731
ORG = lambda ws: [__import__("app.sponsors.ner", fromlist=["rule_organic"]).rule_organic(w) for w in ws]  # noqa: E731
ACME_AD = "This episode is brought to you by Acme. Go to acme.com/show and use code SHOW for 20% off."


def ep(s, sid: str, title: str, days_ago: float, description: str) -> str:
    e = Episode(show_id=sid, guid=f"{sid}-{title}", title=title, description=description, published_at=AS_OF - timedelta(days=days_ago))
    s.add(e)
    s.flush()
    return e.id


def scan(ids=None):
    return scan_all(ids)


# ───────────────────────── detection classes ─────────────────────────
def test_mandatory_organic_mention_never_sponsorship_or_opportunity(db):
    text = "We discuss a study inspired by Microsoft's new research on sleep."
    ds = detect(text, ShowContext(), ner_fn=R, organic_fn=ORG, organic_names=True)
    assert [(d.cls, d.brand_name) for d in ds] == [("organic_mention", "Microsoft")]
    with session_scope() as s:
        filler(s, 21)
        mk_show(s, "shw_m", "Member", v=BASE)
        mk_show(s, "shw_a", "Neighbour", v=peak_vec(BASE, 2))
        for i in range(4):
            ep(s, "shw_a", f"E{i}", 3 + i, text + " Read more at microsoft.com/research")
    scan()
    with session_scope() as s:
        assert not s.scalar(select(Brand).where(Brand.name.ilike("%microsoft%")))
        hist = s.scalars(select(SponsorshipEvent).where(SponsorshipEvent.cls.in_(("declared_sponsorship", "likely_sponsorship")))).all()
        assert hist == []
        assert s.scalar(select(func.count()).select_from(SponsorshipEvent).where(SponsorshipEvent.cls == "organic_mention")) >= 1
        res = sp.compute(s, Corpus.load(s, AS_OF), sp.BrandIndex.load(s), "shw_m")
        assert res["scored"] == [] and res["state"]["state"] == "no_match"


def test_self_promo_network_boilerplate_podcast_promo_affiliate_not_sponsors(db):
    ctx = ShowContext(own_domains={"myshow.com"}, own_names={"myshow"})
    cases = {
        "Get our merch at myshow.com/shop and join us on patreon.com/myshow": "self_promotion",
        "Learn more about your ad choices. Visit megaphone.fm/adchoices": "network_disclosure",
        "Check out our friends at Murder Club: https://podcasts.apple.com/us/podcast/murder-club/id12345": "podcast_promo",
        "Books mentioned (affiliate links, I earn a commission): amzn.to/3abc": "affiliate",
        "Call 1-800-GAMBLER or visit FanDuel.com/RG or ccpg.org/chat": "network_disclosure",
    }
    for t, cls in cases.items():
        got = {d.cls for d in detect(t, ctx, ner_fn=R)}
        assert got == {cls}, (t, got)
    with session_scope() as s:
        mk_show(s, "shw_x", "X", v=BASE, website="https://myshow.com")
        for i, t in enumerate(cases):
            ep(s, "shw_x", f"E{i}", i + 1, t)
    scan(["shw_x"])
    with session_scope() as s:
        assert s.scalar(select(func.count()).select_from(Brand)) == 0          # none of these ever becomes a brand


def test_repeated_sponsor_blocks_are_kept_as_events(db):
    with session_scope() as s:
        mk_show(s, "shw_r", "Repeat", v=BASE)
        for i in range(5):
            ep(s, "shw_r", f"E{i}", 7 * i + 1, f"Episode {i} talk.\n\nSponsors:\n- Acme: acme.com/show code SHOW\n\nFollow us")
    scan(["shw_r"])
    with session_scope() as s:
        evs = s.scalars(select(SponsorshipEvent).where(SponsorshipEvent.cls == "declared_sponsorship", SponsorshipEvent.domain == "acme.com")).all()
        assert len(evs) == 5 and len({e.episode_id for e in evs}) == 5           # one per episode: a running campaign, not boilerplate
        b = s.scalar(select(Brand).where(Brand.primary_domain == "acme.com"))
        assert b.n_events == 5 and b.status == "active"


# ───────────────────────── brand identity ─────────────────────────
def test_domain_merge_no_name_only_merge_and_denylist(db):
    with session_scope() as s:
        mk_show(s, "shw_1", "One", v=BASE)
        mk_show(s, "shw_2", "Two", v=peak_vec(BASE, 2))
        ep(s, "shw_1", "E1", 2, "Sponsored by Acme. Visit www.acme.com/one for 10% off.")
        ep(s, "shw_2", "E2", 3, "Thanks to our sponsor: shop.acme.com/two use code TWO")
        ep(s, "shw_2", "E3", 4, "This episode is sponsored by Zeta Labs.")                     # name only, no domain anywhere
        ep(s, "shw_1", "E4", 5, "This episode is sponsored by Zeta Labs Inc.")                 # different name string
        ep(s, "shw_1", "E5", 6, "Sponsored by Spotify. Listen on open.spotify.com/show/abc")   # platform: never a brand
    scan(["shw_1", "shw_2"])
    with session_scope() as s:
        acme = s.scalars(select(Brand).where(Brand.primary_domain == "acme.com")).all()
        assert len(acme) == 1 and acme[0].n_shows == 2                                       # same registrable domain -> one brand
        assert "Acme" in (acme[0].aliases or [])                                             # name seen in the same sentence
        zetas = s.scalars(select(Brand).where(Brand.name.ilike("zeta%"))).all()
        assert len(zetas) == 2 and all(z.identity == "name_only" for z in zetas)            # never merged on name similarity
        assert not s.scalar(select(BrandDomain).where(BrandDomain.domain.in_(("spotify.com", "open.spotify.com"))))
        assert not s.scalar(select(Brand).where(Brand.name.ilike("spotify")))                     # platform NAME: review, not a brand
        assert s.scalar(select(SponsorshipEvent).where(SponsorshipEvent.rule.like("%platform_name%"))).cls == "uncertain"


# ───────────────────────── sponsor opportunities ─────────────────────────
def _sponsor_world(s, *, member_group="Comedy", acme_days=5, member_kwargs=None):
    filler(s, 21)
    mk_show(s, "shw_m", "Member", v=BASE, groups=[member_group], **(member_kwargs or {}))
    for i, sid in enumerate(("shw_a", "shw_b", "shw_c")):
        mk_show(s, sid, f"Neighbour {sid[-1].upper()}", v=peak_vec(BASE, 10 + i))
        for k in range(3):
            ep(s, sid, f"{sid} ep {k}", acme_days + 3 * k + i, ACME_AD)


def _brand(s, domain="acme.com"):
    return s.scalar(select(Brand).where(Brand.primary_domain == domain))


def _cats(bid, cats):
    with session_scope() as s:
        rv.set_categories(s, bid, cats, "test")


def _compute(s, member="shw_m", cfg=None):
    return sp.compute(s, Corpus.load(s, AS_OF), sp.BrandIndex.load(s), member, cfg or sp.get_config())


def test_sponsor_opportunity_found_with_faithful_explanation_and_four_measures(db):
    with session_scope() as s:
        _sponsor_world(s)
    scan()
    with session_scope() as s:
        _cats(_brand(s).id, ["business_software"])
    with session_scope() as s:
        res = _compute(s)
        assert len(res["qualified"]) == 1
        r = res["qualified"][0]
        assert r["type"] == "sponsor" and r["target_title"] == "Acme"
        assert r["explanation"]["faithfulness_problems"] == [] and "similar to yours" in r["explanation"]["text"]
        st = {f["name"]: f["status"] for f in r["factors"]}
        assert st["audience_size_fit"] == "disabled" and st["geo_fit"] == "disabled"
        assert r["conversion"]["label"] == "Not enough data yet"
        assert r["contact_status"]["status"] == "website_only" and "not a verified contact" in r["contact_status"]["label"]


def test_mandatory_verified_only_for_registered_advertiser_and_no_email_or_person_in_output(db):
    with session_scope() as s:
        _sponsor_world(s)
        ep(s, "shw_a", "contact ep", 2, ACME_AD + " Questions? Email jane.doe@acme.com or call Jane Doe.")
    scan()
    with session_scope() as s:
        r = _compute(s)["qualified"][0]
        assert r["readiness"]["level"] != "verified" and r["contact_status"]["status"] != "registered"
        bid = r["target_show_id"]
    app = FastAPI()
    app.include_router(sponsors_router)
    c = TestClient(app, headers=TOKEN_HEADERS)
    with session_scope() as s:
        rv.link(s, bid, {"advertiser_ref": "adv1", "active_campaign": True, "campaign_categories": ["Comedy"]}, "admin")
    with session_scope() as s:
        r2 = _compute(s)["qualified"][0]
        assert r2["readiness"]["level"] == "verified" and r2["contact_status"]["label"] == "Registered on PodBae"
    c.post("/v1/sponsor-opportunities/generate", json={"member_show_id": "shw_m"})
    from app.intel.trust import jobs
    jobs.run_pending()
    blobs = [c.get("/v1/sponsor-opportunities", params={"member_show_id": "shw_m"}).text, c.get("/v1/shows/shw_a/sponsors").text,
             c.get("/v1/admin/sponsors/brands").text, c.get("/v1/admin/sponsors/review/queue").text]
    for b in blobs:
        assert not EMAIL.search(b), EMAIL.search(b)
        assert "Jane Doe" not in b.replace("[email removed]", "")


def test_gates_inactive_already_sponsoring_kids_alcohol_blocked_at_high_fit_and_exclusivity(db):
    with session_scope() as s:
        _sponsor_world(s)
        for i, sid in enumerate(("shw_a", "shw_b")):           # Brewco: alcohol, also active on neighbours
            ep(s, sid, "brew", 4 + i, "Today's sponsor is Brewco. Head to brewco.com/show for craft beer and wine, code SHOW.")
        ep(s, "shw_a", "old", 300, "Sponsored by Oldco. Visit oldco.com/x for 10% off.")
        ep(s, "shw_b", "old2", 310, "Sponsored by Oldco. Visit oldco.com/y for 10% off.")
    scan()
    with session_scope() as s:
        acme, brew, old = _brand(s), _brand(s, "brewco.com"), _brand(s, "oldco.com")
        ids = acme.id, brew.id
        assert old.status == "inactive"
    _cats(ids[0], ["business_software"])
    _cats(ids[1], ["alcohol"])
    with session_scope() as s:
        rej = {r["candidate_show_id"]: r["reason"] for r in _compute(s)["rejections"]}
        assert rej.get(old.id) == "inactive_brand"
        assert ids[0] not in rej and ids[1] not in rej
    # Kids & Family member: alcohol gated by default
    with session_scope() as s:
        record(s, "show", "shw_m", "category_group", ["Kids & Family"], source=get_source(s, "rss", "rss"), tier="verified", method="rule")
    with session_scope() as s:
        rej = {r["candidate_show_id"]: r for r in _compute(s)["rejections"]}
        assert rej[ids[1]]["reason"] == "sensitive_category_default", rej
    # blocked brand category excluded BEFORE scoring even though Acme scores >= 95-level evidence on every factor
    with session_scope() as s:
        creator = get_source(s, "creator_declared", "creator")
        record(s, "show", "shw_m", "creator.blocked_brand_categories", ["business_software"], source=creator, tier="creator_provided", method="manual")
    with session_scope() as s:
        res = _compute(s)
        assert {r["candidate_show_id"]: r["reason"] for r in res["rejections"]}[ids[0]] == "blocked_brand_category"
        assert ids[0] not in {r["target_show_id"] for r in res["scored"]}
    # already sponsors the member
    with session_scope() as s:
        ep(s, "shw_m", "own", 2, ACME_AD)
    scan(["shw_m"])
    with session_scope() as s:
        record(s, "show", "shw_m", "creator.blocked_brand_categories", [], source=get_source(s, "creator_declared", "creator"),
               tier="creator_provided", method="manual")
    with session_scope() as s:
        assert {r["candidate_show_id"]: r["reason"] for r in _compute(s)["rejections"]}[ids[0]] == "already_sponsors_member"


def test_competitor_exclusivity_gate(db):
    with session_scope() as s:
        _sponsor_world(s)
        for sid in ("shw_a", "shw_b"):
            ep(s, sid, "rival", 6, "Sponsored by Rival. Visit rival.com/show for 15% off.")
        ep(s, "shw_m", "mine", 3, "Sponsored by Rival. Visit rival.com/me for 15% off.")     # member's current sponsor
    scan()
    with session_scope() as s:
        a, rival = _brand(s), _brand(s, "rival.com")
    _cats(a.id, ["business_software"])
    _cats(rival.id, ["business_software"])
    with session_scope() as s:
        record(s, "show", "shw_m", "creator.exclusive_categories", ["business_software"], source=get_source(s, "creator_declared", "creator"),
               tier="creator_provided", method="manual")
    with session_scope() as s:
        rej = {r["candidate_show_id"]: r["reason"] for r in _compute(s)["rejections"]}
        assert rej.get(a.id) == "competitor_exclusivity", rej


def test_determinism_missing_data_and_no_padding(db):
    with session_scope() as s:
        _sponsor_world(s)
    scan()
    with session_scope() as s:
        b = _brand(s)
        b.categories, b.category_method = [], "none"            # no categories -> category_fit missing, renormalised
    with session_scope() as s:
        r1, r2 = _compute(s), _compute(s)
        assert r1["result_hash"] == r2["result_hash"]
        row = r1["scored"][0]
        cf = next(f for f in row["factors"] if f["name"] == "category_fit")
        assert cf["status"] == "missing" and cf["effective_weight"] == 0
        assert "category_fit" in row["confidence"]["missing_factors"]
        cfg = sp.get_config()
        cfg["ranking"]["min_fit"] = 99
        r3 = _compute(s, cfg=cfg)
        assert r3["qualified"] == [] and r3["state"]["state"] == "no_match" and r3["scored"]   # never padded


def test_review_flow_precision_and_machine_reviewer_rejected(db):
    with session_scope() as s:
        mk_show(s, "shw_q", "Q", v=BASE)
        ep(s, "shw_q", "E1", 2, "This podcast is brought to you by our friends.")
    scan(["shw_q"])
    with session_scope() as s:
        unc = s.scalar(select(SponsorshipEvent).where(SponsorshipEvent.cls == "uncertain"))
        assert unc is not None
        with pytest.raises(rv.ReviewError):
            rv.save(s, unc.id, "claude", "ok", "declared_sponsorship")
        out = rv.save(s, unc.id, "Ana", "reject")
        assert out["verification_status"] == "reviewed_rejected"
        p = rv.precision(s)
        assert p["per_class"]["uncertain"]["reviewed"] == 1 and p["reviewers"] == ["Ana"]
        q = rv.queue(s, "Ana")
        assert q["items"][0]["my_verdict"]["verdict"] == "reject"


def test_no_llm_and_service_token_on_sponsor_routes(db, monkeypatch):
    from app.intel.understanding import providers
    monkeypatch.setattr(providers, "get_provider", lambda *a, **k: (_ for _ in ()).throw(AssertionError("LLM requested")))
    with session_scope() as s:
        _sponsor_world(s)
    scan()
    sp.generate("shw_m", as_of=AS_OF)
    with session_scope() as s:
        assert s.scalar(select(func.count()).select_from(CostLedger).where(CostLedger.operation.like("llm%"))) == 0
        assert s.scalar(select(func.count()).select_from(Provenance).where(Provenance.method == "llm")) == 0
    app = FastAPI()
    app.include_router(sponsors_router)
    bare = TestClient(app)
    for m, path in (("get", "/v1/sponsor-opportunities?member_show_id=shw_m"), ("post", "/v1/sponsor-opportunities/generate"),
                    ("get", "/v1/admin/sponsors/stats"), ("get", "/v1/admin/sponsors/review/queue"), ("get", "/v1/admin/sponsors/brands"),
                    ("get", "/v1/shows/shw_m/sponsors"), ("post", "/v1/sponsors/registrations"), ("get", "/v1/admin/engine/sponsor-metrics")):
        assert getattr(bare, m)(path, **({"json": {}} if m == "post" else {})).status_code == 401, path


def test_sponsor_events_with_positions_and_public_sponsors_seen_declared_only(db):
    from app.opportunities.api import router as opp_router
    with session_scope() as s:
        _sponsor_world(s)
        ep(s, "shw_a", "likely only", 1, "Get 20% off at maybeco.com with code SHOW")             # likely: never on the public list
    scan()
    sp.generate("shw_m", as_of=AS_OF)
    app = FastAPI()
    app.include_router(sponsors_router)
    app.include_router(opp_router)
    c = TestClient(app, headers=TOKEN_HEADERS)
    lst = c.get("/v1/sponsor-opportunities", params={"member_show_id": "shw_m", "user_id": "u1"}).json()
    item = lst["items"][0]
    assert item["type"] == "sponsor" and item["fit"]["note"].startswith("Vibe Logic draft") and item["contact_status"]
    ev = c.post("/v1/events", json={"events": [{"opportunity_id": item["id"], "type": "impression", "user_id": "u1", "position": 1,
                                                "idempotency_key": "imp:x"}]})
    assert ev.status_code == 200
    assert c.post("/v1/events", json={"events": [{"opportunity_id": item["id"], "type": "dismiss", "user_id": "u1",
                                                  "reason": "category_conflict"}]}).status_code == 200
    seen = c.get("/v1/shows/shw_a/sponsors").json()["sponsors"]
    assert [x["name"] for x in seen] == ["Acme"]
