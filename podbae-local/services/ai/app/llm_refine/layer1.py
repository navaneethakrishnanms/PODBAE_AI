"""Phase 4 Layer 1 refiners, registered on the Phase 1 seam (understanding/refine.py). They run ONLY where rules are weak:

  conversational_style  rule value 'unknown' or confidence < 0.5. Needs >= 1 verbatim quote from an episode title /
                        description / the show description; otherwise the value stays 'unknown'.
  guests_present        rule guest share between 0.1 and 0.5, or a rule-detected guest name whose first name is not in
                        first_names.txt. Per-episode guest verdicts must quote the episode text; guest NAMES exist only
                        inside those quotes (evidence), never as people profiles or fields.
  topics                extra topics from the FIXED taxonomy only, each with >= 2 verbatim quotes from 2 different texts
                        (the Phase 1 evidence rule). Rule topics are kept; additions are marked basis 'llm'.

Every value: method='llm', tier='inferred', confidence <= LLM_CONFIDENCE_CAP, the rule value kept alongside (it is a
separate provenance row from a separate source), never written where a verified / creator-provided value exists."""
from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..intel.config import get_settings
from ..intel.models import Episode, Provenance, Show
from ..intel.trust.audit import audit
from ..intel.trust.provenance import add_evidence, get_source, live_rows, record
from ..intel.understanding import signals as sg
from ..intel.understanding.refine import RefineContext, RefineResult, register_refiner
from . import client

PV = {"conversational_style": "style-v1", "guests_present": "guests-v2", "topics": "topics-v1"}
PROTECTED_TIERS = ("verified", "creator_provided")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Quote(_Strict):
    source: str = Field(max_length=60)
    quote: str = Field(max_length=300)


class StyleOut(_Strict):
    style: Literal["solo_monologue", "co_hosted_banter", "interview", "panel", "narrative_storytelling", "unknown"]
    evidence: list[Quote] = Field(default_factory=list, max_length=3)


class GuestVerdict(_Strict):
    source: str = Field(max_length=60)
    guest: bool
    quote: str = Field(default="", max_length=300)


class GuestOut(_Strict):
    episodes: list[GuestVerdict] = Field(default_factory=list, max_length=12)


class TopicProposal(_Strict):
    id: str = Field(max_length=60)
    evidence: list[Quote] = Field(default_factory=list, max_length=4)


class TopicsOut(_Strict):
    topics: list[TopicProposal] = Field(default_factory=list, max_length=3)


# ───────────────────────── shared helpers ─────────────────────────
def _src(s: Session):
    model = client.get_llm_provider().model_version if client.get_llm_provider() else "none"
    return get_source(s, f"llm:{model}", "llm", f"LLM refinement ({model}); inferred, evidence-checked, never used for audience facts")


def _rule_row(s: Session, sid: str, field: str) -> Provenance | None:
    rows = [r for r in live_rows(s, "show", sid, field, include_llm=False)]
    rows.sort(key=lambda r: -r.fetched_at.timestamp())
    return rows[0] if rows else None


def protected(s: Session, sid: str, field: str) -> bool:
    """A verified / creator-provided value exists: the LLM never writes next to it (it could not win anyway)."""
    return any(r.data_tier in PROTECTED_TIERS for r in live_rows(s, "show", sid, field, include_llm=False))


def _llm_rows(s: Session, sid: str, field: str) -> list[Provenance]:
    return [r for r in live_rows(s, "show", sid, field, include_llm=True) if r.method == "llm"]


def retire(s: Session, sid: str, field: str, why: str) -> int:
    """The LLM no longer supports a value (e.g. no verifiable quote this time): its old row stops being live."""
    n = 0
    for r in _llm_rows(s, sid, field):
        r.superseded_by = r.id
        n += 1
    if n:
        audit(s, "llm", "retired", "show", sid, {"field": field, "why": why})
    return n


def sources(s: Session, show: Show, n_eps: int = 8, chars: int = 350) -> dict[str, str]:
    from ..intel.understanding.pipeline import _fact
    desc = _fact(s, show.id, "description") or ""
    eps = list(s.scalars(select(Episode).where(Episode.show_id == show.id, Episode.removed.is_(False))
                         .order_by(Episode.published_at.desc()).limit(n_eps)))
    out = {"show_title": show.title or "", "show_description": desc[:1200]}
    for e in eps:
        out[e.id] = f"{e.title or ''}\n{(e.description or '')[:chars]}"
    return out


