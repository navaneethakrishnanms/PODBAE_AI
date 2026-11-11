from __future__ import annotations

import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# must be set before app modules read settings
os.environ.update({"INTEL_DATABASE_URL": "sqlite://", "INTEL_ALLOW_PRIVATE_URLS": "1", "INTEL_EMBED_MODEL": "hash",
                   "LLM_PROVIDER": "mock", "INTEL_WORKER": "0", "INTEL_BACKOFF_BASE": "0", "INTEL_DISABLED": "1",
                   "PODCASTINDEX_API_KEY": "", "PODCASTINDEX_API_SECRET": "", "INTEL_TADDY_ENABLED": "0",
                   "INTEL_SERVICE_TOKEN": "test-service-token"})
TOKEN_HEADERS = {"X-Service-Token": "test-service-token"}
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402


@pytest.fixture()
def db():
    from app.intel import ingest, vectors
    from app.intel.config import reset_settings
    from app.intel.db import create_all, init_engine, session_scope
    from app.intel.trust.budget import ensure_default_budgets

    reset_settings(database_url="sqlite://", allow_private_urls=True, embed_model="hash", backoff_base_seconds=0.0)
    vectors.reset_embedder()
    ingest.STAGE_HOOK = None
    ingest.set_client_factory(__import__("app.intel.connectors.base", fromlist=["make_client"]).make_client)
    init_engine("sqlite://")
    create_all()
    with session_scope() as s:
        ensure_default_budgets(s)
    yield
    ingest.STAGE_HOOK = None


class FeedServer:
    """Tiny HTTP server with mutable routes: path -> dict(status, body, headers, etag)."""

    def __init__(self) -> None:
        self.routes: dict[str, dict] = {}
        self.hits: dict[str, int] = {}
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):  # silence
                pass

            def do_GET(self):  # noqa: N802
                path = self.path
                outer.hits[path] = outer.hits.get(path, 0) + 1
                r = outer.routes.get(path)
                if r is None:
                    self.send_response(404); self.end_headers(); return
                if r.get("offline"):
                    self.connection.close(); return
                etag = r.get("etag")
                if etag and self.headers.get("If-None-Match") == etag:
                    self.send_response(304); self.end_headers(); return
                self.send_response(r.get("status", 200))
                for k, v in (r.get("headers") or {}).items():
                    self.send_header(k, v)
                if etag:
                    self.send_header("ETag", etag)
                body = r.get("body", b"")
                if isinstance(body, str):
                    body = body.encode()
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def set(self, path: str, body=b"", **kw) -> str:
        self.routes[path] = {"body": body, **kw}
        return self.base + path

    def close(self) -> None:
        self.httpd.shutdown()


@pytest.fixture()
def server():
    srv = FeedServer()
    yield srv
    srv.close()
