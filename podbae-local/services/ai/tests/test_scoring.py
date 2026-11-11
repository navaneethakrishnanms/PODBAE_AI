from fastapi.testclient import TestClient

from app.main import app
from app.schemas import MatchRequest
from app.scoring import match

REQ = {
    "podcast": {"id": 1, "name": "A", "categories": ["Comedy"], "location": "New York, NY",
                "vibeTags": ["Casual"], "toneTags": ["Playful"], "keywords": ["humor"],
                "lastEpisodeAt": "2025-12-25T00:00:00Z"},
    "candidates": [
        {"id": 2, "type": "sponsor", "name": "B", "categories": ["Comedy"], "location": "New York, NY",
         "vibeTags": ["Casual"], "toneTags": ["Playful"], "keywords": ["humor"]},
        {"id": 3, "type": "guest", "name": "C", "categories": ["Sports"]},
    ],
    "asOf": "2026-01-01T00:00:00Z",
}


def test_deterministic() -> None:
    a = match(MatchRequest.model_validate(REQ)).model_dump(by_alias=True)
    b = match(MatchRequest.model_validate(REQ)).model_dump(by_alias=True)
    assert a == b
    assert a["matches"][0]["targetId"] == 2


def test_breakdown_and_explanation() -> None:
    m = match(MatchRequest.model_validate(REQ)).matches[0]
    assert m.score_breakdown.genre_score == 1.0
    assert len(m.explanation.reasons) == 2
    assert "7 day" in (m.explanation.why_now or "")
    assert m.explanation.evidence


def test_http_endpoints() -> None:
    c = TestClient(app, headers={"X-Service-Token": "test-service-token"})
    assert c.get("/health").json()["status"] == "ok"
    r = c.post("/match", json=REQ).json()
    assert r["matches"][0]["scoreBreakdown"]["genreScore"] == 1.0
    chat = c.post("/heybae/chat", json={"message": "hi", "context": {}}).json()
    assert "reply" in chat