def _conf(base: float) -> float:
    return round(min(get_settings().llm_conf_cap, base), 2)


def _write(s: Session, sid: str, field: str, value, conf: float, rule: Provenance | None, pv: str, quotes: list[tuple[str, str]],
           show: Show) -> None:
    src = _src(s)
    model = client.get_llm_provider().model_version
    rule_txt = f"rule value kept alongside: {rule.value_json!r} (conf {rule.confidence})" if rule else "no rule value"
    record(s, "show", sid, field, value, source=src, tier="inferred", method="llm", confidence=_conf(conf),
           model_version=f"{model}/{pv}", source_ref=rule_txt[:500])
    for lab, q in quotes[:4]:
        loc = {"episode_id": lab} if lab.startswith("ep_") else {"part": lab, "url": show.canonical_feed_url}
        add_evidence(s, "show", sid, field if field != "guests_present" else "guest_friendliness", q, {**loc, "method": "llm"}, src)


# ───────────────────────── conversational style ─────────────────────────
STYLE_TASK = ("Classify the podcast's conversational style as ONE of: solo_monologue (one host talking), co_hosted_banter "
              "(two or more regular hosts chatting), interview (a host talks with a different guest most episodes), panel (three or "
              "more voices discussing), narrative_storytelling (produced, scripted story / documentary). Use ONLY the data blocks. "
              "Give 1-3 quotes copied exactly from the blocks that show the style (e.g. 'my guest today', 'join my co-host'). "
              "If the blocks do not show the style clearly, answer 'unknown' with no evidence.")


# A quote only counts as style evidence if it contains a FORMAT cue for the style claimed (the model must point at
# something that is actually about the format, not any sentence from the show).
STYLE_CUES = {
    "solo_monologue": re.compile(r"\b(I|I'm|I’m|I've|I’ll|I'll|me|my|myself|join me|solo|just me|on my own)\b"),
    "co_hosted_banter": re.compile(r"\b(co-?hosts?|cohosts?|hosts|we|we're|we’re|us|our|together|both of us|friends|duo|"
                                   r"(?:and|&) (?:his|her|my) (?:wife|husband|brother|sister|friend|partner))\b", re.I),
    "interview": re.compile(r"\b(guests?|interview\w*|joined by|joins (?:me|us)|sit(?:s)? down with|talk(?:s|ed)? (?:to|with)|"
                            r"conversation with|speak(?:s)? with|chat(?:s|ted)? with|welcome[sd]?|feat\.?|ft\.?|author|founder|expert|dr\.?)\b", re.I),
    "panel": re.compile(r"\b(panel\w*|roundtable|round table|guests|crew|team|hosts|everyone|all of us)\b", re.I),
    "narrative_storytelling": re.compile(r"\b(story|stories|storytelling|series|chapter|part \d+|documentary|investigat\w*|"
                                         r"narrat\w*|true crime|unfolds|the tale|episode \d+)\b", re.I),
}


def style_eligible(s: Session, sid: str) -> bool:
    r = _rule_row(s, sid, "conversational_style")
    return r is not None and not protected(s, sid, "conversational_style") and (r.value_json == "unknown" or r.confidence < 0.5)


def refine_style(s: Session, show: Show) -> dict:
    rule = _rule_row(s, show.id, "conversational_style")
    src = sources(s, show)
    out = client.run(s, "style", PV["conversational_style"], STYLE_TASK, src, StyleOut,
                     meta={"rule_value": rule.value_json if rule else None, "rule_confidence": rule.confidence if rule else None,
                           "categories": []}, entity=("show", show.id))
    if not out.ok:
        return {"status": out.status}
    v: StyleOut = out.value
    cue = STYLE_CUES.get(v.style)
    quotes = [(lab, q.quote) for q in v.evidence if (lab := client.find_source(q.quote, out.sent, q.source))
              and len(client.norm(q.quote)) >= 12 and cue is not None and cue.search(q.quote)]
    if v.style == "unknown" or not quotes:
        retire(s, show.id, "conversational_style", "no verifiable evidence")
        return {"status": out.status, "value": "unknown", "applied": False, "model_said": v.style, "verified_quotes": len(quotes)}
    _write(s, show.id, "conversational_style", v.style, 0.4 + 0.07 * len(quotes), rule, PV["conversational_style"], quotes, show)
    return {"status": out.status, "value": v.style, "applied": True, "rule": rule.value_json if rule else None, "verified_quotes": len(quotes)}


