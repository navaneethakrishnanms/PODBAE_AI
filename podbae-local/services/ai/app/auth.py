"""Service-to-service auth. The AI service binds to 127.0.0.1 and additionally requires a shared secret header on every
route except health checks, so another local process (or a mis-exposed port) cannot read or write intelligence data.

    X-Service-Token: <INTEL_SERVICE_TOKEN>

No token configured on the service = fail closed (every protected call is 401), never "open by default"."""
from __future__ import annotations

import hmac

from fastapi import Header, HTTPException

from .intel.config import get_settings

HEADER = "X-Service-Token"


def require_service_token(x_service_token: str | None = Header(default=None, alias=HEADER)) -> None:
    expected = get_settings().service_token
    if not expected:
        raise HTTPException(401, "service token not configured on the AI service (set INTEL_SERVICE_TOKEN)")
    if not x_service_token or not hmac.compare_digest(x_service_token.encode(), expected.encode()):
        raise HTTPException(401, f"missing or invalid {HEADER} header")
