"""Seed the intelligence store with REAL independent shows: `npm run intel:seed`.

Source of feeds, in order:
  1. services/ai/seed/feeds.txt  (bundled snapshot: `url<TAB>category` per line), if present and not --rediscover;
  2. Podcast Index search (PODCASTINDEX_API_KEY/SECRET) or, with no key, the free iTunes Search API, across >= 8 categories.
Each discovered list is written back to seed/feeds.txt so the run is reproducible without any key.
Every feed is ingested through the same pipeline/jobs code the API uses, under the configured budget.
Nothing here fabricates data: shows that cannot be fetched are reported as failures.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def load_env() -> None:
    env = ROOT.parents[1] / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


load_env()

CATEGORIES: dict[str, list[str]] = {
    "Comedy": ["comedy podcast", "improv comedy", "stand up comedians", "funny stories", "sketch comedy", "comedy interviews", "humor", "satire"],
    "True Crime": ["true crime podcast", "unsolved mysteries", "cold cases", "murder", "crime stories", "investigation", "paranormal"],
    "Technology": ["technology podcast", "software engineering", "indie hackers", "open source", "programming", "linux", "startups", "gadgets", "cybersecurity", "web development"],
    "Business": ["small business podcast", "entrepreneur interviews", "marketing podcast", "finance podcast", "investing", "career advice", "freelance", "leadership"],
    "Health & Wellness": ["mental health podcast", "fitness and nutrition", "mindfulness meditation", "yoga", "sleep", "healthy living", "therapy", "self care"],
    "Society & Culture": ["culture and society", "personal stories", "relationships podcast", "travel stories", "philosophy", "interviews with people", "community"],
    "Education": ["learn language podcast", "history podcast", "science explained", "language learning", "astronomy", "math", "lectures", "study"],
    "Arts": ["film review podcast", "writing and books", "design podcast", "photography", "music podcast", "poetry", "movie reviews", "book club"],
    "Sports & Hobbies": ["running podcast", "gardening podcast", "board games", "cooking podcast", "cycling", "football", "fishing", "woodworking", "video games"],
    "Kids & Family": ["parenting podcast", "family stories", "kids stories", "homeschool", "children"],
    "Religion & Spirituality": ["spirituality podcast", "faith conversations", "sermon", "bible study", "buddhism", "christian"],
    "News & Politics": ["local news podcast", "policy discussion", "politics podcast", "current events", "economics", "environment"],
}
# large networks / broadcasters: skipped to bias towards independent shows (best-effort heuristic, not a guarantee)
BIG = ("npr.org", "wondery", "iheart", "spotify.com", "siriusxm", "nytimes", "bbc.co.uk", "bbci.co.uk", "cbc.ca", "cnn.com",
       "foxnews", "nbcnews", "abcnews", "theguardian", "pbs.org", "audible", "cadence13", "podtrac.com/pts/redirect.mp3/npr", "feeds.megaphone.fm/ESP",
       "washingtonpost", "wsj.com", "bloomberg", "economist.com", "vox.com", "theatlantic", "slate.com", "gimlet", "radiotopia", "earwolf")


_HOSTS: dict[str, bool] = {}


def host_reachable(url: str) -> bool:
    """Cheap TCP connect probe, cached per host. Some networks block many podcast hosts; probing avoids 20 s timeouts per feed."""
    import socket
    p = urlsplit(url)
    host, port = p.hostname or "", p.port or (443 if p.scheme == "https" else 80)
    key = f"{host}:{port}"
    if key not in _HOSTS:
        try:
            socket.create_connection((host, port), timeout=4).close()
            _HOSTS[key] = True
        except OSError:
            _HOSTS[key] = False
    return _HOSTS[key]


def feeds_file() -> Path:
    return ROOT / "seed" / "feeds.txt"


def discover(target: int, per_query: int) -> list[tuple[str, str]]:
    from app.intel.connectors.base import make_client
    from app.intel.connectors.directory import GPodderSearch, ITunesSearch, PodcastIndex

    out: dict[str, tuple[str, str]] = {}
    skipped_hosts: dict[str, int] = {}
    with make_client() as client:
        pi = PodcastIndex(client)
        itunes = ITunesSearch(client)
        gpod = GPodderSearch(client)
        # no Podcast Index key: iTunes Search if reachable, else the public gPodder directory
        use_itunes = False
        if not pi.available:
            try:
                itunes.search("test", 1); use_itunes = True
            except Exception:  # noqa: BLE001
                use_itunes = False
        provider = "Podcast Index" if pi.available else "iTunes Search" if use_itunes else "gPodder directory (no Podcast Index key; iTunes unreachable)"
        search = pi.search if pi.available else itunes.search if use_itunes else gpod.search
        print(f"discovering via {provider}")
        want_each = max(8, int(target * 1.6 / len(CATEGORIES)))   # oversample: dead feeds are expected
        for cat, terms in CATEGORIES.items():
            got = 0
            for term in terms:
                if got >= want_each:
                    break
                for attempt in range(3):
                    try:
                        found = search(term, per_query)
                        break
                    except Exception as exc:  # noqa: BLE001 - rate limits etc.
                        print(f"  {term}: {type(exc).__name__}, retrying"); time.sleep(8 * (attempt + 1)); found = []
                for f in found:
                    u = f.get("feed_url")
                    if not u or any(b in u.lower() for b in BIG) or (f.get("subscribers") or 0) > 6000:   # skip big networks / huge shows
                        continue
                    if not host_reachable(u):
                        skipped_hosts[urlsplit(u).hostname or "?"] = skipped_hosts.get(urlsplit(u).hostname or "?", 0) + 1
                        continue
                    key = urlsplit(u).netloc + urlsplit(u).path
                    if key not in out:
                        out[key] = (u, cat); got += 1
                time.sleep(3.2 if use_itunes else 0.5)     # iTunes Search allows ~20 calls/min
            print(f"  {cat}: {got} feeds")
    top = sorted(skipped_hosts.items(), key=lambda kv: -kv[1])[:12]
    print(f"skipped {sum(skipped_hosts.values())} feeds on {len(skipped_hosts)} unreachable hosts from this network, e.g. {top}")
    rows = list(out.values())
    random.Random(7).shuffle(rows)
    return rows


def load_list() -> list[tuple[str, str]]:
    rows = []
    for line in feeds_file().read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#"):
            u, _, c = line.partition("\t")
            rows.append((u.strip(), c.strip() or "Unknown"))
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", type=int, default=300, help="shows to ingest")
    ap.add_argument("--concurrency", type=int, default=6)
    ap.add_argument("--rediscover", action="store_true", help="ignore seed/feeds.txt and discover again")
    ap.add_argument("--per-query", type=int, default=50)
    ap.add_argument("--budget-usd", type=float, default=None, help="global monthly budget cap for this run (default from env)")
    args = ap.parse_args()

    if args.budget_usd is not None:
        os.environ["INTEL_BUDGET_GLOBAL_MONTHLY_USD"] = str(args.budget_usd)
    from app import intel
    from app.intel import ingest
    from app.intel.db import session_scope
    from app.intel.models import Show
    from app.intel.trust import budget
    from sqlalchemy import func, select

    intel.startup(start_worker=False)
    if not args.rediscover and feeds_file().exists():
        rows = load_list()
        print(f"using bundled list: {len(rows)} feeds ({feeds_file()})")
    else:
        rows = discover(args.target, args.per_query)
        feeds_file().parent.mkdir(exist_ok=True)
        feeds_file().write_text("# url<TAB>category (discovered " + time.strftime("%Y-%m-%d") + ")\n" + "\n".join(f"{u}\t{c}" for u, c in rows) + "\n", encoding="utf-8")
        print(f"wrote {len(rows)} feeds to {feeds_file()}")

    already = set()
    with session_scope() as s:
        from app.intel.models import ShowAlias
        from app.intel.normalize import url_key
        have = set(s.scalars(select(ShowAlias.value).where(ShowAlias.kind == "rss_url")))
    todo = [(u, c) for u, c in rows if url_key(u) not in have][: max(0, args.target - len(have))] if have else rows[: int(args.target * 1.3)]
    print(f"ingesting {len(todo)} feeds with {args.concurrency} workers (target {args.target}, already stored {len(have)})")

    results: list[dict] = []
    t0 = time.perf_counter()

    def one(u: str, cat: str) -> dict:
        t = time.perf_counter()
        try:
            r = ingest.run_pipeline(u)
            return {"url": u, "category": cat, "ok": True, "show_id": r["show_id"], "status": r["feed"]["status"], "seconds": round(time.perf_counter() - t, 2),
                    "enrich": r.get("enrich", {}).get("mode"), "episodes": r["feed"].get("episodes", {}).get("stored_window")}
        except Exception as exc:  # noqa: BLE001
            return {"url": u, "category": cat, "ok": False, "error": f"{type(exc).__name__}: {exc}"[:200], "seconds": round(time.perf_counter() - t, 2)}

    with ThreadPoolExecutor(args.concurrency) as ex:
        futs = [ex.submit(one, u, c) for u, c in todo]
        for i, f in enumerate(as_completed(futs), 1):
            r = f.result()
            results.append(r)
            if i % 10 == 0 or i == len(futs):
                ok = sum(1 for x in results if x["ok"])
                print(f"  {i}/{len(futs)} done, {ok} ok, {time.perf_counter() - t0:.0f}s elapsed")
            with session_scope() as s:
                if not budget.check(s, 0.0).ok:
                    print("global budget exhausted; remaining enrichment degrades to rules-only")

    with session_scope() as s:
        total = s.scalar(select(func.count()).select_from(Show).where(Show.merged_into.is_(None)))
    (ROOT / "eval").mkdir(exist_ok=True)
    (ROOT / "eval" / "seed_run.json").write_text(json.dumps({"finished": time.strftime("%Y-%m-%d %H:%M:%S"), "wall_seconds": round(time.perf_counter() - t0, 1),
                                                           "shows_in_store": total, "results": results}, indent=1), encoding="utf-8")
    fails = [r for r in results if not r["ok"]]
    print(f"\nDONE: {sum(r['ok'] for r in results)} ok, {len(fails)} failed, {total} shows in store, {time.perf_counter() - t0:.0f}s")
    for r in fails[:15]:
        print("  FAIL", r["url"], r["error"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
