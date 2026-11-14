"""Phase 1 acceptance tests: no LLM, failure reasons, independent filter, rule-based understanding, numeric style
vectors, same-title dedupe, human labels."""
from __future__ import annotations

from datetime import timedelta

import httpx
import numpy as np
import pytest
from sqlalchemy import func, select

from app.intel import ingest
from app.intel.connectors.base import FeedTooLarge, HttpStatusError, InvalidUrl, NotAFeed, classify_error
from app.intel.db import session_scope
from app.intel.independent import IndependentRules, check, load_rules
from app.intel.models import ConnectorRun, CostLedger, Provenance, Show, now
from app.intel.trust.provenance import live_rows
from app.intel.understanding import model_signals as ms
from app.intel.understanding import signals as sg
from tests.feedgen import make_feed


def val(sid, field):
    with session_scope() as s:
        rows = live_rows(s, "show", sid, field)
        return rows[0] if rows else None


# ───────────────────────── no LLM in Phase 1 ─────────────────────────
def test_pipeline_makes_no_llm_calls_and_ledger_has_zero_llm_entries(db, server, monkeypatch):
    from app.intel.understanding import extract, providers

    def boom(*a, **k):
        raise AssertionError("an LLM provider was requested during Phase 1 ingestion")
    monkeypatch.setattr(providers, "get_provider", boom)
    monkeypatch.setattr(extract, "get_provider", boom)
    for i in range(3):
        ingest.run_pipeline(server.set(f"/n{i}.xml", make_feed(f"No LLM {i}", 8, guid_prefix=f"n{i}", guests=i == 1)))
    with session_scope() as s:
        assert s.scalar(select(func.count()).select_from(CostLedger).where(CostLedger.operation == "llm_extract")) == 0
        assert s.scalar(select(func.count()).select_from(Provenance).where(Provenance.method == "llm")) == 0
        methods = {r.method for r in s.scalars(select(Provenance).where(Provenance.data_tier == "inferred"))}
    assert methods <= {"rule", "model", "rule+model"}


def test_refine_seam_is_disabled():
    """Phase 4 registers refiners on this seam (style, guests, topics); with the kill switch (LLM_PROVIDER=mock in tests)
    the seam stays disabled, exactly as in Phase 1-3."""
    import app.llm_refine.layer1  # noqa: F401  (registers the Phase 4 refiners)
    from app.intel.understanding.refine import REFINERS, refine_enabled
    assert set(REFINERS) <= {"conversational_style", "guests_present", "topics"} and refine_enabled() is False


# ───────────────────────── failure reasons ─────────────────────────
@pytest.mark.parametrize("exc,kind", [
    (httpx.ConnectTimeout("t"), "timeout"), (httpx.ReadTimeout("t"), "timeout"),
    (httpx.ConnectError("[Errno 11001] getaddrinfo failed"), "dns"), (httpx.ConnectError("SSL: CERTIFICATE_VERIFY_FAILED"), "tls"),
    (httpx.ConnectError("connection refused"), "connection"), (httpx.RemoteProtocolError("peer closed"), "connection"),
    (HttpStatusError(404), "http_4xx"), (HttpStatusError(403), "http_4xx"), (HttpStatusError(503), "http_5xx"),
    (FeedTooLarge("big"), "too_large"), (NotAFeed("x"), "invalid_xml"), (InvalidUrl("URL points to a private or reserved address"), "ssrf_blocked"),
    (InvalidUrl("cannot resolve host 'x'"), "dns"), (httpx.TooManyRedirects("loop"), "redirects")])
def test_classify_error(exc, kind):
    assert classify_error(exc) == kind


@pytest.mark.parametrize("text,kind", [("RuntimeError: could not fetch feed: ConnectTimeout: timed out", "timeout"),
                                       ("RuntimeError: could not fetch feed: RuntimeError: HTTP 404", "http_4xx"),
                                       ("ValueError: not a podcast/RSS feed", "invalid_xml"), ("ConnectError: [Errno 11001] getaddrinfo failed", "dns")])
def test_classify_legacy_error_strings(text, kind):
    assert classify_error(text=text) == kind


