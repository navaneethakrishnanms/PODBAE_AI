"""Layer 2: scan every stored episode (show notes + transcripts) for sponsorship evidence, resolve brands, infer categories.
Rules + local models only (GLiNER for brand names near ad cues, e5 for brand categories); no LLM; no fetching.
    python scripts/sponsors_scan.py            (npm run sponsors:scan)"""
from __future__ import annotations

try:  # native load order: torch, then sentence_transformers, before anything imports lxml (see app/main.py)
    import torch  # noqa: F401
    import sentence_transformers  # noqa: F401
except Exception:  # noqa: BLE001
    pass
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.envfile import load_env  # noqa: E402

load_env()


def main() -> int:
    from app.intel.db import init_engine
    from app.sponsors.scan import scan_all
    init_engine()
    res = scan_all()
    print(json.dumps(res, indent=1, default=str))
    (Path(__file__).resolve().parents[1] / "eval" / "sponsor_scan.json").write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
