from __future__ import annotations

try:  # import torch BEFORE other native libraries: on Windows another DLL load order can make torch fail to load
    import torch  # noqa: F401  (WinError 127 on fbgemm.dll). The embedder refuses to fall back silently if it does.
    # Phase 2: sentence_transformers must ALSO load before lxml (RSS connector): lxml.etree first, then
    # sentence_transformers (-> sklearn/scipy) segfaults the process in the torch_gpu env (access violation on import).
    import sentence_transformers  # noqa: F401
except Exception:  # noqa: BLE001
    pass

import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI


from .envfile import load_env  # noqa: E402

load_env()

from . import scoring  # noqa: E402
from .auth import require_service_token  # noqa: E402
from .llm import get_llm  # noqa: E402
from .schemas import ChatRequest, ChatResponse, MatchRequest, MatchResponse  # noqa: E402

@asynccontextmanager
async def lifespan(_app: FastAPI):
    from . import intel
    if os.environ.get("INTEL_DISABLED") != "1":
        intel.startup()
    yield
    intel.shutdown()


app = FastAPI(title="PodBae AI Service", version="0.4.0", lifespan=lifespan)
from .intel.api import public_router as intel_public_router  # noqa: E402
from .intel.api import router as intel_router  # noqa: E402
from .opportunities.api import router as opportunities_router  # noqa: E402
from .sponsors.api import router as sponsors_router  # noqa: E402
from .llm_refine.api import router as llm_router  # noqa: E402

app.include_router(intel_public_router)   # /v1/health only
app.include_router(intel_router)          # every other /v1 route: X-Service-Token required
app.include_router(opportunities_router)  # Layer 4 opportunity engine (same token)
app.include_router(sponsors_router)       # Layer 2 sponsor intelligence + sponsor opportunities (same token)
app.include_router(llm_router)            # Phase 4 LLM admin: status / metrics / run / rule-vs-AI (same token)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "llm": get_llm().name}


@app.post("/match", response_model=MatchResponse, response_model_by_alias=True, dependencies=[Depends(require_service_token)])
def match(req: MatchRequest) -> MatchResponse:
    return scoring.match(req)


@app.post("/heybae/chat", response_model=ChatResponse, response_model_by_alias=True, dependencies=[Depends(require_service_token)])
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