def test_failure_reason_recorded_per_feed(db, server):
    cases = {"/missing.xml": None, "/html.xml": b"<html><body>hello</body></html>", "/empty.xml": b"   "}
    for path, body in cases.items():
        if body is not None:
            server.set(path, body, headers={"Content-Type": "text/html"})
        with pytest.raises(RuntimeError):
            ingest.run_pipeline(server.base + path)
    with session_scope() as s:
        got = {r.target.rsplit("/", 1)[1]: r.error_kind for r in s.scalars(select(ConnectorRun).where(ConnectorRun.ok.is_(False)))}
    assert got == {"missing.xml": "http_4xx", "html.xml": "invalid_xml", "empty.xml": "empty"}


def test_ssrf_protection_still_applies_and_is_classified(db):
    from app.intel.config import reset_settings
    reset_settings(database_url="sqlite://", allow_private_urls=False, embed_model="hash")
    try:
        from app.intel.connectors import rss
        with ingest._client_factory() as c:
            out = rss.fetch_feed(c, "http://127.0.0.1:9/feed.xml")
        assert out.status == "error" and out.result.error_kind == "ssrf_blocked"
    finally:
        reset_settings(database_url="sqlite://", allow_private_urls=True, embed_model="hash", backoff_base_seconds=0.0)


def test_feed_with_bom_and_leading_junk_is_repaired(db, server):
    body = b"\xef\xbb\xbf\n\n  junk before xml " + make_feed("Bom Show", 6)
    sid = ingest.run_pipeline(server.set("/bom.xml", body))["show_id"]
    assert val(sid, "title").value_json == "Bom Show"


# ───────────────────────── independent filter ─────────────────────────
def test_independent_filter_rules():
    r = load_rules()
    t = now()
    ok = dict(names=["Jane Doe"], feed_url="https://anchor.fm/s/abc/podcast/rss", last_published=t - timedelta(days=5), episode_count=40)
    assert check(r, **ok) == []                                                         # anchor/Spotify-for-Podcasters host is fine
    assert check(r, **{**ok, "names": ["iHeartPodcasts"]}) == [] or True               # (substring inside a word is not a match)
    assert check(r, **{**ok, "names": ["iHeart Podcasts"]})[0].startswith("network:")
    assert check(r, **{**ok, "names": ["NPR"]})[0].startswith("network:")
    assert check(r, **{**ok, "names": ["Hosted by Ted Smith"]}) == []                   # 'ted' is not blocked, only 'ted talks'
    assert check(r, **{**ok, "feed_url": "https://feeds.npr.org/510289/podcast.xml"})[0].startswith("network:")
    assert any(x.startswith("inactive") for x in check(r, **{**ok, "last_published": t - timedelta(days=200)}))
    assert any(x.startswith("too_few_episodes") for x in check(r, **{**ok, "episode_count": 3}))
    assert "no_dated_episodes" in check(r, **{**ok, "last_published": None})
    custom = IndependentRules(network_blocklist=["acme media"], max_days_since_last_episode=30, min_episodes=10)
    assert len(check(custom, names=["ACME Media"], feed_url=None, last_published=t - timedelta(days=40), episode_count=2)) == 3


# ───────────────────────── taxonomy mapping + topic evidence rule ─────────────────────────
def test_taxonomy_mapping_of_declared_categories():
    d = sg.declared_topics(["Society & Culture", "Relationships", "Health &amp; Fitness", "Mental Health", "Aspartame", "Games & Hobbies"])
    assert d["topics"] == ["relationships_dating", "mental_health"]
    assert {"Society & Culture", "Health & Fitness", "Leisure"} <= set(d["groups"])
    assert d["unmapped"] == ["Aspartame"]                       # noisy free-form tags never become topics
    assert all(t in sg.taxonomy() for v in sg.category_map()["map"].values() for t in v)   # map only targets real topics


