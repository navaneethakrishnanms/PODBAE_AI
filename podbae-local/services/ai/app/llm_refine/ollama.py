"""Ollama provider (local daemon; works for local models and for Ollama cloud models such as gpt-oss:120b-cloud).

- POST /api/chat with `format` = the pydantic JSON schema (structured output); the client falls back to format="json"
  + strict validation when structured output fails.
- `think` is sent ONLY to models whose capabilities include "thinking" (gpt-oss: "low"); thinking text is discarded here and
  never stored, logged or displayed.
- temperature 0 + fixed seed: same input -> same output (and the client caches by content hash anyway).
- Client-side rate limiter (LLM_RATE_PER_MIN, process-wide). 429 / 5xx / connection errors back off exponentially; after
  LLM_HTTP_RETRIES the provider raises RateLimited / ProviderUnavailable so a job can PAUSE (not fail) and resume later.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass

import httpx

from ..intel.config import get_settings
from .outbound import OutboundPayload


class ProviderError(RuntimeError):
    """Non-retryable (bad request, unknown model, no credits...)."""


class RateLimited(ProviderError):
    """429 after all retries: the caller should pause and resume later."""


class ProviderUnavailable(ProviderError):
    """Daemon down / 5xx / timeout after all retries."""


@dataclass
class ChatResult:
    text: str
    tokens_in: int
    tokens_out: int
    latency_ms: int
    retries: int = 0


class _Limiter:
    def __init__(self):
        self._lock = threading.Lock()
        self._next = 0.0

    def wait(self, per_min: float, sleep=time.sleep) -> float:
        if per_min <= 0:
            return 0.0
        with self._lock:
            t = time.monotonic()
            delay = max(0.0, self._next - t)
            self._next = max(t, self._next) + 60.0 / per_min
        if delay:
            sleep(delay)
        return delay


LIMITER = _Limiter()


class OllamaProvider:
    name = "ollama"
    price_in_per_1k = 0.0
    price_out_per_1k = 0.0

    def __init__(self, base_url: str | None = None, model: str | None = None, transport: httpx.BaseTransport | None = None,
                 sleep=time.sleep):
        cfg = get_settings()
        self.base_url = (base_url or cfg.ollama_base_url).rstrip("/")
        self.model_version = model or cfg.ollama_model
        self._client = httpx.Client(transport=transport, timeout=httpx.Timeout(cfg.llm_timeout, connect=10))
        self._sleep = sleep
        self._caps: list[str] | None = None
        self.rate_limit_pauses = 0

    @property
    def ledger_name(self) -> str:
        return "ollama-cloud" if self.model_version.endswith("-cloud") else "ollama-local"

    # ── status ──
    def capabilities(self) -> list[str]:
        if self._caps is None:
            try:
                r = self._client.post(f"{self.base_url}/api/show", json={"model": self.model_version}, timeout=15)
                self._caps = list(r.json().get("capabilities") or []) if r.status_code == 200 else []
            except httpx.HTTPError:
                self._caps = []
        return self._caps

    def check(self) -> dict:
        """Daemon up? model present? model answers? (one tiny real call). Never raises."""
        out = {"base_url": self.base_url, "model": self.model_version, "daemon": False, "model_present": False, "answers": False,
               "error": None}
        try:
            v = self._client.get(f"{self.base_url}/api/version", timeout=5)
            out["daemon"], out["version"] = v.status_code == 200, v.json().get("version")
            tags = self._client.get(f"{self.base_url}/api/tags", timeout=10).json().get("models") or []
            out["model_present"] = any(m.get("name") == self.model_version for m in tags)
            r = self._client.post(f"{self.base_url}/api/chat", json={
                "model": self.model_version, "stream": False, "messages": [{"role": "user", "content": 'Reply with {"ok": true}'}],
                "format": {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]},
                "options": {"temperature": 0, "num_predict": 20}, **self._think()}, timeout=get_settings().llm_timeout)
            body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
            out["answers"] = r.status_code == 200 and bool((body.get("message") or {}).get("content"))
            if not out["answers"]:
                out["error"] = (body.get("error") or f"HTTP {r.status_code}")[:300]
        except Exception as exc:  # noqa: BLE001 - a status check never raises
            out["error"] = f"{type(exc).__name__}: {exc}"[:300]
        return out

    def _think(self) -> dict:
        t = get_settings().llm_think
        return {"think": t} if t and "thinking" in self.capabilities() else {}

    # ── the one call ──
    def chat(self, system: str, payload_text: str, payload: OutboundPayload, schema: dict | str) -> ChatResult:
        """`payload` proves the text went through outbound.prepare(); `payload_text` is the prompt built from it."""
        if not isinstance(payload, OutboundPayload):
            raise ProviderError("refused: prompt material did not pass the outbound privacy filter")
        cfg = get_settings()
        body = {"model": self.model_version, "stream": False, "keep_alive": "10m", "format": schema,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": payload_text}],
                "options": {"temperature": 0, "seed": 7, "num_ctx": cfg.llm_num_ctx}, **self._think()}
        retries = 0
        while True:
            LIMITER.wait(cfg.llm_rate_per_min, self._sleep)
            t0 = time.perf_counter()
            try:
                r = self._client.post(f"{self.base_url}/api/chat", json=body)
                status = r.status_code
            except (httpx.ConnectError, httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout, httpx.RemoteProtocolError) as exc:
                status, r = -1, None
                err = f"{type(exc).__name__}"
            if status == 200:
                d = r.json()
                msg = d.get("message") or {}
                # msg.get("thinking") is deliberately dropped: never stored, logged or shown
                return ChatResult(text=msg.get("content") or "", tokens_in=int(d.get("prompt_eval_count") or 0),
                                  tokens_out=int(d.get("eval_count") or 0), latency_ms=int((time.perf_counter() - t0) * 1000),
                                  retries=retries)
            if status == 429 or status >= 500 or status == -1:
                if retries >= cfg.llm_http_retries:
                    if status == 429:
                        self.rate_limit_pauses += 1
                        raise RateLimited("rate limited (429) after retries")
                    raise ProviderUnavailable(f"provider unavailable ({err if status == -1 else f'HTTP {status}'}) after retries")
                retry_after = 0.0
                if r is not None and r.headers.get("retry-after", "").replace(".", "", 1).isdigit():
                    retry_after = float(r.headers["retry-after"])
                self._sleep(min(cfg.llm_backoff_max, max(retry_after, cfg.llm_backoff_base * (2 ** retries))))
                retries += 1
                continue
            try:
                msg = (r.json() or {}).get("error") or r.text
            except ValueError:
                msg = r.text
            raise ProviderError(f"HTTP {status}: {str(msg)[:200]}")

    # legacy Provider protocol (understanding/extract.py); not used by Phase 4 refiners
    def complete_json(self, system: str, user: str):
        from ..intel.understanding.providers import LLMResponse
        from .outbound import prepare
        p = prepare({"show_description": user})
        res = self.chat(system, p.blocks[0][1], p, "json")
        return LLMResponse(res.text, res.tokens_in, res.tokens_out)
