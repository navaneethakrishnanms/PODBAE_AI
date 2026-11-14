# PodBae Local (PODBAE_AI)

A localhost replica of the PodBae MVP (podbae.love) plus the AI layer being built for it, one layer at a time.
Windows, no Docker, **no API keys required**. Everything lives in `podbae-local/`.

| Layer | Status |
|---|---|
| Phase 0: MVP replica (UI, routes, `/api/*` surface) | Done |
| **Layer 1: Podcast Intelligence + Trust Spine** | Built, **hardened in Phase 1** (no LLM; rules + local embeddings). See `podbae-local/PHASE1_REPORT.md` |
| Layer 2-6 (sponsor, venue, opportunity engine, Bae agent, outcomes) | Not started |

## Architecture

```mermaid
flowchart LR
  Web["apps/web<br/>React + Vite :5173"] -- "/api (Vite proxy)" --> API["apps/api<br/>Express :5000"]
  API -- "Drizzle / SQL" --> DB[("Express app DB<br/>PGlite (embedded Postgres)<br/>data/pglite")]
  API -- "HTTP + X-Service-Token<br/>/v1/*, /match, /heybae/chat" --> AI["services/ai<br/>FastAPI 127.0.0.1:8000<br/>(conda: torch_gpu)"]
  AI -- "SQLAlchemy + Alembic" --> IS[("AI intelligence store<br/>SQLite WAL + sqlite-vec<br/>data/intel.db")]
  AI -. "local GPU" .-> E5["multilingual-e5-small<br/>embeddings"]
  AI -. "no key" .-> SRC["RSS feeds · iTunes Search API"]
  API -. "AI down" .-> FB["cached profile / in-process<br/>TS scoring fallback"]
```

Two databases, two owners:

| Store | Owner | Holds |
|---|---|---|
| **Express app DB** (`data/pglite`, PGlite) | `apps/api` | users, sessions, tiers, payments (mock), chat, swipes, matches, UI state, the link between a member's podcast and its intelligence show id (`intel_links`) |
| **AI intelligence store** (`data/intel.db`, SQLite + sqlite-vec; Postgres + pgvector in production, untested) | `services/ai` | shows, episodes, field-level provenance (source, tier, method, confidence, freshness), evidence snippets, embeddings, cost ledger, budgets, jobs, audit log, corpus calibration, human evaluation labels |

The Node API reaches intelligence **only** through the AI service's HTTP API. The AI service listens on `127.0.0.1` only, and every route except `/health` and `/v1/health` requires the header `X-Service-Token` (value `INTEL_SERVICE_TOKEN` in `.env`; Express sends it automatically).

## Layer 1 status (after Phase 1)

- **Ingestion:** RSS (conditional GET, retries, encoding repair, SSRF protection on every redirect hop), iTunes Search for discovery (no key; rate-limited about 20/min and cached). Every failed feed gets a reason code: `dns`, `timeout`, `http_4xx`, `http_5xx`, `tls`, `invalid_xml`, `empty`, `too_large`, `ssrf_blocked`, ...
- **Seed:** about 300 *independent, active* shows across 12 category groups. The definition is in `services/ai/seed/independent.yaml`: a network blocklist, a new episode within 90 days, and at least 5 episodes.
- **Understanding, with no LLM:**
  - topics from a fixed taxonomy (each needs evidence from 2 episodes, or the description + 1 episode)
  - guest detection rules
  - conversational style, with `unknown` when no rule is confident
  - vibe from corpus-calibrated embedding similarity
  - tone, values and brand-safety lexicons

  Each value records `method` = rule / model and a confidence.
- **Similarity:**
  - content: e5 embeddings
  - style: a numeric, mean-centred vector (fixes the Layer 1 problem where unrelated shows scored 0.97)
- **Identity:** a same-title merge needs a strong agreeing signal: podcast:guid, iTunes ID, the same owner (salted email hash; the raw email is never stored), the same artwork, or ≥50% shared distinctive episode GUIDs.
- **Evaluation:** human labels are collected at `/admin/labels`. Claude-written drafts are excluded from scoring.
- **Still mocked / untested:** LLM (none used), Podcast Index and Taddy (no keys), Postgres + pgvector, Whisper.

