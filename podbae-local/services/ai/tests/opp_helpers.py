"""Synthetic intelligence-store builder for Layer 4 tests: exact control over vectors, fields, tiers and timestamps."""
from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np

from app.intel.models import Embedding, Episode, Evidence, Show, ShowClaim
from app.intel.trust.provenance import add_evidence, get_source, record
from app.intel.understanding.model_signals import STYLE_VERSION
from app.intel.understanding.schemas import VIBE_TERMS
from app.intel.understanding.signals import STYLES, TONES
from app.intel.vectors import to_blob

AS_OF = datetime(2026, 11, 12, 12, 0, 0)
DIM = 16


def vec(seed: int | None = None, base: np.ndarray | None = None, noise: float = 0.0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    v = rng.normal(size=DIM) if base is None else base + noise * rng.normal(size=DIM)
    return (v / np.linalg.norm(v)).astype(np.float32)


def style_feat(vibe_hot: list[str], style: str | None, tones: list[str]) -> dict:
    return {"vibe": [0.9 if t in vibe_hot else 0.2 for t in VIBE_TERMS], "style": [1.0 if style == s else 0.0 for s in STYLES],
            "tone": [1.0 if t in tones else 0.0 for t in TONES], "version": STYLE_VERSION}


def mk_show(s, sid: str, title: str, *, v: np.ndarray, lang: str | None = "en", detected: tuple[str, float] | None = None,
            topics: list[tuple[str, float]] = (("comedy", 1.0),), declared: list[str] = ("comedy",), groups: list[str] = ("Comedy",),
            activity: str = "active", cadence: float | None = 7.0, minutes: float | None = 40.0, last_days: float = 3.0,
            guest: float | None = 0.4, style: str | None = "interview", vibe_hot: list[str] = ("Humorous", "Casual", "Energetic"),
            tones: list[str] = ("conversational",), flags: list[str] = (), owner: str | None = None, website: str | None = None, contact_url: str | None = None,
            description: str = "A show.", creator: dict | None = None, member_user: str | None = None, joined_days: float = 200,
            demo: bool = False, style_features: bool = True, at: datetime = AS_OF) -> str:
    rss = get_source(s, "rss", "rss")
    rules = get_source(s, "podbae-rules", "rule")
    model = get_source(s, "local-model:e5", "local_model")
    langsrc = get_source(s, "langdetect", "local_model")
    creator_src = get_source(s, "creator_declared", "creator")
    s.add(Show(id=sid, canonical_feed_url=f"https://feeds.test/{sid}.xml", title=title, language=lang, activity=activity))
    s.flush()
    r = lambda f, val, tier="verified", method="parsed", src=rss, conf=1.0: record(s, "show", sid, f, val, source=src, tier=tier,  # noqa: E731
                                                                                  method=method, confidence=conf, at=at - timedelta(hours=1))
    r("title", title)
    r("description", description)
    if lang:
        r("language", lang)
    if detected:
        r("language", detected[0], tier="estimated", method="model", src=langsrc, conf=detected[1])
    r("categories", list(groups))
    r("declared_topics", list(declared), method="rule", conf=0.9)
    r("category_group", list(groups), method="rule", conf=0.9)
    r("topics", [{"id": t, "name": t.replace("_", " ").title(), "group": groups[0] if groups else "?", "weight": w, "episodes": 3,
                  "basis": ["lexicon"]} for t, w in topics], tier="inferred", method="rule", src=rules, conf=0.55)
    r("activity_status", activity, tier="estimated", method="rule", conf=0.8)
    if cadence is not None:
        r("cadence_days", cadence, method="rule")
    if minutes is not None:
        r("avg_episode_minutes", minutes, method="rule")
    r("last_published", (at - timedelta(days=last_days)).isoformat() + "Z", method="rule")
    if guest is not None:
        r("guest_friendliness", guest, tier="inferred", method="rule", src=rules, conf=0.5)
    r("conversational_style", style or "unknown", tier="inferred", method="rule", src=rules, conf=0.55 if style else 0.15)
    r("tone", list(tones), tier="inferred", method="rule", src=rules, conf=0.35)
    r("brand_safety_flags", list(flags), tier="inferred", method="rule", src=rules, conf=0.4)
    r("vibe", {t: (0.9 if t in vibe_hot else 0.2) for t in VIBE_TERMS}, tier="inferred", method="model", src=model, conf=0.35)
    if style_features:
        r("style_features", style_feat(list(vibe_hot), style, list(tones)), tier="inferred", method="rule+model", src=model, conf=0.3)
    if owner:
        r("owner_email_hash", owner)
    if website:
        r("website", website)
    if contact_url:
        r("contact_routes", [{"kind": "contact_page", "url": contact_url, "found_in": "episode_notes"}], method="rule", conf=0.9)
    for k, val in (creator or {}).items():
        record(s, "show", sid, f"creator.{k}", val, source=creator_src, tier="creator_provided", method="manual", confidence=1.0,
               at=at - timedelta(hours=1))
    s.add(Embedding(entity_type="show", entity_id=sid, space="content", model="test", model_version="1", dim=DIM, content_hash=sid,
                    vector=to_blob(v)))
    if member_user:
        s.add(ShowClaim(show_id=sid, user_id=member_user, demo=demo, created_at=at - timedelta(days=joined_days)))
    s.flush()
    return sid


def add_episode(s, sid: str, title: str, days_ago: float, *, topic: str | None = None, guest: bool = False, at: datetime = AS_OF) -> str:
    e = Episode(show_id=sid, guid=f"{sid}-{title}", title=title, published_at=at - timedelta(days=days_ago))
    s.add(e)
    s.flush()
    rules = get_source(s, "podbae-rules", "rule")
    if topic:
        add_evidence(s, "show", sid, "topics", f"[{topic}] {title}", {"episode_id": e.id, "topic": topic}, rules)
    if guest:
        add_evidence(s, "show", sid, "guest_friendliness", f"{title} — rule: test", {"episode_id": e.id}, rules)
    return e.id


def filler(s, n: int = 24, seed: int = 100) -> list[str]:
    """Unrelated shows (random vectors, other topics) so corpus statistics are meaningful."""
    out = []
    for i in range(n):
        out.append(mk_show(s, f"shw_fill{i:02d}", f"Filler {i}", v=vec(seed + i), topics=[("history", 1.0)], declared=["history"],
                           groups=["History"], vibe_hot=["Reflective", "Educational", "Professional"], tones=["calm"], style="solo_monologue",
                           minutes=90, cadence=30, guest=0.0))
    return out


def peak_vec(base: np.ndarray, seed: int, noise: float = 0.18) -> np.ndarray:
    return vec(seed, base=base, noise=noise)
