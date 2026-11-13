"""A. Candidate generation: union of
   - content-space nearest neighbours (e5, exact cosine over the stored vectors)
   - style-space nearest neighbours (numeric style vector, conversational-style dims excluded so 'unknown' is not a category)
   - shows sharing a declared topic or category group
capped (~200). Candidates are ALL shows in the intelligence store, members and non-members alike. Ordering is
deterministic: by best rank in any source, then show id. (At much larger scale the exact scans become an ANN query
through intel.vectors.VectorIndex; exact is used here because it is deterministic and the corpus is small.)"""
from __future__ import annotations

from ..intel.linalg import dot
from .features import Corpus


def generate(corpus: Corpus, member_id: str, cfg: dict) -> list[dict]:
    cc = cfg["candidates"]
    m = corpus.shows[member_id]
    best: dict[str, dict] = {}

    def add(sid: str, source: str, rank: int) -> None:
        if sid == member_id:
            return
        d = best.setdefault(sid, {"show_id": sid, "sources": [], "best_rank": rank})
        d["sources"].append(source)
        d["best_rank"] = min(d["best_rank"], rank)

    sims = corpus.content_sims(member_id)
    for r, (sid, _) in enumerate(sorted(((k, v) for k, v in sims.items() if k != member_id), key=lambda kv: (-round(kv[1], 9), kv[0]))
                                 [: int(cc["content_neighbours"])]):
        add(sid, "content", r)

    mv = corpus.style_vec(member_id, False)
    if mv is not None:
        ss = []
        for sid in corpus.ids:
            if sid == member_id:
                continue
            v = corpus.style_vec(sid, False)
            if v is not None:
                ss.append((sid, dot(mv, v)))
        for r, (sid, _) in enumerate(sorted(ss, key=lambda kv: (-round(kv[1], 9), kv[0]))[: int(cc["style_neighbours"])]):
            add(sid, "style", r)

    dm, gm = set(m.val("declared_topics") or []), set(m.val("category_group") or [])
    if dm or gm:
        meta = []
        for sid in corpus.ids:
            if sid == member_id:
                continue
            o = corpus.shows[sid]
            score = 2 * len(dm & set(o.val("declared_topics") or [])) + len(gm & set(o.val("category_group") or []))
            if score:
                meta.append((sid, score))
        for r, (sid, _) in enumerate(sorted(meta, key=lambda kv: (-kv[1], kv[0]))[: int(cc["shared_metadata_max"])]):
            add(sid, "shared_metadata", r)

    out = sorted(best.values(), key=lambda d: (d["best_rank"], d["show_id"]))[: int(cc["cap"])]
    for d in out:
        d["sources"] = sorted(set(d["sources"]))
    return out
