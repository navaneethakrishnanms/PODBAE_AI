"""UI smoke check (Phase 1, Step 8). Needs `npm run dev` running.

    conda run -n torch_gpu python scripts/ui_smoke.py [--base http://localhost:5173]

Logs in as each demo role (Chromium via Playwright), visits the main pages from TESTING_CHECKLIST.md, saves full-page
screenshots to screenshots/, and records console errors, page errors and failed requests per page into
screenshots/report.json (+ a printed summary). It does not click destructive actions."""
from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "screenshots"

ROLES = {
    "public": (None, None, ["/", "/get-started", "/login", "/discover", "/submit", "/advertiser-submit", "/enterprise"]),
    "podcaster": ("podcaster@podbae.local", "demo123", ["/dashboard", "/intelligence", "/swipe", "/messages", "/discover", "/profile", "/schedule",
                                                         "/analytics", "/partners", "/listen"]),
    "advertiser": ("brand@podbae.local", "demo123", ["/dashboard/campaign-builder", "/discover"]),
    "admin": ("admin@podbae.local", "admin123", ["/admin", "tab:Ingestion jobs", "tab:Coverage", "tab:Costs", "tab:Labels", "/admin/labels",
                                                  "tab:Engine", "/admin/labels/pairs"]),
    # Phase 2 (Layer 4 opportunity engine) demo accounts, created by Admin -> Engine -> "Set up demo members"
    "commit_showcase": ("mindful@demo.podbae.local", "demo123", ["/dashboard", "/intelligence"]),
    "no_match": ("nomatch@demo.podbae.local", "demo123", ["/dashboard"]),
}
OPP_PAGES = {("podcaster", "/dashboard"), ("commit_showcase", "/dashboard"), ("no_match", "/dashboard")}
IGNORE = re.compile(r"favicon|hot-update|__vite|sockjs|/@vite/|\.map$", re.I)


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_") or "home"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:5173")
    a = ap.parse_args()
    OUT.mkdir(exist_ok=True)
    report: list[dict] = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for role, (email, pw_, pages) in ROLES.items():
            ctx = browser.new_context(viewport={"width": 1366, "height": 900})
            page = ctx.new_page()
            current: dict = {}

            def on_console(msg, cur=current, role=role):
                if role == "public" and "status of 401" in msg.text:      # the browser's log line for the expected 401 above
                    return
                if msg.type == "error" and not IGNORE.search(msg.text):
                    cur.setdefault("console_errors", []).append(msg.text[:300])

            def on_pageerror(err, cur=current):
                cur.setdefault("page_errors", []).append(str(err)[:300])

            def on_response(resp, cur=current, role=role):
                # anonymous visitors: the app probes the session with /api/auth/me, and 401 is the expected answer
                if role == "public" and resp.status == 401 and resp.url.endswith("/api/auth/me"):
                    cur.setdefault("expected_401", 0)
                    cur["expected_401"] += 1
                    return
                if resp.status >= 400 and not IGNORE.search(resp.url):
                    cur.setdefault("failed_requests", []).append(f"{resp.status} {resp.request.method} {resp.url.replace(a.base, '')}")

            def on_failed(req, cur=current):
                if not IGNORE.search(req.url):
                    cur.setdefault("failed_requests", []).append(f"FAILED {req.method} {req.url.replace(a.base, '')}: {req.failure}")

            page.on("console", on_console)
            page.on("pageerror", on_pageerror)
            page.on("response", on_response)
            page.on("requestfailed", on_failed)
            if email:
                r = page.request.post(f"{a.base}/api/auth/login", data={"email": email, "password": pw_})
                if r.status != 200:
                    report.append({"role": role, "page": "login", "error": f"login failed: HTTP {r.status}"})
                    ctx.close()
                    continue
            for p in pages:
                current.clear()
                t0 = time.perf_counter()
                try:
                    if p.startswith("tab:"):
                        label = p[4:]
                        if "/admin" not in page.url or "/admin/labels" in page.url:
                            page.goto(f"{a.base}/admin", wait_until="networkidle")
                        page.get_by_role("tab", name=label, exact=True).first.click()     # Radix Tabs render role="tab"
                        page.wait_for_load_state("networkidle")
                        page.wait_for_timeout(800)
                        name = f"{role}_admin_tab_{slug(label)}"
                    else:
                        page.goto(f"{a.base}{p}", wait_until="networkidle")
                        page.wait_for_timeout(1000)
                        name = f"{role}_{slug(p)}"
                    extra: dict = {}
                    if (role, p) in OPP_PAGES:      # Layer 4 cards: count them, read the four measures, open breakdown + dismiss dialog
                        page.wait_for_timeout(1500)
                        cards = page.locator("[data-testid=opportunity-card]")
                        extra["opportunity_cards"] = cards.count()
                        body = page.inner_text("body")
                        extra["readiness_seen"] = [x for x in ("Verified", "Potential lead", "Discovery lead") if x in body]
                        extra["four_measures"] = all(x.lower() in body.lower() for x in ("Fit", "Evidence confidence", "Commercial status", "Not enough data yet")) if cards.count() else None
                        extra["no_match_state"] = "No good match yet" in body
                        if cards.count():
                            page.get_by_role("button", name="Show breakdown").first.click()
                            page.wait_for_timeout(300)
                            extra["breakdown_open"] = page.get_by_text("disabled").count() > 0
                            page.get_by_role("button", name="Dismiss").first.click()
                            page.get_by_text("Tell us why").wait_for(timeout=5000)
                            extra["dismiss_reason_dialog"] = page.get_by_text("Not my vibe").count() > 0
                            page.keyboard.press("Escape")      # close without dismissing (nothing is changed)
                            page.wait_for_timeout(300)
                    if p == "/admin/labels/pairs":   # render member show 1 with its blind candidate pairs (nothing is saved)
                        page.get_by_placeholder("e.g. Priya").fill("ui-smoke (not saved)")
                        page.get_by_role("button", name=re.compile("Start labelling|Switch labeler")).click()
                        page.get_by_text("Member show 1 of").wait_for(timeout=20000)
                        extra["pair_candidates"] = page.get_by_text(re.compile(r"^Candidate \d+$")).count()
                        page.wait_for_timeout(500)
                    if p == "/admin/labels":       # render the labelling form for show 1 (nothing is saved)
                        page.get_by_placeholder("e.g. Priya").fill("ui-smoke (not saved)")
                        page.get_by_role("button", name=re.compile("Start labelling|Switch labeler")).click()
                        page.get_by_text("Show 1 of").wait_for(timeout=15000)
                        page.wait_for_timeout(500)
                    shot = OUT / f"{name}.png"
                    page.screenshot(path=str(shot), full_page=True)
                    text = page.inner_text("body")[:20000]
                    entry = {"role": role, "page": p, "url": page.url.replace(a.base, ""), "screenshot": str(shot.relative_to(ROOT)),
                             "ms": int((time.perf_counter() - t0) * 1000), "not_found": "Page not found" in text,
                             "admins_only": "Admins only" in text, **extra,
                             **{k: (list(v) if isinstance(v, list) else v) for k, v in current.items()}}
                except Exception as exc:  # noqa: BLE001
                    entry = {"role": role, "page": p, "error": f"{type(exc).__name__}: {exc}"[:300],
                             **{k: (list(v) if isinstance(v, list) else v) for k, v in current.items()}}
                report.append(entry)
            ctx.close()
        browser.close()
    (OUT / "report.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    bad = [r for r in report if r.get("error") or r.get("console_errors") or r.get("page_errors") or r.get("failed_requests") or r.get("not_found")]
    print(f"{len(report)} pages visited, {len(report) - len(bad)} clean, {len(bad)} with problems; screenshots in {OUT}")
    for r in bad:
        print(f"- [{r['role']}] {r['page']}: " + "; ".join(
            f"{k}={v}" for k, v in r.items() if k in ("error", "console_errors", "page_errors", "failed_requests", "not_found") and v))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