## Requirements
- **Node 20+** (verified: node **v24.12.0**, npm **11.6.2**) and **Python 3.10** in the conda env **`torch_gpu`**.
- Exact working Python environment: `services/ai/requirements.lock.txt` (pip freeze of `torch_gpu`; minimum ranges in `requirements.txt`).
- Internet access for seeding and real feeds.
- Check everything with **`npm run doctor`** (PASS / WARN / FAIL with the fix for each failure).

## Run
```powershell
conda activate torch_gpu
cd C:\Users\nk\PODBAE\podbae-local
copy .env.example .env      # first time only, then set INTEL_SERVICE_TOKEN to a long random string
npm run setup               # first time only: npm install + pip install + migrations + demo seed
npm run doctor              # environment self-check
npm run dev                 # web http://localhost:5173 · api http://localhost:5000 · ai http://127.0.0.1:8000
```
Open http://localhost:5173. Press `Ctrl+C` to stop all three servers.

- The AI service runs **without auto-reload** (`scripts/dev-ai.mjs` starts the torch_gpu Python directly and kills its
  process tree on exit). Under `conda run`, uvicorn's Windows reloader hung and left orphaned servers.
- When developing the AI service, use `npm run dev:ai:reload` in its own terminal instead.
- If anything is left on 5173 / 5000 / 8000, run `npm run stop` (it only kills PodBae processes).

## Commands (from `podbae-local/`)

| Command | What it does |
|---|---|
| `npm run dev` | start web, api and ai together (ai without auto-reload) |
| `npm run dev:ai:reload` | the AI service alone, with auto-reload (development) |
| `npm run stop` | stop leftover PodBae processes on 5173 / 5000 / 8000 |
| `npm run doctor` | environment self-check: versions, packages, native import order, sqlite-vec, e5 on GPU, data stores, workspace links, ports, .env |
| `npm run sponsors:scan` | Layer 2: scan every stored episode + transcript for sponsorship evidence (rules + local GLiNER on the GPU; no LLM), resolve brands, infer categories |
| `npm run intel:eval2` | Layer 2 evaluation -> `services/ai/eval/layer2.json` (class counts, coverage, brands, sponsor-opportunity coverage, merge test) |
| `npm run intel:compact` | remove superseded / below-threshold opportunity rows and VACUUM `data/intel.db` (stop the AI service first) |
| `npm run intel:eval4` | Layer 4 evaluation without labels (coverage, no-match, gates, readiness, diversity, determinism, latency) -> `services/ai/eval/layer4_after.json` |
| `npm run setup` | install deps, apply migrations (both stores), seed demo data |
| `npm run reset` | wipe the **Express** DB (`data/pglite`) and reseed demo users (stop `npm run dev` first) |
| `npm run db:generate` / `npm run db:migrate` / `npm run seed` | Express DB: new drizzle migration / apply / seed |
| `npm run intel:migrate` | apply Alembic migrations to the intelligence store |
| `npm run intel:seed` | ingest ~300 independent active shows via iTunes Search (add `-- --fresh` to archive the current store first) |
| `npm run intel:connect-demo` | connect `podcaster@podbae.local` to a real feed (needs `npm run dev`) |
| `npm run intel:eval` | write `EVAL_LAYER1.md` (human-label metrics, style similarity, dedupe, seed, coverage, costs) |
| `npm run intel:diagnose-feeds` | re-fetch the Layer 1 feed list and classify every failure |
| `npm run ui:smoke` | Playwright: log in as each role, screenshot the main pages into `screenshots/`, report console errors (needs `npm run dev`) |
| `npm test` · `npm run test:ai` | API tests (vitest) · AI-service tests (pytest) |
| `ENGINE=legacy` (in `.env`) | podcast-partner matching falls back to the old tag-overlap scorer (default: the Layer 4 engine) |
| `npm run typecheck` · `npm run lint` · `npm run build` | quality checks |

