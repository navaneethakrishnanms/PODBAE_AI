"""G. Ranking. Rank by Fit, tie-break by confidence, then prefer opportunities the member has not seen, then show id.
MMR on content vectors re-orders the head so the top results are not near-clones of each other.

NO PADDING: only opportunities with Fit >= min_fit AND confidence >= min_confidence are shown. Fewer than 3 -> only those,
with an explanation; none -> a 'no good match yet' state that says what would help."""
from __future__ import annotations

from .factors import clip01
from .features import Corpus, ShowFeatures


def qualifies(rec: dict, cfg: dict) -> bool:
    r = cfg["ranking"]
    return rec["fit"] >= float(r["min_fit"]) and rec["confidence"]["value"] >= float(r["min_confidence"])


def base_key(rec: dict, seen_days: dict[str, int]) -> tuple:
    return (-rec["fit"], -rec["confidence"]["value"], seen_days.get(rec["target_show_id"], 0), rec["target_show_id"])


def mmr(recs: list[dict], corpus: Corpus, cfg: dict, seen_days: dict[str, int] | None = None) -> list[dict]:
    r = cfg["ranking"]
    lam, k = float(r["mmr_lambda"]), int(r["mmr_top_k"])
    clone_z = float(cfg["factors"]["content_similarity"]["clone_z"])
    pool = sorted(recs, key=lambda x: base_key(x, seen_days or {}))
    head, tail = pool[:k], pool[k:]

    def sim(a: str, b: str) -> float:
        c = corpus.cos(a, b)
        z = corpus.z(c) if c is not None else None
        return 0.0 if z is None else clip01(z / clone_z)

    out: list[dict] = []
    while head:
        best, best_score = None, None
        for x in head:
            div = max((sim(x["target_show_id"], y["target_show_id"]) for y in out), default=0.0)
            sc = round(lam * x["fit"] / 100.0 - (1 - lam) * div, 9)
            if best_score is None or sc > best_score:
                best, best_score = x, sc
            if out:
                x.setdefault("mmr", {})["max_similarity_to_higher_ranked"] = round(div, 4)
        out.append(best)
        head.remove(best)
    return out + tail


def suggestions(m: ShowFeatures) -> list[dict]:
    """What would help, derived only from what is missing on the member's own profile."""
    out = []
    if not m.val("creator.goals"):
        out.append({"code": "add_goals", "action": "Add your goals", "detail": "Tell us whether you want cross-promos, guest swaps or feed swaps."})
    if m.val("creator.collaboration_openness") not in ("open", "selective"):
        out.append({"code": "set_openness", "action": "Set your collaboration openness", "detail": "Open or selective creators are shown as Verified partners to other members."})
    if not any(m.get(f) for f in ("audience.totals", "audience.top_countries")):
        out.append({"code": "upload_audience", "action": "Upload audience analytics",
                    "detail": "Turns on audience-size and geography matching, which are disabled until both shows have this data."})
    if not (m.val("topics") or m.val("declared_topics")):
        out.append({"code": "clarify_topics", "action": "Make your topics clear", "detail": "Add categories and a show description that names your topics."})
    return out


def state(qualified: list[dict], m: ShowFeatures, gate_counts: dict[str, int], cfg: dict) -> dict:
    r = cfg["ranking"]
    if len(qualified) >= 3:
        return {"state": "ok", "message": None, "suggestions": []}
    blocked = {k: v for k, v in gate_counts.items() if k in ("blocked_category", "blocked_brand_safety", "language_incompatible")}
    why = (f"Only partners with Fit of at least {r['min_fit']} and evidence confidence of at least {r['min_confidence']} are shown; "
           "we never pad the list with weaker matches.")
    if blocked:
        why += " Your settings also excluded: " + ", ".join(f"{v} ({k.replace('_', ' ')})" for k, v in sorted(blocked.items())) + "."
    if not qualified:
        return {"state": "no_match", "message": "No good match yet. " + why, "suggestions": suggestions(m)}
    return {"state": "few", "message": f"Only {len(qualified)} strong match{'es' if len(qualified) > 1 else ''} right now. " + why,
            "suggestions": suggestions(m)}
