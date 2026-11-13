"""The OLD scorer (weighted tag overlap, app/scoring.py) applied to the same intelligence-store shows, as the evaluation
baseline. It is mapped as faithfully as the store allows: categories -> genre, top-3 vibes -> vibe tags, tone -> tone tags,
topic + declared-topic names -> keywords, last published / episode count -> performance. There is no location in RSS, so the
location component is 0 for everyone (as it was for any show without a location). Only the member itself is excluded:
the old scorer had no eligibility gates."""
from __future__ import annotations

from datetime import timezone

from ..intel.understanding.signals import taxonomy
from ..scoring import load_config, score_one
from ..schemas import Candidate, Subject
from .features import Corpus, ShowFeatures


def _subject(sf: ShowFeatures, i: int) -> dict:
    tax = taxonomy()
    vibe = sf.val("vibe") or {}
    kws = [t.get("name") for t in sf.val("topics") or [] if isinstance(t, dict) and t.get("name")]
    kws += [tax.get(t, {}).get("label", t) for t in sf.val("declared_topics") or []]
    return {"id": i, "name": sf.title, "categories": list(sf.val("categories") or []),
            "vibe_tags": [k for k, _ in sorted(vibe.items(), key=lambda kv: (-kv[1], kv[0]))[:3]], "tone_tags": list(sf.val("tone") or []),
            "keywords": kws, "last_episode_at": sf.val("last_published"), "episode_count": sf.val("episode_count")}


def rank(corpus: Corpus, member_id: str, k: int = 5) -> list[dict]:
    cfg = load_config()
    now = corpus.as_of.replace(tzinfo=timezone.utc)
    idx = {sid: i for i, sid in enumerate(corpus.ids)}
    subj = Subject(**_subject(corpus.shows[member_id], idx[member_id]))
    out = []
    for sid in corpus.ids:
        if sid == member_id:
            continue
        c = Candidate(type="podcast", **_subject(corpus.shows[sid], idx[sid]))
        out.append({"target_show_id": sid, "score": score_one(subj, c, now, cfg).total_score})
    out.sort(key=lambda r: (-r["score"], r["target_show_id"]))
    return out[:k]
