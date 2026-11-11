"""Representative seed (Phase 1, Step 3): ~300 INDEPENDENT, ACTIVE shows, balanced across >= 8 category groups,
discovered with the Apple iTunes Search API (no key; rate-limited + cached).   `npm run intel:seed`

Pipeline per candidate (every rejection / failure is recorded with its reason):
  1. iTunes metadata pre-filter: primary genre must belong to the target group; independent rules on publisher name,
     feed host, latest release date and episode count (seed/independent.yaml).
  2. RSS check: fetch the feed (Phase 1 fetcher) and apply the same rules to the RSS author / owner / newest episode /
     episode count. Fetch failures get a reason code (dns, timeout, http_4xx, ...).
  3. Accepted feeds are ingested through the normal pipeline (rules + local models, no LLM), until the group quota is met.
Afterwards: corpus recalibration (vibe z-scores, style-vector centring) and the 30-show human label set.

Options: --fresh moves the current data/intel.db to data/archive/ first (the Layer 1 store is also in backups/).
Nothing here fabricates data: shows that cannot be fetched are reported as failures, never padded."""
from __future__ import annotations

try:  # import torch BEFORE other native libraries: on Windows a different DLL load order can make torch fail
    import torch  # noqa: F401  (WinError 127 on fbgemm.dll), and the embedding model then cannot load
except Exception:  # noqa: BLE001 - reported later by the embedder, which refuses to fall back silently
    pass

import argparse
import json
import random
import shutil
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.envfile import load_env  # noqa: E402

load_env()

# group -> iTunes search terms. Group membership is decided by the show's own iTunes genre, not by the search term.
GROUPS: dict[str, list[str]] = {
    "Comedy": ["comedy podcast", "comedians talk", "improv comedy", "funny friends podcast", "stand up comedy podcast", "comedy chat"],
    "True Crime": ["true crime", "unsolved mysteries", "cold case podcast", "true crime stories", "murder mystery podcast", "crime podcast"],
    "Technology": ["technology podcast", "software developers", "tech talk", "programming podcast", "indie hackers", "ai podcast"],
    "Business": ["small business podcast", "entrepreneur podcast", "marketing podcast", "personal finance podcast", "leadership podcast", "side hustle"],
    "Health & Fitness": ["fitness podcast", "mental health podcast", "nutrition podcast", "wellness podcast", "running podcast", "yoga podcast"],
    "Society & Culture": ["relationships podcast", "personal stories podcast", "culture podcast", "philosophy podcast", "travel stories podcast", "life advice"],
    "Education": ["learn english podcast", "education podcast", "self improvement podcast", "teaching podcast", "language learning", "how to podcast"],
    "Arts": ["book podcast", "writing podcast", "design podcast", "food podcast", "cooking podcast", "art podcast"],
    "Sports": ["sports podcast", "football podcast", "basketball podcast", "soccer podcast", "baseball podcast", "golf podcast"],
    "Leisure": ["gardening podcast", "board games podcast", "video games podcast", "crafts podcast", "cars podcast", "hobby podcast"],
    "Religion & Spirituality": ["christian podcast", "faith podcast", "spirituality podcast", "bible study podcast", "meditation podcast", "sermon podcast"],
    "Kids & Family": ["parenting podcast", "kids stories podcast", "mom podcast", "family podcast", "dad podcast", "bedtime stories"],
    "Science": ["science podcast", "space podcast", "nature podcast", "psychology podcast", "biology podcast", "physics podcast"],
    "TV & Film": ["movie podcast", "film review podcast", "tv show podcast", "star wars podcast", "horror movies podcast", "anime podcast"],
    "History": ["history podcast", "ancient history", "military history podcast", "local history podcast"],
    "Music": ["music podcast", "musicians podcast", "hip hop podcast", "songwriting podcast"],
}


def feeds_file() -> Path:
    return ROOT / "seed" / "feeds.txt"


