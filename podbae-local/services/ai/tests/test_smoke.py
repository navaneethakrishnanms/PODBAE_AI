from app.intel import ingest
from app.intel.db import session_scope
from app.intel.models import Episode, Show
from app.intel.profile import build_profile
from sqlalchemy import select, func
from tests.feedgen import make_feed


def test_pipeline_smoke(db, server):
    url = server.set("/a.xml", make_feed("Garden Chat", 8, categories=["Leisure"]))
    res = ingest.run_pipeline(url)
    assert res["feed"]["status"] == "ok"
    with session_scope() as s:
        p = build_profile(s, res["show_id"])
        assert p["fields"]["title"]["value"] == "Garden Chat"
        assert p["fields"]["topics"]["data_tier"] == "inferred"
        print({k: (v["data_tier"], v["freshness"]) for k, v in p["fields"].items()})
        print(p["completeness"], [i["code"] for i in p["improve"]], res)
