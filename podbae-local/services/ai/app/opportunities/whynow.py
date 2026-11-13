"""F. Why-now triggers. Built ONLY from real timestamps in the store; if there is no signal there is no trigger (we never
write a generic "now is a great time"). Every trigger carries its evidence: episode id, date, title.

  joined_podbae          candidate claimed their show on PodBae within joined_days
  shared_topic_recent    candidate published an episode supporting a topic you share within shared_topic_days
  recent_guest_episodes  candidate ran guest episodes (guest-rule evidence) within guest_episode_days
  reactivated            candidate's newest episode ended a gap of >= reactivated_gap_days, within reactivated_recent_days
  cadence_increased      median gap of the last n episodes < cadence_ratio x the median gap of the n before"""
from __future__ import annotations

from statistics import median

from sqlalchemy.orm import Session

from .features import Corpus, ShowFeatures, days_between, redact

LABELS = {"joined_podbae": "Recently joined PodBae", "shared_topic_recent": "New episode on a shared topic",
          "recent_guest_episodes": "Recently ran guest episodes", "reactivated": "Back after a break",
          "cadence_increased": "Publishing more often"}


def _ep(e) -> dict:
    return {"episode_id": e.id, "date": e.published_at.date().isoformat(), "title": redact(e.title)[:200]}


def triggers(s: Session, corpus: Corpus, m: ShowFeatures, c: ShowFeatures, shared_topics: list[dict], cfg: dict) -> list[dict]:
    w = cfg["why_now"]
    now = corpus.as_of
    out: list[dict] = []
    eps = corpus.episodes(s, c.show_id)
    by_id = {e.id: e for e in eps}

    if c.is_member and c.joined_at is not None and 0 <= days_between(now, c.joined_at) <= float(w["joined_days"]):
        out.append({"code": "joined_podbae", "label": LABELS["joined_podbae"], "evidence": [],
                    "detail": {"joined_on": c.joined_at.date().isoformat()}})

    shared_ids = {t["id"]: t["name"] for t in shared_topics}
    if shared_ids:
        hits: dict[str, tuple] = {}
        for ev in corpus.evidence(s, c.show_id, "topics"):
            loc = ev.locator or {}
            e = by_id.get(loc.get("episode_id"))
            tid = loc.get("topic")
            if e is None or tid not in shared_ids or days_between(now, e.published_at) > float(w["shared_topic_days"]):
                continue
            if days_between(now, e.published_at) < 0:
                continue
            if e.id not in hits:
                hits[e.id] = (e, tid)
        if hits:
            e, tid = sorted(hits.values(), key=lambda x: (x[0].published_at, x[0].id), reverse=True)[0]
            out.append({"code": "shared_topic_recent", "label": LABELS["shared_topic_recent"], "evidence": [_ep(e)],
                        "detail": {"topic_id": tid, "topic_name": shared_ids[tid], "episodes_in_window": len(hits),
                                   "window_days": int(w["shared_topic_days"])}})

    g_eps = {}
    for ev in corpus.evidence(s, c.show_id, "guest_friendliness"):
        e = by_id.get((ev.locator or {}).get("episode_id"))
        if e is not None and 0 <= days_between(now, e.published_at) <= float(w["guest_episode_days"]):
            g_eps[e.id] = e
    if g_eps:
        rec = sorted(g_eps.values(), key=lambda e: (e.published_at, e.id), reverse=True)
        out.append({"code": "recent_guest_episodes", "label": LABELS["recent_guest_episodes"], "evidence": [_ep(e) for e in rec[:3]],
                    "detail": {"guest_episodes": len(rec), "window_days": int(w["guest_episode_days"])}})

    dates = [e for e in eps if e.published_at is not None]
    if len(dates) >= 2:
        newest = dates[0]
        gap = days_between(newest.published_at, dates[1].published_at)
        if days_between(now, newest.published_at) <= float(w["reactivated_recent_days"]) and gap >= float(w["reactivated_gap_days"]):
            out.append({"code": "reactivated", "label": LABELS["reactivated"], "evidence": [_ep(newest)],
                        "detail": {"gap_days": int(gap)}})
    n, p = int(w["cadence_recent_n"]), int(w["cadence_prior_n"])
    if len(dates) >= n + p + 1 and days_between(now, dates[0].published_at) <= 30:
        gaps = [days_between(a.published_at, b.published_at) for a, b in zip(dates, dates[1:])]
        recent, prior = median(gaps[:n]), median(gaps[n:n + p])
        if prior > 0 and recent < float(w["cadence_ratio"]) * prior:
            out.append({"code": "cadence_increased", "label": LABELS["cadence_increased"], "evidence": [_ep(dates[0])],
                        "detail": {"recent_median_gap_days": round(recent, 1), "prior_median_gap_days": round(prior, 1)}})

    order = {k: i for i, k in enumerate(w["priority"])}
    return sorted(out, key=lambda t: order.get(t["code"], 99))
