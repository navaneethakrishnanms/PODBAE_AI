"""Environment self-check (Phase 2 close-out). Run with:  npm run doctor   (= conda run -n torch_gpu python scripts/doctor.py)

Every check prints PASS / WARN / FAIL with the fix. Risky native-library checks run in a SUBPROCESS so a crash (the
Phase 1-2 segfaults / OpenMP aborts) is reported as a FAIL instead of killing the doctor. Exit code 1 if any FAIL."""
from __future__ import annotations

import importlib
import json
import os
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AI = ROOT / "services" / "ai"
results: list[tuple[str, str, str, str]] = []


def rec(status: str, name: str, detail: str = "", fix: str = "") -> None:
    results.append((status, name, detail, fix))
    line = f"[{status}] {name}" + (f": {detail}" if detail else "")
    print(line + (f"\n        fix: {fix}" if fix and status != "PASS" else ""), flush=True)


def sub(code: str, timeout: int = 300) -> tuple[int, str]:
    p = subprocess.run([sys.executable, "-c", code], cwd=str(AI), capture_output=True, text=True, timeout=timeout,
                       encoding="utf-8", errors="replace")
    return p.returncode, (p.stdout + p.stderr).strip()


# ───────────── versions ─────────────
def versions() -> None:
    v = sys.version_info
    in_env = "torch_gpu" in sys.executable
    rec("PASS" if (v.major, v.minor) >= (3, 10) and in_env else "FAIL", "python", f"{sys.version.split()[0]} at {sys.executable}",
        "run through `npm run doctor` (conda env torch_gpu, Python >= 3.10)")
    node = shutil.which("node")
    if not node:
        rec("FAIL", "node", "not on PATH", "install Node 20+ (tested with 24.12)")
        return
    nv = subprocess.run([node, "-v"], capture_output=True, text=True).stdout.strip()
    npm = shutil.which("npm") or shutil.which("npm.cmd")
    npv = subprocess.run([npm, "-v"], capture_output=True, text=True, shell=os.name == "nt").stdout.strip() if npm else "?"
    major = int(re.sub(r"\D", "", nv.split(".")[0]) or 0)
    rec("PASS" if major >= 20 else "FAIL", "node / npm", f"node {nv}, npm {npv}", "install Node 20+ (tested with node 24.12.0 / npm 11.6.2)")


# ───────────── python packages ─────────────
IMPORT_NAME = {"pyyaml": "yaml", "uvicorn[standard]": "uvicorn", "python-multipart": "multipart", "sqlite-vec": "sqlite_vec",
               "sentence-transformers": "sentence_transformers", "pytest": "pytest"}


def packages() -> None:
    missing = []
    for line in (AI / "requirements.txt").read_text(encoding="utf-8").splitlines():
        line = line.split("#")[0].strip()
        if not line:
            continue
        name = re.split(r"[<>=!~ ]", line)[0].strip().lower()
        mod = IMPORT_NAME.get(name, name.replace("-", "_"))
        code, out = sub(f"import {mod}")
        if code != 0:
            missing.append(f"{name} ({out.splitlines()[-1][:80] if out else 'exit ' + str(code)})")
    rec("PASS" if not missing else "FAIL", "requirements.txt importable", "all importable" if not missing else "; ".join(missing),
        "conda run -n torch_gpu pip install -r services/ai/requirements.txt  (exact versions: services/ai/requirements.lock.txt)")


# ───────────── native import order (crash-prone) ─────────────
def import_order() -> None:
    code, out = sub("import torch, sentence_transformers, lxml.etree, numpy as np\n"
                    "a = np.random.rand(300, 300); b = a @ a\nprint('ok', b.shape)")
    rec("PASS" if code == 0 and "ok" in out else "FAIL", "native import order torch -> sentence_transformers -> lxml -> numpy BLAS",
        "loads without crash" if code == 0 else f"exit code {code}: {out[-200:]}",
        "keep the preload order in services/ai/app/main.py (torch, then sentence_transformers, before anything imports lxml)")
    code, out = sub("import lxml.etree, sentence_transformers; print('ok')")
    rec("PASS" if code == 0 else "WARN", "reverse order lxml -> sentence_transformers (known hazard)",
        "also loads" if code == 0 else f"crashes (exit {code}); the service avoids it by preloading sentence_transformers first",
        "never import lxml before sentence_transformers in a process that embeds")


def sqlite_vec() -> None:
    code, out = sub("import sqlite3, sqlite_vec\nc = sqlite3.connect(':memory:'); c.enable_load_extension(True); sqlite_vec.load(c)\n"
                    "print(c.execute('select vec_version()').fetchone()[0])")
    rec("PASS" if code == 0 else "FAIL", "sqlite-vec loads", out.splitlines()[-1] if out else "", "pip install sqlite-vec>=0.1.6")


def e5_gpu() -> None:
    code, out = sub("import torch, sentence_transformers, sys\nsys.path.insert(0, '.')\n"
                    "from app.envfile import load_env; load_env()\nfrom app.intel.vectors import get_embedder\n"
                    "e = get_embedder(); v = e.embed(['hello podcast'])\n"
                    "print('model', e.name, 'device', getattr(e, 'device', '?'), 'dim', v.shape[1])", timeout=600)
    last = out.splitlines()[-1] if out else ""
    ok = code == 0 and "model" in last
    gpu = "device cuda" in last
    rec("PASS" if ok and gpu else ("WARN" if ok else "FAIL"), "e5 embedding model loads on the GPU", last if ok else f"exit {code}: {out[-200:]}",
        "check CUDA / torch in torch_gpu; first run downloads intfloat/multilingual-e5-small (needs internet once)")


