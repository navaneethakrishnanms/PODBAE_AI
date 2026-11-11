"""Identity/dedupe evaluation on a constructed set of known duplicates and known look-alikes (synthetic feeds served locally).
Doubles as a regression test (thresholds below) and writes eval/dedupe_results.json for EVAL_LAYER1.md.
This measures our identity RULES on cases we thought of; it is not a claim about real-world dedupe accuracy."""
from __future__ import annotations

import json
from itertools import combinations
from pathlib import Path

from app.intel import ingest
from tests.feedgen import make_feed

OUT = Path(__file__).resolve().parents[1] / "eval" / "dedupe_results.json"


def test_dedupe_precision_recall(db, server):
    # (feed path, kwargs for make_feed, ground-truth entity, scenario)
    cases: list[tuple[str, dict, str, str]] = []

    def add(path, ent, scenario, **kw):
        cases.append((path, kw, ent, scenario))

    # ---------- true duplicates ----------
    add("/dup1/a.xml", "E1", "baseline", title="Alpha Show", n=8, guid_prefix="a")
    add("/dup1/a.xml?utm_source=newsletter", "E1", "tracking param", title="Alpha Show", n=8, guid_prefix="a")
    add("/dup1/a.xml/", "E1", "trailing slash", title="Alpha Show", n=8, guid_prefix="a")
    add("/dup2/orig.xml", "E2", "baseline", title="Beta Cast", n=8, guid_prefix="b", podcast_guid="11111111-aaaa-5bbb-8ccc-000000000001")
    add("/dup2/mirror-other-host.xml", "E2", "same podcast:guid, title edited", title="Beta Cast (Official Feed)", n=8, guid_prefix="bb",
        podcast_guid="11111111-aaaa-5bbb-8ccc-000000000001")
    add("/dup3/orig.xml", "E3", "baseline", title="Gamma Hour", n=10, guid_prefix="g")
    add("/dup3/feedburner.xml", "E3", "mirror: same title + same episodes, no guid tag", title="Gamma Hour", n=10, guid_prefix="g")
    add("/dup3/partial.xml", "E3", "mirror with 80% episode overlap", title="Gamma Hour", n=10, guid_prefix="g", skip_guids={"g-8", "g-9"})
    add("/dup4/old.xml", "E4", "baseline", title="Delta Talk", n=8, guid_prefix="d", podcast_guid="22222222-aaaa-5bbb-8ccc-000000000002")
    add("/dup4/new.xml", "E4", "moved feed (itunes:new-feed-url + same guid)", title="Delta Talk", n=8, guid_prefix="d",
        podcast_guid="22222222-aaaa-5bbb-8ccc-000000000002")
    # known hard cases we EXPECT to miss: host migration changed every episode guid and there is no podcast:guid
    add("/hard1/a.xml", "E5", "baseline", title="Epsilon Weekly", n=8, guid_prefix="e1")
    add("/hard1/b.xml", "E5", "HARD: migrated host, all new episode guids, no podcast:guid", title="Epsilon Weekly", n=8, guid_prefix="e2")

    # ---------- look-alikes that must NOT merge ----------
    add("/neg/s1.xml", "N1", "negative baseline", title="Morning Notes", n=8, guid_prefix="ep")            # default 'ep-N' guids...
    add("/neg/s2.xml", "N2", "different title, identical guid strings", title="Evening Stories", n=8, guid_prefix="ep")
    add("/neg/s3.xml", "N3", "homonym: same title, different episodes", title="Daily Update", n=8, guid_prefix="du1")
    add("/neg/s4.xml", "N4", "homonym: same title, different episodes", title="Daily Update", n=8, guid_prefix="du2")
    add("/neg/s5.xml", "N5", "same title, different language", title="Daily Update", n=8, guid_prefix="du3", lang="de",
        desc="Ein tägliches Update über Gartenarbeit und Kochen in der Nachbarschaft für alle Hörer.")
    add("/neg/s6.xml", "N6", "near-identical title", title="Garden Talk", n=8, guid_prefix="gt1")
    add("/neg/s7.xml", "N7", "near-identical title", title="Garden Talks", n=8, guid_prefix="gt2")
    add("/neg/s8.xml", "N8", "same title, 30% overlap only", title="Shared Name", n=10, guid_prefix="sn")
    add("/neg/s9.xml", "N9", "same title, 30% overlap only", title="Shared Name", n=17, guid_prefix="sn", skip_guids={f"sn-{i}" for i in range(0, 7)})

    ids: list[str] = []
    for path, kw, _ent, _sc in cases:
        base = path.split("?")[0]
        title = kw.pop("title")
        n = kw.pop("n")
        body = make_feed(title, n, **kw)
        if base.endswith("/dup4/new.xml") or path == "/dup4/old.xml":
            pass
        server.set(base, body)
        if path == "/dup4/old.xml":     # old URL advertises the new one
            server.set(base, make_feed(title, n, new_feed_url=server.base + "/dup4/new.xml", **kw))
        ids.append(ingest.run_pipeline(server.base + path)["show_id"])
    truth = [c[2] for c in cases]

    tp = fp = fn = tn = 0
    errors = []
    for i, j in combinations(range(len(cases)), 2):
        same_t, same_p = truth[i] == truth[j], ids[i] == ids[j]
        tp += same_t and same_p
        fp += (not same_t) and same_p
        fn += same_t and not same_p
        tn += (not same_t) and not same_p
        if same_t != same_p:
            errors.append({"a": f"{cases[i][3]} [{cases[i][0]}]", "b": f"{cases[j][3]} [{cases[j][0]}]", "truth_same": same_t, "predicted_same": same_p})
    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = tp / (tp + fn) if tp + fn else 1.0
    res = {"feeds": len(cases), "true_entities": len(set(truth)), "predicted_shows": len(set(ids)), "pairs": tp + fp + fn + tn,
           "tp": tp, "fp": fp, "fn": fn, "tn": tn, "precision": round(precision, 4), "recall": round(recall, 4), "errors": errors,
           "note": "synthetic duplicates/look-alikes built by us; includes 1 deliberately hard case (all-new episode guids) we expect to miss"}
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(res, indent=1), encoding="utf-8")
    assert precision == 1.0, errors           # we never merge different shows (in this constructed set)
    assert recall >= 0.85, errors             # all realistic duplicates caught; only the deliberately hard case may be missed
    assert {e["a"].split("[")[1] for e in errors} <= {"/hard1/a.xml]"}, errors
