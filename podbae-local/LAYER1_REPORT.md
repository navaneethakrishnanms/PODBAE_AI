# LAYER 1 REPORT: Podcast Intelligence + Trust Spine

Status: built, tested, seeded with real shows, running. Measured numbers are in `EVAL_LAYER1.md`. **No Layer 2+ work was done.**

## What works (verified by tests or measurement)
- **Trust spine** (`services/ai/app/intel/trust/`, tables via Alembic `0001`): sources, provenance (tier/method/confidence/expiry/superseded_by), evidence (<=300 chars), cost_ledger, budgets, jobs, audit_log.
  - Field-level freshness policy: stale values are flagged in the profile and a refresh job is queued.
  - Conflicts keep all values; the resolver picks by tier then freshness, and logs the conflict.
  - Untrusted-content guard: HTML/script/control-char stripping and length caps; text reaches LLMs only inside `<untrusted_data>` blocks with delimiter look-alikes neutralised.
  - Jobs: idempotent keys, stage checkpoints, resume after a kill, exponential backoff to `max_attempts`, then `failed` with a reason.
  - Budgets: checked before every LLM/GPU/paid call; skip + ledger row + audit entry + graceful rules-only degrade.
- **Ingestion:** RSS (httpx + feedparser + tolerant lxml pass for `podcast:` tags), SSRF-safe URL validation on every redirect hop, size caps, conditional GET (ETag/Last-Modified), latest 200 episodes stored and 20 processed deeply, provided transcripts only (quality-checked).
  - Identity: aliases (normalised URL, `podcast:guid`, Podcast Index id, iTunes id), redirects, `itunes:new-feed-url`, duplicate collapse.
  - Episodes marked removed rather than deleted; language detection; active/slowing/inactive.
- **Understanding:** rules first; LLM extraction behind a strict pydantic schema (extra fields forbidden; age/gender/income/city/listener-count keys and free-text claims rejected); evidence snippets must literally occur in the cited source or are dropped; cached by content hash + prompt version + model version; invalid JSON gives bounded retries then a low-confidence rules-only fallback.
- **Embeddings/search:** `intfloat/multilingual-e5-small` (384-d, multilingual, ~118M params; runs on your GPU, confirmed `cuda`). Separate content / style / transcript-chunk spaces, re-embed on model change, `VectorIndex` with sqlite-vec.
- **Creator data:** two-step audience CSV upload (column mapping, range/plausibility flags, never silently dropped), self-declared goals/openness/blocked categories, all stored `creator_provided` with the file as evidence.
- **Profile:** `GET /v1/shows/{id}/profile` returns value + tier + source + fetched_at + freshness + confidence + evidence per field, a completeness score, missing fields (never guessed) and an "improve" list; 1-2 episode shows get `preliminary`.
- **App wiring:** `/api/agent/ingest-rss` and the submit flow call `/v1/ingest/rss`; live job progress on `/success` and `/intelligence`; `/intelligence`, `/discover` real-shows section, admin Ingestion jobs / Coverage / Costs tabs; "may be outdated" cached-profile banner when the AI service is down (tested); TS contracts in `packages/contracts/src/intelligence.ts`.
- **Tests:** pytest 88 passed (all your listed acceptance cases incl. 5,000-episode feed, kill-and-resume, injection, forbidden fields, cache hit, budget skip, tier/source/timestamp on every field, Alembic migrations); vitest 18 passed; typecheck, lint and web build clean.

## Measured numbers (details in EVAL_LAYER1.md)
- Seed: **102 real shows in the store** (91 of 279 attempted feeds ingested in this run, plus 11 from earlier partial runs), not the 300 requested. 188 failures: connect/read timeouts (114), HTTP 403/404 (38), non-feed pages (17), connection/TLS errors (11), dropped connections (5).
- Ingestion time per show: mean 5.4 s, median 2.8 s, p95 25 s (6 parallel workers, includes GPU embedding).
- Cost (estimates): avg $0.00005/show, p95 $0.00017/show; all of it is GPU-time pricing, since the mock LLM is $0. Forced re-ingest of 30 shows: 100% enrichment and embedding cache hits.
- Extraction vs 30 labels (mock/heuristic, **labels written by me, please review**): topics recall 60%, vibe top-3 overlap 1.50/3 (random 0.75), top-1 in labels 63% (random 25%), conversational style 30% (majority baseline 27%), guest-friendly 60% accuracy (recall is poor: 3 of 15 found).
- Dedupe on constructed cases: precision 1.00, recall 0.89 (the one miss is the deliberately hard all-new-guid migration).

