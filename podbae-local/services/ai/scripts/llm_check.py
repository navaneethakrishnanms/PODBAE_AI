"""Phase 4: is the LLM usable? Checks the Ollama daemon, the model and one real structured answer. Exit 0 = ready.
If not ready, prints the exact commands to fix it. Usage: npm run llm:check"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.envfile import load_env  # noqa: E402

load_env()
from app.intel.config import get_settings  # noqa: E402
from app.llm_refine import llm_active  # noqa: E402
from app.llm_refine.ollama import OllamaProvider  # noqa: E402


def main() -> int:
    cfg = get_settings()
    p = OllamaProvider()
    st = p.check()
    st.update(provider=cfg.llm_provider, refine_enabled=cfg.llm_refine_enabled, llm_active=llm_active(),
              capabilities=p.capabilities(), ledger_provider=p.ledger_name)
    print(json.dumps(st, indent=1))
    if st["daemon"] and st["model_present"] and st["answers"]:
        if not llm_active():
            print("\nModel answers, but the LLM is OFF (kill switch). To turn it on, in .env set:\n"
                  f"  LLM_PROVIDER=ollama\n  OLLAMA_MODEL={p.model_version}\n  INTEL_LLM_REFINE=true")
        return 0
    print("\nNOT READY. Fix with (PowerShell):")
    if not st["daemon"]:
        print("  ollama serve            # or start the Ollama app; it listens on", cfg.ollama_base_url)
    if p.model_version.endswith("-cloud"):
        print("  ollama signin           # cloud models need a signed-in ollama.com account (with credits / a plan)")
    if not st["model_present"]:
        print(f"  ollama pull {p.model_version}")
    print(f'  ollama run {p.model_version} "reply with OK"   # must print an answer, not an error')
    if st.get("error"):
        print("  last error:", st["error"])
    print("  or use a local model:  set OLLAMA_MODEL=llama3.1:8b in .env")
    return 1


if __name__ == "__main__":
    sys.exit(main())
