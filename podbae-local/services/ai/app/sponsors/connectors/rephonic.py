"""Rephonic connector SEAM (podcast audience / sponsor data). DISABLED: not tested, no API key. Never returns fake data.
To enable later: set REPHONIC_API_KEY and INTEL_REPHONIC_ENABLED=true, implement fetch_sponsors() / fetch_audience(),
store results with source 'rephonic', tier 'estimated', and run them through the same brand resolution."""
from __future__ import annotations

import os


class NotConfigured(RuntimeError):
    pass


def status() -> dict:
    has_key = bool(os.environ.get("REPHONIC_API_KEY"))
    enabled = has_key and os.environ.get("INTEL_REPHONIC_ENABLED", "false").lower() == "true"
    return {"enabled": False, "has_key": has_key, "requested": enabled,
            "note": "Not tested, no key: the connector is a seam only. No Rephonic data is used or simulated."}


def fetch_sponsors(show_id: str) -> list[dict]:
    raise NotConfigured("Rephonic connector is not implemented / not configured (no key, not tested).")


def fetch_audience(show_id: str) -> dict:
    raise NotConfigured("Rephonic connector is not implemented / not configured (no key, not tested).")