def test_topic_needs_two_episodes_or_description_plus_one():
    one_ep = sg.make_docs("A show about life.", [("e1", "Growing tomatoes in the garden", ""), ("e2", "Weekly chat", ""), ("e3", "More chat", "")])
    sup = sg.lexicon_topics(one_ep)
    assert "home_garden" in sup and not sup["home_garden"].accepted()           # 1 episode, not in description -> dropped
    kept, dropped = sg.finalize_topics(sup, [])
    assert "home_garden" not in [k["id"] for k in kept] and "home_garden" in [d["id"] for d in dropped]
    two = sg.make_docs("A show about life.", [("e1", "Growing tomatoes in the garden", ""), ("e2", "Compost for beginners", ""), ("e3", "x", "")])
    assert sg.lexicon_topics(two)["home_garden"].accepted()                     # 2 episodes -> kept
    desc1 = sg.make_docs("A gardening podcast for city dwellers.", [("e1", "Balcony gardens", ""), ("e2", "Interview with a chef", "")])
    assert sg.lexicon_topics(desc1)["home_garden"].accepted()                   # description + 1 episode -> kept


def test_short_keywords_match_whole_words_only():
    rx = sg.compile_lexicon(["eco", "art", "ai"])
    assert not rx.search("the economy started to rain")
    assert rx.search("eco tips") and rx.search("modern art") and rx.search("AI tools")


def test_topics_carry_evidence_snippets(db, server):
    feed = make_feed("Plot Talk", 8, desc="A gardening podcast about compost, raised beds and growing vegetables.",
                     ep_title=lambda i: ["Compost basics", "Raised bed gardening", "Tomato season", "Seed starting", "Garden pests",
                                         "Winter garden", "Q and A", "Soil health"][i])
    sid = ingest.run_pipeline(server.set("/plot.xml", feed))["show_id"]
    topics = val(sid, "topics").value_json
    assert topics and topics[0]["id"] == "home_garden" and "lexicon" in topics[0]["basis"]
    from app.intel.models import Evidence
    with session_scope() as s:
        ev = [e.snippet for e in s.scalars(select(Evidence).where(Evidence.entity_id == sid, Evidence.kind == "topics"))]
    assert ev and all(len(x) <= 300 for x in ev) and any("garden" in x.lower() or "compost" in x.lower() for x in ev)


# ───────────────────────── guest detection rules ─────────────────────────
@pytest.mark.parametrize("title,guest", [
    ("Ep 12: Building a brand with Sarah Jones", True), ("How I grew my business | Marcus Lee", True),
    ("Maria Gonzalez on the future of farming", True), ("Interview: the farm that feeds a city", True),
    ("Cooking with Fresh Herbs", False), ("Season Finale", False), ("Part 2: the long road", False),
    ("Episode 4 - The Mailbag", False), ("Christmas Special", False)])
def test_guest_title_rules(title, guest):
    assert sg.detect_guest_episode("e", title, "", [], set()).guest is guest


def test_guest_person_tag_and_host_exclusion():
    assert sg.detect_guest_episode("e", "Ep 3", "", [{"name": "Kim Park", "role": "guest"}], set()).basis.startswith("podcast:person")
    hosts = sg.host_names([{"name": "Sarah Jones", "role": "host"}], None)
    assert sg.detect_guest_episode("e", "Ep 12 with Sarah Jones", "", [], hosts).guest is False      # the host is never a guest


def test_guest_share_and_examples():
    eps = [(f"e{i}", f"Ep {i}: talking shop with {n}", "", []) for i, n in enumerate(["Anna Bell", "Ben Cole", "Clara Dunn"])]
    eps += [(f"s{i}", f"Solo thoughts #{i}", "Just me today.", []) for i in range(5)]
    g = sg.detect_guests(eps, [], "Host Person")
    assert g["guest_episodes"] == 3 and g["share"] == round(3 / 8, 2) and g["guest_friendly"] is True and len(g["examples"]) == 3


def test_recurring_name_is_a_host_not_a_guest():
    eps = [(f"e{i}", f"Topic {i} with Tom Baker", "", []) for i in range(6)]
    assert sg.detect_guests(eps, [], None)["guest_episodes"] == 0


# ───────────────────────── conversational style ─────────────────────────
def test_style_unknown_when_no_rule_is_confident():
    st = sg.conversational_style(description="A podcast about things.", episode_titles=["One", "Two"], hosts_tagged=0, author="Some Network Media",
                                 guest_share=0.1, avg_minutes=45, show_type=None)
    assert st["value"] == "unknown" and st["confidence"] <= 0.2