## Demo logins (all fake, `demo=true`)
| Email | Password | Role |
|---|---|---|
| admin@podbae.local | admin123 | admin (sees Ingestion / Coverage / Costs / Labels tabs, `/admin/labels`) |
| podcaster@podbae.local | demo123 | podcaster (flirt tier; `/intelligence`) |
| brand@podbae.local | demo123 | advertiser |

Other seeded accounts use `*@demo.podbae.local` / `demo123`. Phase 2 demo (create via Admin -> Engine -> "Set up demo members"):

- `mindful@demo.podbae.local`: Commit-tier showcase, sees every opportunity level.
- `nomatch@demo.podbae.local`: shows the honest no-match state.
- `member01..21@demo.podbae.local`: demo PodBae members.

## Copy-safe: `data/` is NOT in git
`podbae-local/data/` (about 290 MB) holds everything the app has learned. It is git-ignored, along with `.env`, so a `git clone` gives you code only:
- `intel.db`: the intelligence store (shows, episodes, embeddings, sponsor events, brands, opportunities, LLM cache)
- `pglite/`: the app database (users, advertisers, campaigns)
- `intel_uploads/`: uploaded files
- `archive/`: old store snapshots

To move a working copy to another machine or folder:
1. Stop everything first: `npm run stop`. Copying while running can corrupt the SQLite WAL or PGlite files.
2. Copy the whole `podbae-local/data/` folder, and `podbae-local/.env`, to the same place in the new checkout. For example, in PowerShell:
   `robocopy C:\old\podbae-local\data C:\new\podbae-local\data /E`
3. Optional: remove `data/pglite/postmaster.pid` if it was copied.
4. Run `npm run doctor` before `npm run dev`.

Without `data/`, the app starts empty. Re-seed the demo with `npm run seed`, then `npm run intel:seed`, `npm run sponsors:scan`, and Admin → Engine → "Set up demo members".

## Reports
- `podbae-local/PHASE1_REPORT.md`: what Phase 1 changed, before/after numbers, what is still mocked, risks, and what Layer 4 can rely on.
- `podbae-local/EVAL_LAYER1.md`: the measured numbers (regenerate with `npm run intel:eval`).
- `podbae-local/LAYER1_REPORT.md`: the original Layer 1 report (historical).
- `podbae-local/TESTING_CHECKLIST.md`: the manual test list.
- `podbae-local/PHASE2_REPORT.md` · `podbae-local/EVAL_LAYER4.md`: Layer 4 opportunity engine (podcast partners) and its measured numbers.
- `podbae-local/PHASE3_REPORT.md` · `podbae-local/EVAL_LAYER2.md`: Layer 2 sponsor intelligence + sponsor opportunities.

## Folder map (`podbae-local/`)
```
packages/contracts/     zod schemas + types shared by web and api (incl. intelligence.ts)
apps/api/               Express: routes (auth, intake, podcasts, member, social, admin, intel), services (matching, intel client, payments seam)
apps/web/src/           React pages (incl. Intelligence.tsx, Admin.tsx, AdminLabels.tsx) and components
services/ai/app/        FastAPI: main.py (+ /match, /heybae), auth.py (service token), intel/ (Layer 1)
  intel/connectors/     rss, iTunes Search, Podcast Index + Taddy (untested), failure classification
  intel/understanding/  signals.py (rules), model_signals.py (embeddings), pipeline.py, taxonomy.yaml, category_map.yaml,
                        vibes.yaml, first_names.txt, refine.py (LLM seam, disabled), extract.py (LLM path, unused in Phase 1)
  intel/trust/          provenance, budgets + cost ledger, jobs, audit, sanitiser
services/ai/seed/       independent.yaml (seed rules), feeds.txt (last seed's accepted feeds)
services/ai/scripts/    intel_seed.py, eval_layer1.py, feed_diagnose.py
scripts/                connect-demo.mjs, ui_smoke.py, open-browser.mjs
data/                   pglite/ (Express DB), intel.db (intelligence store), archive/ (previous stores)   (git-ignored)
```