## What is mocked / not exercised
- **LLM is the mock heuristic provider.** The OpenAI/Anthropic HTTP providers exist but were never called (no keys); their prices are estimates to verify.
- **Podcast Index and Taddy were never run** (no keys). The code is written to their docs; the coverage matrix therefore has an `rss` block only.
- **pgvector backend and Postgres URL** are written but untested (no Postgres here).
- **Whisper transcription** is off by default; only the gating (disabled / no opt-in / not owner) is tested, not actual transcription.
- Discovery used the public **gPodder directory** because this network blocks iTunes Search and many podcast hosts; gPodder skews to older shows (many inactive or dead feeds), so the seed is not a clean sample of "independent shows".
- The UI was opened in the browser but I have not visually verified it; use `TESTING_CHECKLIST.md` section 8b.

## Field availability by source (from the coverage matrix, rss, 102 shows)
Title 99%, description 98%, language tag 97%, episodes 96%, episode dates 95%, episode descriptions 95%, image 95%, author 88%, categories 87%, episode durations 69%.
Rare: `podcast:guid` 15%, `itunes:new-feed-url` 16%, explicit flag 10%, **transcripts 10%**, **`podcast:person` 7%**.
Audience demographics, listener counts: **0%** from any public source; only creator uploads can supply them.
Podcast Index / Taddy coverage: unmeasured.

## Known risks / weaknesses
1. Extraction quality is heuristic-level (numbers above). Style classification is barely above baseline; guest-friendliness misses most guest shows; topics leak noisy RSS category tags (e.g. "Aspartame").
2. **Style-space similarity is not useful yet:** short style text embeds to cosine ~0.97 for unrelated shows. Content-space neighbours look topically sensible but only 16% share a declared category (categories are noisy). Treat `space=style` as experimental.
3. Subset-feed rule: a same-title feed whose episodes are all contained in another is treated as a duplicate (right for truncated mirrors, wrong for a rare homonym with fewer episodes).
4. The intelligence API has no auth of its own: it binds to localhost and relies on the Node API for sessions and ownership. Do not expose port 8000.
5. SQLite is single-node. Worker threads are in-process; the `jobs` table is the source of truth so a real queue can replace them.
6. "Independent" filtering is a host/subscriber heuristic, not a guarantee.
7. RSS content is public but belongs to publishers; before commercial use, check each source's terms (`sources.terms_note` is where this is recorded).

## Seams left for later layers
**Layer 2 (sponsor intelligence)**
- Same trust spine: new `entity_type` values (`brand`, `campaign`) in `provenance`/`evidence`/`cost_ledger`; `sources.kind` is a free string.
- A new connector in `connectors/` (reports its returned fields into `connector_runs`, so the coverage matrix extends automatically) and a job type via `@register("...")`.
- Reuse `understanding/extract.py` pattern (sanitised blocks -> strict schema -> cache -> fallback) with a new schema + prompt version.
- New `VectorIndex` space (`space="brand"`); `similar()` already takes `entity_type`.
- Show-side inputs it can read through the profile API: `topics`, `values`, `brand_safety_flags`, `creator.blocked_categories`, `audience.*`.

**Layer 4 (opportunity engine)**
- Inputs are `GET /v1/shows/{id}/profile` (all fields carry tier + confidence, so scoring can weigh by trust) and `GET /v1/shows/{id}/similar`.
- Budgets already support `user` and `tier` scopes for plan-based economics.
- The existing app matching service (`apps/api/src/services/matching.ts` -> `/match`) is the integration point; nothing in Layer 1 changes its contract.
- Explanations can cite `evidence` ids and `provenance_id` from profile fields.

## Run it
`npm run dev` -> http://localhost:5173/intelligence (login `podcaster@podbae.local` / `demo123`; already connected to a real feed via `npm run intel:connect-demo`). Re-seed: `npm run intel:seed` (stop `npm run dev` first is NOT required; SQLite WAL allows it). Tests: `npm run test:ai`, `npm test`.

STOPPED here as instructed. Awaiting your review of labels (`services/ai/eval/labels.yaml`) and the numbers.
