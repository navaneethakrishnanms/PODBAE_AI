"""Commercial readiness (separate from Fit and confidence): is there a REAL collaboration route?

  verified        PodBae member who opted into collaboration (open / selective)           -> message in-app
  potential_lead  PodBae member without stated openness                                    -> message in-app
                  or the show itself declares a contact / booking / guest / collab page   -> that page (evidence stored)
                  (from the feed: show description, episode notes, website-link path, podcast:person href)
  discovery_lead  everyone else. A plain homepage alone is NOT a route.

E-mails are never shown, stored or derived (contact routes drop anything with '@' / mailto; the owner e-mail hash stays
internal). Conversion probability is always "Not enough data yet" in this phase: there are no outcomes to learn from."""
from __future__ import annotations

from urllib.parse import urlparse

from .features import ShowFeatures

LABELS = {"verified": "Verified", "potential_lead": "Potential lead", "discovery_lead": "Discovery lead"}
CONVERSION = {"status": "not_enough_data", "label": "Not enough data yet",
              "note": "No partnership outcomes have been recorded yet, so no conversion probability is estimated."}
ROUTE_LABEL = {"guest_application": "guest application page", "booking": "booking page", "collaboration": "collaboration page",
               "contact_page": "contact page"}


def website_url(v: object) -> str | None:
    """Only a plain public http(s) URL; never mailto:, never something with credentials in it."""
    if not isinstance(v, str):
        return None
    u = v.strip()
    p = urlparse(u)
    if p.scheme not in ("http", "https") or not p.netloc or "@" in p.netloc or "@" in u:
        return None
    return u[:300]


def declared_route(c: ShowFeatures) -> dict | None:
    for r in c.val("contact_routes") or []:
        if isinstance(r, dict) and website_url(r.get("url")):
            return r
    return None


def readiness(c: ShowFeatures) -> dict:
    if c.is_member:
        op = c.val("creator.collaboration_openness")
        if op in ("open", "selective"):
            return {"level": "verified", "label": LABELS["verified"], "contact_route": "in_app",
                    "reason": f"On PodBae and has opted into collaboration ({op}). You can message them here."}
        return {"level": "potential_lead", "label": LABELS["potential_lead"], "contact_route": "in_app",
                "reason": "On PodBae, but has not said whether they are open to collaborations yet. You can message them here."}
    r = declared_route(c)
    if r:
        where = r["found_in"].replace("_", " ")
        return {"level": "potential_lead", "label": LABELS["potential_lead"], "contact_route": "contact_page",
                "contact_url": r["url"], "route_kind": r["kind"],
                "evidence": {"url": r["url"], "found_in": r["found_in"], **({"episode_id": r["episode_id"]} if r.get("episode_id") else {})},
                "reason": f"Not on PodBae yet; the show links a public {ROUTE_LABEL.get(r['kind'], 'contact page')} (found in {where})."}
    return {"level": "discovery_lead", "label": LABELS["discovery_lead"], "contact_route": "none",
            "reason": "Not on PodBae yet and the feed declares no contact or booking route (a homepage alone does not count). "
                      "You can invite them to PodBae."}
