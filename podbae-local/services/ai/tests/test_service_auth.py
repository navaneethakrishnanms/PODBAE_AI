"""Service token: every route except health requires X-Service-Token == INTEL_SERVICE_TOKEN; unset token fails closed."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.intel.config import reset_settings
from app.main import app
from tests.conftest import TOKEN_HEADERS

PROTECTED = [("get", "/v1/shows"), ("get", "/v1/admin/coverage"), ("get", "/v1/admin/costs"), ("get", "/v1/jobs/job_x"),
             ("post", "/v1/ingest/rss"), ("get", "/v1/labels/queue"), ("post", "/match"), ("post", "/heybae/chat")]


@pytest.fixture()
def c(db):
    return TestClient(app)


@pytest.mark.parametrize("method,path", PROTECTED)
def test_missing_token_is_401(c, method, path):
    r = getattr(c, method)(path, **({"json": {}} if method == "post" else {}))
    assert r.status_code == 401, (path, r.text)


@pytest.mark.parametrize("method,path", PROTECTED)
def test_wrong_token_is_401(c, method, path):
    r = getattr(c, method)(path, headers={"X-Service-Token": "wrong"}, **({"json": {}} if method == "post" else {}))
    assert r.status_code == 401, (path, r.text)


def test_health_is_open_and_correct_token_works(c):
    assert c.get("/health").status_code == 200
    assert c.get("/v1/health").status_code == 200
    assert c.get("/v1/shows", headers=TOKEN_HEADERS).status_code == 200


def test_unset_token_fails_closed(c):
    reset_settings(database_url="sqlite://", allow_private_urls=True, embed_model="hash", service_token="")
    try:
        r = c.get("/v1/shows", headers={"X-Service-Token": ""})
        assert r.status_code == 401 and "not configured" in r.json()["detail"]
    finally:
        reset_settings(database_url="sqlite://", allow_private_urls=True, embed_model="hash", backoff_base_seconds=0.0)
