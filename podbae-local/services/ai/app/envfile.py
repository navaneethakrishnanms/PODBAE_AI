"""Tiny .env loader shared by the service and scripts (no extra dependency). Existing environment variables win.
Supports `KEY=value`, quoted values, and strips trailing ` # comments` on unquoted values."""
from __future__ import annotations

import os
import re
from pathlib import Path

ENV_PATH = Path(__file__).resolve().parents[3] / ".env"


def parse_line(line: str) -> tuple[str, str] | None:
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        return None
    k, v = line.split("=", 1)
    k, v = k.strip(), v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        v = v[1:-1]
    else:
        v = re.split(r"\s+#", v, maxsplit=1)[0].strip()
    return (k, v) if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", k) else None


def load_env(path: Path = ENV_PATH) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        kv = parse_line(line)
        if kv:
            os.environ.setdefault(*kv)
