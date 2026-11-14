"""Layer 2 corpus statistics (admin + EVAL_LAYER2)."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..intel.models import Show, now
from . import ner
from .models import Brand, SponsorScanRun, SponsorshipEvent
from .resolve import effective_class


def corpus_stats(s: Session, top: int = 25) -> dict:
    n_shows = s.scalar(select(func.count()).select_from(Show).where(Show.merged_into.is_(None))) or 0
    by_class = dict(s.execute(select(SponsorshipEvent.cls, func.count()).group_by(SponsorshipEvent.cls)).all())
    shows_by_class: dict[str, set] = defaultdict(set)
    months: Counter = Counter()
    hist_shows: set = set()
    for e in s.scalars(select(SponsorshipEvent)):
        ce = effective_class(e)
        shows_by_class[e.cls].add(e.show_id)
        if ce in ("declared_sponsorship", "likely_sponsorship"):
            hist_shows.add(e.show_id)
            if e.episode_date:
                months[e.episode_date.strftime("%Y-%m")] += 1
    net_only = shows_by_class["network_disclosure"] - hist_shows
    brands = list(s.scalars(select(Brand).where(Brand.merged_into.is_(None), Brand.n_events > 0)))
    st = Counter(b.status for b in brands)
    active_2plus = [b for b in brands if b.status == "active" and b.n_shows >= 2]
    last = s.scalar(select(SponsorScanRun).order_by(SponsorScanRun.created_at.desc()).limit(1))
    since = now() - timedelta(days=730)
    return {
        "shows": n_shows, "events_by_class": by_class, "shows_by_class": {k: len(v) for k, v in shows_by_class.items()},
        "coverage_sponsorship_history": {"shows": len(hist_shows), "share": round(len(hist_shows) / n_shows, 3) if n_shows else None},
        "network_disclosure_only": {"shows": len(net_only), "share": round(len(net_only) / n_shows, 3) if n_shows else None,
                                    "note": "ads exist (ad-choices / hosting boilerplate) but no brand is visible in the text"},
        "brands": {"total": len(brands), "by_status": dict(st), "active_on_2plus_shows": len(active_2plus),
                   "by_identity": dict(Counter(b.identity for b in brands)), "by_category_method": dict(Counter(b.category_method for b in brands))},
        "top_brands": [{"id": b.id, "name": b.name, "domain": b.primary_domain, "shows": b.n_shows, "events": b.n_events, "status": b.status,
                        "categories": [c.get("label") for c in b.categories or []]}
                       for b in sorted(brands, key=lambda b: (-b.n_shows, -b.n_events, b.name))[:top]],
        "events_per_month": dict(sorted((k, v) for k, v in months.items() if k >= since.strftime("%Y-%m"))),
        "last_scan": ({"at": last.created_at.isoformat() + "Z", "method": last.method, "episodes": last.episodes, "transcripts": last.transcripts,
                       "events": last.events, "seconds": last.seconds, "detector_version": last.detector_version} if last else None),
        "ner": ner.status(),
        "verification": dict(s.execute(select(SponsorshipEvent.verification_status, func.count()).group_by(SponsorshipEvent.verification_status)).all()),
    }