# ───────────── data stores ─────────────
def stores() -> None:
    db = ROOT / "data" / "intel.db"
    try:
        c = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=5)
        n = c.execute("select count(*) from shows where merged_into is null").fetchone()[0]
        ver = c.execute("select version_num from alembic_version").fetchone()[0]
        rec("PASS" if ver >= "0003" else "FAIL", "data/intel.db opens", f"{n} shows, migration {ver}", "npm run intel:migrate")
    except Exception as exc:  # noqa: BLE001
        rec("FAIL", "data/intel.db opens", str(exc)[:150], "npm run intel:migrate (or restore data/ from a backup)")
    pg = ROOT / "data" / "pglite"
    need = ["base", "global", "pg_wal", "pg_xact", "pg_tblspc", "pg_notify", "pg_stat", "pg_stat_tmp", "pg_snapshots", "pg_twophase",
            "pg_commit_ts", "pg_dynshmem", "pg_replslot", "pg_serial", "pg_logical/mappings", "pg_logical/snapshots"]
    if not pg.exists():
        rec("WARN", "data/pglite", "missing (created by npm run db:migrate + npm run seed)", "npm run db:migrate && npm run seed")
    else:
        miss = [d for d in need if not (pg / d).is_dir()]
        rec("PASS" if not miss else "FAIL", "data/pglite directory structure", "complete" if not miss else f"missing {miss}",
            "create the missing EMPTY folders (copies/zips drop empty dirs); Postgres will not open without them")
        if (pg / "postmaster.pid").exists() and not _port_open(5000):
            rec("WARN", "data/pglite stale lock", "postmaster.pid present while the API is not running", "delete data/pglite/postmaster.pid")


# ───────────── node workspace links ─────────────
def workspaces() -> None:
    nm = ROOT / "node_modules" / "@podbae"
    miss = [w for w in ("api", "web", "contracts") if not (nm / w).exists()]
    rec("PASS" if not miss else "FAIL", "npm workspace links", "node_modules/@podbae/{api,web,contracts}" if not miss else f"missing {miss}", "npm install")


# ───────────── ports ─────────────
def _port_open(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


def _owners() -> dict[int, str]:
    if os.name != "nt":
        return {}
    ps = ("Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Where-Object { $_.LocalPort -in 5173,5000,8000 } | "
          "ForEach-Object { $c = (Get-CimInstance Win32_Process -Filter \"ProcessId=$($_.OwningProcess)\").CommandLine; "
          "[pscustomobject]@{port=$_.LocalPort; cmd=$c} } | ConvertTo-Json -Compress")
    out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True).stdout.strip()
    if not out:
        return {}
    data = json.loads(out)
    data = data if isinstance(data, list) else [data]
    return {int(d["port"]): d.get("cmd") or "" for d in data}


def ports() -> None:
    own = _owners()
    for port, what in ((5173, "web"), (5000, "api"), (8000, "ai")):
        cmd = own.get(port)
        if cmd is None and not _port_open(port):
            rec("PASS", f"port {port} ({what})", "free")
        elif cmd is not None and re.search(r"vite|tsx|uvicorn|podbae|dev-ai", cmd, re.I):
            rec("PASS", f"port {port} ({what})", "in use by our dev process")
        else:
            rec("FAIL", f"port {port} ({what})", f"in use by another process: {(cmd or '?')[:100]}", "npm run stop, or close the other program")


# ───────────── .env ─────────────
REQUIRED_ENV = ["PORT", "SESSION_SECRET", "WEB_ORIGIN", "AI_SERVICE_URL", "INTEL_SERVICE_TOKEN", "LLM_PROVIDER", "INTEL_EMBED_MODEL"]


def env() -> None:
    p = ROOT / ".env"
    if not p.exists():
        rec("FAIL", ".env", "missing", "copy .env.example to .env")
        return
    keys = {}
    for line in p.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            keys[k.strip()] = v.strip()
    miss = [k for k in REQUIRED_ENV if not keys.get(k)]
    rec("PASS" if not miss else "FAIL", ".env required keys", "all present" if not miss else f"missing/empty: {miss}",
        "see .env.example (INTEL_SERVICE_TOKEN: any long random string, shared by api and ai)")
    if keys.get("LLM_PROVIDER", "mock") != "mock" or keys.get("INTEL_LLM_REFINE", "false").lower() == "true":
        rec("WARN", "LLM settings", "LLM_PROVIDER is not mock or INTEL_LLM_REFINE is on", "Phase 1-2 run with no LLM: LLM_PROVIDER=mock")


def main() -> int:
    print(f"PodBae doctor ({ROOT})\n", flush=True)
    for fn in (versions, packages, import_order, sqlite_vec, e5_gpu, stores, workspaces, ports, env):
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            rec("FAIL", fn.__name__, f"check crashed: {type(exc).__name__}: {exc}"[:200])
    fails = sum(1 for r in results if r[0] == "FAIL")
    warns = sum(1 for r in results if r[0] == "WARN")
    print(f"\n{len(results)} checks: {len(results) - fails - warns} PASS, {warns} WARN, {fails} FAIL", flush=True)
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