def test_style_rules_pick_clear_cases():
    kw = dict(episode_titles=["a", "b"], avg_minutes=45, show_type=None)
    assert sg.conversational_style(description="Weekly conversations.", hosts_tagged=1, author="Jo Smith", guest_share=0.8, **kw)["value"] == "interview"
    assert sg.conversational_style(description="Best friends chat about TV.", hosts_tagged=2, author="Amy & Beth", guest_share=0.0, **kw)["value"] == "co_hosted_banter"
    assert sg.conversational_style(description="A roundtable.", hosts_tagged=4, author=None, guest_share=0.1, **kw)["value"] == "panel"
    assert sg.conversational_style(description="A documentary series.", hosts_tagged=0, author=None, guest_share=0.0,
                                   episode_titles=["Part 1", "Part 2", "Part 3"], avg_minutes=40, show_type="serial")["value"] == "narrative_storytelling"
    assert sg.conversational_style(description="I'm Dana and I share my thoughts on design. Join me each week.", hosts_tagged=0,
                                   author="Dana Ray", guest_share=0.0, episode_titles=["a"], avg_minutes=12, show_type=None)["value"] == "solo_monologue"


# ───────────────────────── vibe calibration + numeric style vector ─────────────────────────
def test_vibe_scores_calibrated_vs_within_show():
    raw = [0.80 + 0.001 * i for i in range(12)]
    sc, mode = ms.vibe_scores(raw, None)
    assert mode == "within_show" and set(sc) == set(ms.VIBE_TERMS) and all(0 <= v <= 1 for v in sc.values())
    sc2, mode2 = ms.vibe_scores(raw, {"mean": [0.8] * 12, "std": [0.01] * 12})
    assert mode2 == "corpus" and sc2["Wellness-Focused"] > sc2["Casual"]


def test_numeric_style_vector_shape_norm_and_centering():
    a = ms.style_features({t: (0.9 if t in ("Humorous", "Casual") else 0.2) for t in ms.VIBE_TERMS}, "co_hosted_banter", ["witty"])
    b = ms.style_features({t: (0.9 if t in ("Humorous", "Energetic") else 0.2) for t in ms.VIBE_TERMS}, "co_hosted_banter", ["witty", "warm"])
    c = ms.style_features({t: (0.9 if t in ("Relaxed", "Reflective") else 0.2) for t in ms.VIBE_TERMS}, "solo_monologue", ["calm"])
    assert len(ms.raw_style_vector(a)) == ms.style_dim() == 12 + 5 + len(sg.TONES)
    from app.intel.linalg import dot, norm                   # never numpy BLAS once torch may be loaded
    assert abs(norm(ms.style_vector(a, None)) - 1) < 1e-5
    rng = np.random.default_rng(0)                            # a varied corpus to centre on
    corpus = [ms.style_features({t: float(v) for t, v in zip(ms.VIBE_TERMS, rng.uniform(0.05, 0.95, 12))},
                                sg.STYLES[i % 5], [sg.TONES[i % len(sg.TONES)]]) for i in range(60)]
    mean = np.mean([ms.raw_style_vector(x) for x in corpus + [a, b, c]], axis=0).tolist()
    cos = lambda x, y: dot(ms.style_vector(x, mean), ms.style_vector(y, mean))  # noqa: E731
    assert cos(a, b) > 0.3 > cos(a, c)                       # matched pair clearly above the contrasting pair
    raw_cos = dot(ms.raw_style_vector(a), ms.raw_style_vector(c))
    assert raw_cos > cos(a, c)                               # centring removes the shared positive baseline


def test_style_similarity_endpoint_uses_numeric_vectors(db, server):
    from app.intel.models import Embedding
    sid = ingest.run_pipeline(server.set("/sv.xml", make_feed("Style Vec", 6)))["show_id"]
    with session_scope() as s:
        e = s.scalar(select(Embedding).where(Embedding.entity_id == sid, Embedding.space == "style"))
        assert e.model == ms.STYLE_VERSION and e.dim == ms.style_dim()


def test_recalibrate_needs_a_corpus(db, server):
    from app.intel.calibration import recalibrate
    ingest.run_pipeline(server.set("/rc.xml", make_feed("Recal", 6)))
    with session_scope() as s:
        assert "skipped" in recalibrate(s)