# ───────────────────────── guests ─────────────────────────
GUEST_TASK = ("List ONLY the episode blocks (labels starting with 'ep_') that feature an outside GUEST (someone who is not a "
              "regular host or co-host). For each, set guest=true and copy the exact few words from that block that show it (e.g. "
              "'my guest Dr. Lee', 'interview with ...', at most 15 words). A recurring co-host is not a guest. Episodes you do not "
              "list count as having no guest. If unsure about an episode, leave it out.")


def guest_eligible(s: Session, sid: str) -> bool:
    if protected(s, sid, "guests_present"):
        return False
    r = _rule_row(s, sid, "guests_present")
    if r is None or r.method == "parsed" or not isinstance(r.value_json, dict):
        return False
    share = float(r.value_json.get("share") or 0)
    if 0.1 <= share <= 0.5:
        return True
    return share > 0 and _unknown_first_name(s, sid)


def _unknown_first_name(s: Session, sid: str) -> bool:
    """Re-run the (deterministic, cheap) guest rules: a detected guest name whose first name is not in first_names.txt
    (only the loose 'feat./ft.' rule accepts those) makes the show ambiguous."""
    from ..intel.understanding.pipeline import _fact
    cfg = get_settings()
    eps = list(s.scalars(select(Episode).where(Episode.show_id == sid, Episode.removed.is_(False))
                         .order_by(Episode.published_at.desc()).limit(cfg.deep_episodes)))
    persons = [{"name": h, "role": "host"} for h in (_fact(s, sid, "hosts") or [])]
    g = sg.detect_guests([(e.id, e.title, e.description, e.persons or []) for e in eps], persons, _fact(s, sid, "author"))
    names = sg.first_names()
    for ex in g["examples"]:
        first = (ex.get("name") or "").replace("Dr. ", "").replace("Prof. ", "").split(" ")[0].strip(".'’").lower()
        if first and first not in names:
            return True
    return False


def refine_guests(s: Session, show: Show) -> dict:
    rule = _rule_row(s, show.id, "guests_present")
    src = sources(s, show)
    eps = [k for k in src if k.startswith("ep_")]
    if len(eps) < 3:
        return {"status": "skipped", "reason": "fewer than 3 episodes"}
    out = client.run(s, "guests", PV["guests_present"], GUEST_TASK, src, GuestOut,
                     meta={"rule_value": (rule.value_json or {}).get("share") if rule else None}, entity=("show", show.id))
    if not out.ok:
        return {"status": out.status}
    # The model lists ONLY guest episodes (fewer output tokens); every episode not listed with a verifiable quote = no guest.
    verdict: dict[str, bool] = {k: False for k in eps}
    quotes: list[tuple[str, str]] = []
    unverified = 0
    for g in out.value.episodes:
        if g.source not in eps or not g.guest or verdict[g.source]:
            continue
        if client.verbatim(g.quote, out.sent.get(g.source, ""), min_len=6):
            verdict[g.source] = True
            quotes.append((g.source, g.quote))
        else:
            unverified += 1
    if unverified and not quotes:                     # it claimed guests but could not quote any: not a usable answer
        return {"status": out.status, "applied": False, "reason": f"{unverified} guest claim(s) without a verbatim quote"}
    n_guest = sum(verdict.values())
    share = round(n_guest / len(verdict), 2)
    rv = rule.value_json if rule else {}
    value = {"value": share >= sg.GUEST_FRIENDLY_SHARE, "basis": "llm: per-episode verdicts with verbatim quotes", "share": share,
             "guest_episodes": n_guest, "episodes_checked": len(verdict), "threshold": sg.GUEST_FRIENDLY_SHARE,
             "rule_share": rv.get("share") if isinstance(rv, dict) else None}
    _write(s, show.id, "guests_present", value, 0.5, rule, PV["guests_present"], quotes, show)
    record(s, "show", show.id, "guest_friendliness", share, source=_src(s), tier="inferred", method="llm", confidence=_conf(0.5),
           model_version=f"{client.get_llm_provider().model_version}/{PV['guests_present']}",
           source_ref=f"LLM guest-episode share {n_guest}/{len(verdict)}; rule share {value['rule_share']}")
    return {"status": out.status, "applied": True, "share": share, "rule_share": value["rule_share"], "quotes": len(quotes)}


