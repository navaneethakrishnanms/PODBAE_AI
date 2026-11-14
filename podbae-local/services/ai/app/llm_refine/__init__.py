"""Phase 4: the LLM, used ONLY where Phase 1-3 rules were measured to be weak. Everything goes through one client
(app/llm/client.py): outbound privacy filter -> untrusted data blocks -> strict pydantic schema -> verbatim-evidence checks
-> content-hash cache -> bounded retries -> ledger. LLM values are stored next to the rule values (never instead of
them), as method='llm', tier='inferred', capped confidence.

Kill switches (either one restores exact Phase 3 behaviour):
  LLM_PROVIDER=mock        no real provider -> no calls, stored LLM values ignored by every reader
  INTEL_LLM_REFINE=false   same, regardless of provider
"""
from __future__ import annotations


def llm_active() -> bool:
    """True only when refinement is switched on AND a real provider is configured. Every reader of LLM-derived values
    (provenance resolution, engine features, sponsor classes, brand categories / names, card phrasing) checks this."""
    from ..intel.config import get_settings
    cfg = get_settings()
    return bool(cfg.llm_refine_enabled and cfg.llm_provider.lower() not in ("", "mock"))
