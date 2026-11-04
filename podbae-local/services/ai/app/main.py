from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI


def _load_env() -> None:
    """Tiny .env loader (repo root) so optional keys apply without extra deps."""
    env = Path(__file__).resolve().parents[3] / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


_load_env()

from . import scoring  # noqa: E402
from .llm import get_llm  # noqa: E402
from .schemas import ChatRequest, ChatResponse, MatchRequest, MatchResponse  # noqa: E402

app = FastAPI(title="PodBae AI Service (placeholder)", version="0.2.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "llm": get_llm().name}


@app.post("/match", response_model=MatchResponse, response_model_by_alias=True)
def match(req: MatchRequest) -> MatchResponse:
    return scoring.match(req)


@app.post("/heybae/chat", response_model=ChatResponse, response_model_by_alias=True)
def heybae_chat(req: ChatRequest) -> ChatResponse:
    llm = get_llm()
    try:
        reply = llm.chat(req.message, req.context, req.history)
        provider = llm.name
    except Exception as exc:  # provider failure -> deterministic mock, never a 500
        from .llm import MockLLM

        reply = MockLLM().chat(req.message, req.context, req.history) + f"\n(LLM error: {type(exc).__name__})"
        provider = "mock"
    return ChatResponse(reply=reply, provider=provider)
