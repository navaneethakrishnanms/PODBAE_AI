"""Sponsor-opportunity metrics: the shared engine metrics for kind='sponsor' + readiness / contact mix."""
from __future__ import annotations

from collections import Counter

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..opportunities.metrics import engine_metrics
from ..opportunities.models import Opportunity
from .opportunities import FACTORS, get_config


def sponsor_metrics(s: Session) -> dict:
    cfg = get_config()
    out = engine_metrics(s, kind="sponsor", cfg=cfg, factors=FACTORS)
    q = list(s.scalars(select(Opportunity).where(Opportunity.type == "sponsor", Opportunity.status == "active")))
    out["counts"]["by_contact_status"] = dict(Counter(((o.breakdown_json or {}).get("contact_status") or {}).get("status", "?") for o in q))
    return out