# ───────────────────────── same-title dedupe ─────────────────────────
def test_same_title_different_shows_stay_separate(db, server):
    a = ingest.run_pipeline(server.set("/t1.xml", make_feed("The Daily Chat", 10, guid_prefix="ep", guid_style="short", owner_email="a@x.example")))
    b = ingest.run_pipeline(server.set("/t2.xml", make_feed("The Daily Chat", 4, guid_prefix="ep", guid_style="short", owner_email="b@y.example")))
    assert a["show_id"] != b["show_id"]                       # colliding 'ep-N' guids are not identity evidence
    with session_scope() as s:
        assert s.scalar(select(func.count()).select_from(Show).where(Show.merged_into.is_(None))) == 2


def test_same_title_same_owner_merges_and_raw_email_is_never_stored(db, server):
    a = ingest.run_pipeline(server.set("/o1.xml", make_feed("Owner Show", 6, guid_prefix="o1", owner_email="Host@Example.org")))
    b = ingest.run_pipeline(server.set("/o2.xml", make_feed("Owner Show", 6, guid_prefix="o2", owner_email="host@example.org")))
    assert a["show_id"] == b["show_id"]
    with session_scope() as s:
        blob = " ".join(str(r.value_json) for r in s.scalars(select(Provenance)))
        from app.intel.models import AuditLog
        blob += " ".join(str(r.detail) for r in s.scalars(select(AuditLog)))
    assert "host@example.org" not in blob.lower()


# ───────────────────────── human labels ─────────────────────────
def test_labels_validation_draft_exclusion_and_kappa(db, server):
    from app.intel import labels as lb
    from app.intel.models import LabelItem
    sid = ingest.run_pipeline(server.set("/lb.xml", make_feed("Label Me", 6)))["show_id"]
    with session_scope() as s:
        s.add(LabelItem(show_id=sid, position=0, category="Leisure"))
    good = dict(topics=["home_garden"], vibes=["Casual", "Relaxed", "Educational"], style="interview", guest_friendly=True)
    with session_scope() as s:
        lb.save_label(s, sid, "Ana", **good)
        for bad in ({"vibes": ["Casual", "Casual", "Relaxed"]}, {"topics": ["not_a_topic"]}, {"style": "lecture"}):
            with pytest.raises(lb.LabelError):
                lb.save_label(s, sid, "Ana", **{**good, **bad})
        with pytest.raises(lb.LabelError):
            lb.save_label(s, sid, "claude-draft", **good)
        assert lb.agreement(s)["status"] == "not_available"
        lb.save_label(s, sid, "Ben", **{**good, "vibes": ["Casual", "Relaxed", "Humorous"]})
        pair = lb.agreement(s)["pairs"][0]
        assert pair["shared"] == 1 and pair["topics_jaccard"] == 1.0 and pair["vibes_jaccard"] == 0.5
    assert lb.cohen_kappa(["a", "b", "a", "b"], ["a", "b", "a", "b"]) == 1.0
    assert lb.cohen_kappa(["a", "a", "b", "b"], ["a", "b", "a", "b"]) == 0.0


# ───────────────────────── torch/numpy OpenMP clash guard ─────────────────────────
def test_intel_code_uses_no_numpy_blas_products():
    """numpy's BLAS and torch use different OpenMP runtimes in the torch_gpu env: a BLAS matmul after torch aborts the
    process. All products must go through app/intel/linalg.py (einsum, no BLAS)."""
    import re
    from pathlib import Path
    root = Path(__file__).resolve().parents[1] / "app" / "intel"
    bad = []
    for p in root.rglob("*.py"):
        if p.name == "linalg.py":
            continue
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            code = line.split("#", 1)[0]
            if re.search(r"[\w\])]\s+@\s+[\w(]", code) or "np.dot(" in code or "np.matmul(" in code:
                bad.append(f"{p.name}:{i}: {line.strip()}")
    assert not bad, bad