# ───────────────────────── topics ─────────────────────────
TOPIC_TASK = ("Which topics from the candidate list does this podcast clearly cover that are NOT already known? Propose at most "
              "3, using ONLY ids from 'candidate_topics'. For each, give at least 2 quotes copied exactly from 2 DIFFERENT data "
              "blocks (an episode or the show description) that show the topic. If none qualify, return an empty list.")


def topics_eligible(s: Session, sid: str) -> bool:
    """Only where the rules are weak: fewer than 3 topics met the evidence rule, or low topic confidence."""
    r = _rule_row(s, sid, "topics")
    if r is None or protected(s, sid, "topics"):
        return False
    return len(r.value_json or []) < 3 or r.confidence < 0.5


def refine_topics(s: Session, show: Show) -> dict:
    rule = _rule_row(s, show.id, "topics")
    kept = list(rule.value_json or []) if rule else []
    kept_ids = {t["id"] for t in kept}
    tax = sg.taxonomy()
    cands = {tid: t["label"] for tid, t in tax.items() if tid not in kept_ids}
    src = sources(s, show)
    out = client.run(s, "topics", PV["topics"], TOPIC_TASK, src, TopicsOut,
                     meta={"topics_known": sorted(kept_ids), "candidate_topics": cands}, entity=("show", show.id))
    if not out.ok:
        return {"status": out.status}
    added, quotes, rejected = [], [], []
    for p in out.value.topics:
        if p.id not in cands:
            rejected.append({"id": p.id, "why": "not a candidate taxonomy id"})
            continue
        good = {}
        for q in p.evidence:
            lab = client.find_source(q.quote, out.sent, q.source)
            if lab and len(client.norm(q.quote)) >= 12 and lab not in good:
                good[lab] = q.quote
        if len(good) < 2:
            rejected.append({"id": p.id, "why": f"{len(good)} verifiable quote source(s); 2 required"})
            continue
        t = tax[p.id]
        added.append({"id": p.id, "name": t["label"], "group": t.get("group"), "episodes": sum(1 for k in good if k.startswith("ep_")),
                      "in_description": "show_description" in good, "basis": ["llm"], "weight": 0.3})
        quotes += [(lab, f"[{t['label']}] {q}"[:300]) for lab, q in good.items()]
    if not added:
        retire(s, show.id, "topics", "no topic met the 2-quote rule")
        return {"status": out.status, "applied": False, "rejected": rejected}
    _write(s, show.id, "topics", kept + added, 0.45, rule, PV["topics"], quotes, show)
    return {"status": out.status, "applied": True, "added": [a["id"] for a in added], "rejected": rejected}


# ───────────────────────── seam registration + runner ─────────────────────────
TASKS = {"style": ("conversational_style", style_eligible, refine_style),
         "guests": ("guests_present", guest_eligible, refine_guests),
         "topics": ("topics", topics_eligible, refine_topics)}


def _seam(field: str):
    def fn(ctx: RefineContext) -> RefineResult | None:     # the Phase 1 seam signature; the runner below is the real entry
        return None
    fn.__name__ = f"refine_{field}"
    return fn


for _name, (_field, _elig, _fn) in TASKS.items():
    register_refiner(_field)(_seam(_field))


def refine_show(s: Session, show_id: str, tasks: list[str] | None = None) -> dict:
    """Run the eligible refiners for one show. Raises client.Paused on rate limiting (the caller pauses / resumes)."""
    show = s.get(Show, show_id)
    res: dict = {}
    if show is None:
        return res
    for name in tasks or list(TASKS):
        field, elig, fn = TASKS[name]
        if not elig(s, show_id):
            res[name] = {"status": "not_eligible"}
            continue
        res[name] = fn(s, show)
    return res