def iso(d: str | None) -> datetime | None:
    if not d:
        return None
    try:
        return datetime.fromisoformat(d.replace("Z", "+00:00")).astimezone(timezone.utc).replace(tzinfo=None)
    except ValueError:
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", type=int, default=300)
    ap.add_argument("--groups", type=int, default=12, help="how many groups to fill (>= 8), taken in the order above")
    ap.add_argument("--concurrency", type=int, default=6)
    ap.add_argument("--per-query", type=int, default=200)
    ap.add_argument("--fresh", action="store_true", help="archive data/intel.db and start a new store")
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    from app.intel.config import REPO_ROOT
    if args.fresh:
        arch = REPO_ROOT / "data" / "archive" / time.strftime("intel_layer1_%Y%m%d_%H%M%S")
        arch.mkdir(parents=True, exist_ok=True)
        for suf in ("", "-wal", "-shm"):
            f = REPO_ROOT / "data" / f"intel.db{suf}"
            if f.exists():
                shutil.move(str(f), str(arch / f.name))
        print(f"archived the previous store to {arch}")

    from app import intel
    from app.intel import ingest
    from app.intel.calibration import recalibrate
    from app.intel.connectors.base import make_client
    from app.intel.connectors.directory import ITunesSearch
    from app.intel.connectors.rss import fetch_feed
    from app.intel.db import session_scope
    from app.intel.independent import check, load_rules, reason_code
    from app.intel.labels import pick_label_set
    from app.intel.models import Show
    from app.intel.normalize import url_key
    from app.intel.trust.provenance import live_rows
    from app.intel.understanding.signals import category_map, norm_category
    from sqlalchemy import func, select

    intel.startup(start_worker=False)
    rules = load_rules()
    groups = list(GROUPS)[: max(8, args.groups)]
    quota = {g: args.target // len(groups) + (1 if i < args.target % len(groups) else 0) for i, g in enumerate(groups)}
    cm = category_map()
    tax = __import__("app.intel.understanding.signals", fromlist=["taxonomy"]).taxonomy()

    def group_of(genres: list[str]) -> str | None:
        """iTunes primaryGenreName is usually a SUBcategory ('Home & Garden'); its genres list also carries the parent
        ('Leisure'). Prefer the primary genre's own group, via the top-level name or the subcategory's taxonomy topic."""
        for gname in genres:
            k = norm_category(gname)
            if k in cm["groups"]:
                return cm["groups"][k]
            if k in cm["map"] and cm["map"][k]:
                return tax[cm["map"][k][0]]["group"]
        return None

    t0 = time.perf_counter()

    # ── 1. discovery + metadata pre-filter ──
    rejections: dict[str, dict[str, int]] = {"directory": {}, "rss": {}}
    candidates: dict[str, list[dict]] = {g: [] for g in groups}
    seen: set[str] = set()
    with make_client() as client:
        it = ITunesSearch(client)
        for g in groups:
            for term in GROUPS[g]:
                try:
                    found = it.search(term, args.per_query)
                except Exception as exc:  # noqa: BLE001
                    print(f"  search {term!r} failed: {type(exc).__name__}: {exc}")
                    continue
                for f in found:
                    key = url_key(f["feed_url"])
                    if key in seen:
                        continue
                    seen.add(key)
                    fg = group_of([f.get("primary_genre") or ""] + list(f.get("categories") or []))
                    if fg not in groups:
                        rejections["directory"]["genre_outside_seed_groups"] = rejections["directory"].get("genre_outside_seed_groups", 0) + 1
                        continue
                    rs = check(rules, names=[f.get("author")], feed_url=f["feed_url"], last_published=iso(f.get("latest_release")),
                               episode_count=f.get("episode_count"))
                    if rs:
                        for r in rs:
                            rejections["directory"][reason_code(r)] = rejections["directory"].get(reason_code(r), 0) + 1
                        continue
                    candidates[fg].append(f)
            print(f"  {g}: {len(candidates[g])} candidates so far (iTunes calls {it.calls}, cache hits {it.cache_hits})")
    print(f"discovery done in {time.perf_counter() - t0:.0f}s; candidates per group: { {g: len(v) for g, v in candidates.items()} }")

    # ── 2 + 3. RSS check + ingest, filling each group's quota ──
    rng = random.Random(args.seed)
    for g in groups:
        rng.shuffle(candidates[g])
    accepted = {g: 0 for g in groups}
    lock = threading.Lock()
    results: list[dict] = []

    def one(g: str, f: dict) -> dict:
        with lock:
            if accepted[g] >= quota[g]:
                return {"group": g, "url": f["feed_url"], "status": "skipped_quota_full"}
        t = time.perf_counter()
        with make_client() as c:
            out = fetch_feed(c, f["feed_url"])
        if out.status != "ok":
            return {"group": g, "url": f["feed_url"], "status": "fetch_failed", "reason": out.result.error_kind, "error": out.result.error}
        pf = out.feed
        dates = [e.published_at for e in pf.episodes if e.published_at]
        rs = check(rules, names=[f.get("author"), pf.author, pf.owner_name], feed_url=out.final_url or f["feed_url"],
                   last_published=max(dates) if dates else None, episode_count=pf.total_items_in_feed)
        if rs:
            return {"group": g, "url": f["feed_url"], "status": "rejected", "reasons": rs}
        with lock:
            if accepted[g] >= quota[g]:
                return {"group": g, "url": f["feed_url"], "status": "skipped_quota_full"}
            accepted[g] += 1            # reserve the slot; released if ingestion fails
        try:
            r = ingest.run_pipeline(f["feed_url"], directory={"itunes_id": f.get("itunes_id"), "genres": f.get("categories"),
                                                               "artist": f.get("author")})
            return {"group": g, "url": f["feed_url"], "status": "ingested", "show_id": r["show_id"], "seconds": round(time.perf_counter() - t, 2),
                    "style": (r.get("enrich") or {}).get("style"), "topics": ((r.get("enrich") or {}).get("topics") or {}).get("kept")}
        except Exception as exc:  # noqa: BLE001
            with lock:
                accepted[g] -= 1
            return {"group": g, "url": f["feed_url"], "status": "ingest_failed", "error": f"{type(exc).__name__}: {exc}"[:300]}

    order = []                         # interleave groups so every group fills in parallel
    for i in range(max(len(v) for v in candidates.values())):
        for g in groups:
            if i < len(candidates[g]):
                order.append((g, candidates[g][i]))
    with ThreadPoolExecutor(args.concurrency) as ex:
        futs = []
        for g, f in order:
            futs.append(ex.submit(one, g, f))
        for i, fu in enumerate(as_completed(futs), 1):
            r = fu.result()
            if r["status"] != "skipped_quota_full":
                results.append(r)
            if r["status"] == "rejected":
                for x in r["reasons"]:
                    rejections["rss"][reason_code(x)] = rejections["rss"].get(reason_code(x), 0) + 1
            if i % 50 == 0:
                print(f"  {i}/{len(futs)} candidates processed; accepted {sum(accepted.values())}/{args.target}, {time.perf_counter() - t0:.0f}s")
            if all(accepted[g] >= quota[g] for g in groups):
                for fu2 in futs:
                    fu2.cancel()
                break

    # ── calibration + label set ──
    with session_scope() as s:
        cal = recalibrate(s)
    with session_scope() as s:
        label_ids = pick_label_set(s, 30, replace=True)
    print(f"recalibrated: {cal}; label set: {len(label_ids)} shows")

    # ── report ──
    with session_scope() as s:
        shows = list(s.scalars(select(Show).where(Show.merged_into.is_(None))))
        def v(sid, f):
            rows = live_rows(s, "show", sid, f)
            return rows[0].value_json if rows else None
        by_group: dict[str, int] = {}
        by_lang: dict[str, int] = {}
        by_act: dict[str, int] = {}
        by_style: dict[str, int] = {}
        for sh in shows:
            gg = (v(sh.id, "category_group") or ["?"])
            by_group[gg[0] if gg else "?"] = by_group.get(gg[0] if gg else "?", 0) + 1
            by_lang[sh.language or "?"] = by_lang.get(sh.language or "?", 0) + 1
            by_act[sh.activity or "?"] = by_act.get(sh.activity or "?", 0) + 1
            st = v(sh.id, "conversational_style") or "?"
            by_style[st] = by_style.get(st, 0) + 1
        total = s.scalar(select(func.count()).select_from(Show).where(Show.merged_into.is_(None)))
    fails: dict[str, int] = {}
    for r in results:
        if r["status"] == "fetch_failed":
            fails[r["reason"] or "other"] = fails.get(r["reason"] or "other", 0) + 1
    ing = [r for r in results if r["status"] == "ingested"]
    secs = sorted(r["seconds"] for r in ing)
    summary = {"finished": time.strftime("%Y-%m-%d %H:%M:%S"), "wall_seconds": round(time.perf_counter() - t0, 1), "target": args.target,
               "quota": quota, "accepted_by_seed_group": accepted, "shows_in_store": total, "by_store_group": by_group, "by_language": by_lang,
               "by_activity": by_act, "by_style": by_style, "rejections": rejections, "fetch_failures": fails,
               "attempted_feeds": sum(1 for r in results if r["status"] in ("ingested", "fetch_failed", "rejected", "ingest_failed")),
               "fetch_ok": sum(1 for r in results if r["status"] in ("ingested", "rejected")),
               "ingest_failed": sum(1 for r in results if r["status"] == "ingest_failed"),
               "ingest_seconds": {"median": secs[len(secs) // 2] if secs else None, "p95": secs[int(.95 * (len(secs) - 1))] if secs else None},
               "calibration": cal, "label_set": label_ids, "rules": rules.version, "results": results}
    (ROOT / "eval").mkdir(exist_ok=True)
    (ROOT / "eval" / "seed_run.json").write_text(json.dumps(summary, indent=1, default=str), encoding="utf-8")
    feeds_file().write_text("# url<TAB>group  (independent, active; discovered via iTunes Search " + time.strftime("%Y-%m-%d") + ")\n"
                            + "\n".join(f"{r['url']}\t{r['group']}" for r in ing) + "\n", encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ("shows_in_store", "accepted_by_seed_group", "by_activity", "by_language", "by_style",
                                              "rejections", "fetch_failures", "attempted_feeds", "fetch_ok", "wall_seconds")}, indent=1))
    short = {g: quota[g] - accepted[g] for g in groups if accepted[g] < quota[g]}
    if short:
        print(f"SHORTFALL (not enough independent active candidates passed): {short}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