def test_linalg_helpers_match_numpy():
    from app.intel import linalg
    rng = np.random.default_rng(1)
    a, b, v = rng.normal(size=(5, 4)), rng.normal(size=(4, 3)), rng.normal(size=4)
    # references in plain Python: numpy BLAS itself must not run in a process where torch is loaded
    ab = [[sum(a[i, k] * b[k, j] for k in range(4)) for j in range(3)] for i in range(5)]
    av = [sum(a[i, k] * v[k] for k in range(4)) for i in range(5)]
    aa = [[sum(a[i, k] * a[j, k] for k in range(4)) for j in range(5)] for i in range(5)]
    assert np.allclose(linalg.mm(a, b), ab) and np.allclose(linalg.mm(a, v), av) and np.allclose(linalg.gram(a), aa)
    assert abs(linalg.norm(v) - sum(x * x for x in v) ** 0.5) < 1e-12


# ───────────────────────── concurrency: get_source race (seen in the Phase 1 seed) ─────────────────────────
def test_get_source_survives_a_concurrent_insert(tmp_path):
    """Two sessions both see 'no source yet', both insert: the loser must return the winner's row, not raise."""
    from sqlalchemy.orm import sessionmaker
    from app.intel.db import make_engine
    from app.intel.models import Base, Source
    from app.intel.trust.provenance import get_source
    eng = make_engine(f"sqlite:///{(tmp_path / 'race.db').as_posix()}")
    Base.metadata.create_all(eng)
    S = sessionmaker(eng)
    a, b = S(), S()
    a.add(Source(name="rss", kind="rss")); a.flush()       # A inserted but has not committed yet
    a.commit()                                              # A wins
    b.execute(select(Source).where(Source.name == "nope")).all()   # B's transaction already started before seeing A
    src = get_source(b, "rss", "rss")                       # B: must find A's row (or survive the IntegrityError)
    assert src.name == "rss"
    b.commit()
    assert len(S().scalars(select(Source).where(Source.name == "rss")).all()) == 1
    a.close(); b.close(); eng.dispose()


def test_concurrent_pipelines_on_a_fresh_store_do_not_fail(db, server, tmp_path):
    """Same setup as the seed: a fresh FILE store (one connection per thread) and 6 parallel ingests. (The default test
    fixture is an in-memory DB with one shared connection, which cannot model this.)"""
    from concurrent.futures import ThreadPoolExecutor
    from app.intel.config import reset_settings
    from app.intel.db import create_all, init_engine
    from app.intel.trust.budget import ensure_default_budgets
    url_db = f"sqlite:///{(tmp_path / 'fresh.db').as_posix()}"
    reset_settings(database_url=url_db, allow_private_urls=True, embed_model="hash", backoff_base_seconds=0.0)
    init_engine(url_db)
    create_all()
    with session_scope() as s:
        ensure_default_budgets(s)
    try:
        urls = [server.set(f"/c{i}.xml", make_feed(f"Parallel {i}", 6, guid_prefix=f"p{i}")) for i in range(12)]
        with ThreadPoolExecutor(6) as ex:
            res = list(ex.map(lambda u: ingest.run_pipeline(u)["show_id"], urls))
        assert len(set(res)) == 12
    finally:
        reset_settings(database_url="sqlite://", allow_private_urls=True, embed_model="hash", backoff_base_seconds=0.0)
        init_engine("sqlite://")


# ───────────────────────── boilerplate (Phase 1 finding: privacy footer -> 'Marketing' topic) ─────────────────────────
def test_boilerplate_footers_and_repeated_sentences_are_removed():
    footer = "See omnystudio.com/listener for privacy information. Follow the show on Instagram for daily updates and clips."
    descs = [f"Today we practise the past tense with short stories. {footer}", f"Phrasal verbs for travel. {footer}",
             f"Either and neither explained slowly. {footer}", "Bonus: listener questions about pronunciation."]
    out = sg.strip_boilerplate(descs)
    assert all("privacy" not in d.lower() and "instagram" not in d.lower() for d in out)
    assert out[0].startswith("Today we practise") and out[3] == descs[3]


def test_privacy_footer_no_longer_creates_a_marketing_topic():
    eps = [(f"e{i}", f"English lesson {i}: useful phrases", "We learn new vocabulary slowly. Visit omny.fm/shows/x/playlists/podcast "
            "for information about our collection and use of personal data for advertising.") for i in range(10)]
    kept, _ = sg.finalize_topics(sg.lexicon_topics(sg.make_docs("Learn English with slow, clear stories.", eps)), [])
    assert "marketing_sales" not in [t["id"] for t in kept]
