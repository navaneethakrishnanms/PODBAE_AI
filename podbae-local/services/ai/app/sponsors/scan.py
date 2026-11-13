"""Corpus scan: ALL stored episode show notes (not only the latest 20) + every stored transcript -> sponsorship_events,
then brand resolution, status and categories. Idempotent: an episode's auto events are replaced on re-scan; reviewed
events keep their human verdict. Runs as job 'sponsors_scan' (admin) or scripts/sponsors_scan.py."""
from __future__ import annotations

import hashlib
import time
from collections import Counter

from sqlalchemy import select

from ..intel.db import session_scope
from ..intel.models import Episode, Show, Transcript
from ..intel.trust import jobs
from ..intel.trust.audit import audit
from ..intel.trust.provenance import live_rows
from . import ner
from .detect import DETECTOR_VERSION, Detection, ShowContext, compact, detect
from .domains import registrable
from .models import SponsorScanRun, SponsorshipEvent


def show_context(s, show: Show) -> ShowContext:
    ctx = ShowContext()
    for f in ("website", "link"):
        r = live_rows(s, "show", show.id, f)
        if r and isinstance(r[0].value_json, str) and registrable(r[0].value_json):
            ctx.own_domains.add(registrable(r[0].value_json))
    feed_dom = registrable(show.canonical_feed_url or "")
    from .domains import denylist
    if feed_dom and feed_dom not in denylist():
        ctx.own_domains.add(feed_dom)
    ctx.own_names.add(compact(show.title))
    for f in ("author", "hosts"):
        r = live_rows(s, "show", show.id, f)
        v = r[0].value_json if r else None
        for x in (v if isinstance(v, list) else [v] if v else []):
            if isinstance(x, str) and len(compact(x)) >= 4:
                ctx.own_names.add(compact(x))
    return ctx


def _key(episode_id: str, source: str, d: Detection) -> str:
    return hashlib.sha256(f"{episode_id}|{source}|{d.cls}|{d.identity()}|{d.rule}".encode()).hexdigest()


def scan_show(s, show: Show, method: str) -> Counter:
    ctx = show_context(s, show)
    eps = list(s.scalars(select(Episode).where(Episode.show_id == show.id, Episode.removed.is_(False))))
    trs = {t.episode_id: t for t in s.scalars(select(Transcript).where(Transcript.episode_id.in_([e.id for e in eps])))} if eps else {}
    counts = Counter()
    existing = {ev.key: ev for ev in s.scalars(select(SponsorshipEvent).where(SponsorshipEvent.show_id == show.id))}
    keep: set[str] = set()
    for e in eps:
        for source, text in (("show_notes", e.description or ""), ("transcript", (trs.get(e.id).text if trs.get(e.id) else ""))):
            if not text.strip():
                continue
            for d in detect(f"{e.title}\n{text}" if source == "show_notes" else text, ctx):
                k = _key(e.id, source, d)
                keep.add(k)
                counts[d.cls] += 1
                if k in existing:
                    continue
                s.add(SponsorshipEvent(key=k, show_id=show.id, episode_id=e.id, episode_date=e.published_at, source=source, cls=d.cls,
                                       rule=d.rule[:60], snippet=d.snippet[:300], url=d.url, domain=d.domain,
                                       brand_name=(d.brand_name or (d.aliases[0] if d.aliases else None)),
                                       promo_code=d.promo_code, method=method if d.brand_name and not d.domain else "rules",
                                       model_version=method if d.brand_name and not d.domain else None,
                                       detector_version=DETECTOR_VERSION, sample_bucket=int(k[:4], 16) % 100))
    for k, ev in existing.items():          # stale auto detections (text changed / rules changed) go; reviewed ones stay
        if k not in keep and ev.verification_status == "auto":
            s.delete(ev)
    return counts


def scan_all(show_ids: list[str] | None = None) -> dict:
    t0 = time.perf_counter()
    method = ner.method()                    # loads GLiNER once (or falls back to rules)
    with session_scope() as s:
        ids = show_ids or [sh.id for sh in s.scalars(select(Show).where(Show.merged_into.is_(None)).order_by(Show.id))]
        n_tr = s.query(Transcript).count()
    total, eps = Counter(), 0
    for sid in ids:
        with session_scope() as s:
            sh = s.get(Show, sid)
            if sh is None:
                continue
            total += scan_show(s, sh, method)
            eps += s.query(Episode).filter(Episode.show_id == sid, Episode.removed.is_(False)).count()
    from .resolve import categorize, resolve
    with session_scope() as s:
        res = resolve(s)
    with session_scope() as s:
        cats = categorize(s)
    with session_scope() as s:
        run = SponsorScanRun(detector_version=DETECTOR_VERSION, method=method, shows=len(ids), episodes=eps, transcripts=n_tr,
                             events=sum(total.values()), by_class=dict(total), seconds=round(time.perf_counter() - t0, 1))
        s.add(run)
        audit(s, "sponsors", "scan", None, None, {"by_class": dict(total), "method": method, "brands": res})
    return {"shows": len(ids), "episodes": eps, "transcripts": n_tr, "events": sum(total.values()), "by_class": dict(total),
            "method": method, "ner": ner.status(), "brands": res, "categories": cats, "seconds": round(time.perf_counter() - t0, 1)}


@jobs.register("sponsors_scan")
def _scan_job(ctx: jobs.JobContext) -> dict:
    return scan_all(ctx.payload.get("show_ids"))
