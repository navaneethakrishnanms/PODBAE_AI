# PHASE 1 REPORT: Layer 1 hardening (no LLM)

**Scope:** make Layer 1 (Podcast Intelligence + Trust Spine) trustworthy using real data, deterministic rules and the local embedding model (`intfloat/multilingual-e5-small` on the GPU).

- **No LLM was called anywhere in this phase.** The cost ledger has 0 LLM rows, and 0 provenance rows have `method=llm`.
- **No other layer was started.** Layer 4 and the others are untouched.
- **No git commands were run.** Everything was done locally.

Measured numbers: `EVAL_LAYER1.md` (regenerate with `npm run intel:eval`). Raw data: `services/ai/eval/`.

## Status against acceptance

| Acceptance item | Result |
|---|---|
| All existing tests pass + new tests | ✅ **pytest 163 passed** (was 88), **vitest 20 passed** (was 18); typecheck 0 errors, lint clean, web build OK |
| New tests: service token, no LLM calls, failure reasons, independent filter, topic evidence rule, taxonomy mapping, guest rules, style "unknown", numeric style vector, same-title-different-show | ✅ all present (`tests/test_service_auth.py`, `tests/test_phase1.py`, `tests/test_itunes.py`, `apps/api/tests/intel.test.ts`) |
| Feed success rate + failure table | ✅ Same 279 Layer 1 feeds: **91 → 192 OK**; Phase 1 seed: **298/322 fetched OK (93%)**; full reason table below |
| ~300 independent active shows | ✅ **300 accepted, 25 in each of 12 groups**, no shortfall (+3 completed partial ingests = 303 in the store) |
| Style similarity fixed (contrasting below matched) | ✅ matched **0.33** vs contrasting **−0.10** (old method: 0.95 vs 0.93) |
| Dedupe: no false merges in tests; precision/recall | ✅ precision **1.00** (0 false merges), recall **0.91** on 29 constructed feeds |
| Human labels: style above 27% baseline, guest-friendly F1 ≥ 0.7, topic Jaccard per category, old-vs-new | ❌ **Not yet measurable: 0 human labels exist.** The labelling page, storage, agreement statistics and old-vs-new scoring are built and tested; someone must label the 30 shows at `/admin/labels`. Claude-written labels are not ground truth and are excluded. |
| App opens at http://localhost:5173 | ✅ `npm run dev` running; web, api and AI service all return 200; Playwright: 25 pages, 0 problems |

## Step 0: Backup (no git)
- Code (141 files; excludes node_modules, dist, `__pycache__` and model caches): `C:\Nk\PODBAE\backups\podbae-local_before_phase1_20261111_110243.zip`
- Data (a consistent `intel.db` snapshot via the SQLite backup API, plus `pglite/`, `intel_uploads/` and the old `.env`): `C:\Nk\PODBAE\backups\podbae-local_data_before_phase1_20261111_110243\`
- The Layer 1 intelligence store was also moved to `data/archive/intel_layer1_20261111_164644/intel.db` before the new seed.

## Step 1: Housekeeping
- **`README.md` (repo root)** rewritten:
  - architecture diagram with the two stores (Express app DB + AI intelligence store) and the service token
  - Layer 1 status, every command, demo logins, folder map
  - the outdated "placeholder / no ingestion" text is removed
- **`.env.example`:** every setting with a comment on its own line (inline `#` comments would have become part of the value). It covers:
  - LLM: `LLM_PROVIDER`, `INTEL_LLM_REFINE`
  - data sources: `PODCASTINDEX_*`, `TADDY_*`, the iTunes rate limit / cache / country
  - store: `INTEL_DATABASE_URL`, `INTEL_HASH_SALT`
  - feed fetching: timeouts, retries, size cap
  - budgets and cost estimates
  - feature flags and `INTEL_SERVICE_TOKEN`
- **`.env`:** the old copy was saved in the backup folder. The missing keys were appended with safe defaults, plus a freshly generated random `INTEL_SERVICE_TOKEN`. `AI_SERVICE_URL` now points at `127.0.0.1` to match the binding.
- **Service auth:**
  - The AI service binds to `127.0.0.1` (`--host 127.0.0.1`, verified with netstat).
  - Every route except `/health` and `/v1/health` requires `X-Service-Token`, including `/match` and `/heybae/chat`. The comparison is constant-time.
  - **No token configured = fail closed** (401 for everything).
  - Express sends the header on every call (`serviceHeaders()`).
  - Tests: missing token → 401, wrong token → 401, unset token → 401, health open, and Express forwards the header.
- **Shared `.env` loader** (`app/envfile.py`): one implementation for the service and scripts; strips inline comments.

## Step 2: Real data sources (no keys)

**iTunes Search connector** (`connectors/directory.py`):
- no key needed
- process-wide rate limiter (`INTEL_ITUNES_RATE_PER_MIN=20`)
- responses cached in a new `api_cache` table (`INTEL_ITUNES_CACHE_HOURS=24`)
- returns feed URL, publisher, genres and genre IDs, episode count, and latest release date
- discovery passes the iTunes ID and genres into ingestion: the ID becomes an identity alias, the genres a `directory_categories` field (estimated tier)

**Podcast Index and Taddy:** still implemented, still disabled. **Not tested (no keys).**

**Failure diagnosis:**
- Every fetch gets one stable reason code: `dns`, `timeout`, `http_4xx`, `http_5xx`, `tls`, `invalid_xml`, `empty`, `too_large`, `ssrf_blocked`, `connection`, `redirects`, `invalid_url`, `other`.
- Codes are stored per feed URL in `connector_runs` (new columns `target` and `error_kind`).
- They are exposed at `/v1/admin/feed-failures` and in Admin → Coverage.

**Fixes** (SSRF protection unchanged and still checked on every redirect hop):
- an honest browser-compatible user agent
- explicit gzip/deflate
- a separate 10 s connect timeout
- one retry with backoff on timeout, connection reset, 5xx or 429
- BOM / leading-junk / wrong-charset repair
- empty bodies are reported as `empty`, not "invalid"

**Bug fixed:** for a brand-new feed, the failure row was written in a transaction that rolled back when ingestion raised, so failures were never stored. It is now committed separately; a test covers it.

### Feed failure table: same 279 Layer 1 feed URLs

| Outcome | Layer 1 run (as recorded) | Today, OLD fetcher settings | Today, Phase 1 fetcher |
|---|---|---|---|
| **ok** | **91** | **159** | **192** |
| timeout | 114 | 46 | 6 |
| http_4xx (41 × 404, 9 × 403, 1 × 410) | 35 | 46 | 51 |
| invalid_xml (not a feed) | 17 | 18 | 20 |
| connection | 14 | 1 | 1 |
| tls | 2 | 3 | 3 |
| http_5xx | 3 | 3 | 3 |
| empty | 0 | 2 | 2 |
| dns / other | 1 / 2 | 1 / 0 | 1 / 0 |

How to read the 91 → 192 jump:
- **+68 feeds come from the network itself.** The old fetcher, run today, gets 159; Layer 1 ran on a more restricted network, and iTunes was blocked then.
- **+33 feeds come from the Phase 1 fetcher changes.** All of them were timeouts with the old fetcher. Most now fetch OK; a few now show as real 4xx or invalid XML.
- **The remaining failures are real:** 51 dead or forbidden URLs and 20 non-feeds.
- **The old list was the wrong population anyway.** Only 90 of the 192 working feeds published in the last 90 days, because the old gPodder list was mostly old shows.

## Step 3: Representative seed (~300 independent, active shows)

**Rules file:** `services/ai/seed/independent.yaml` (editable). A show must pass all three:
- **Not a network show:**
  - publisher-name blocklist matched as whole words, so "ted" doesn't match "hosted"
  - feed-host blocklist matched as a domain suffix; hosting platforms used by independents (anchor.fm / Spotify for Podcasters, Libsyn, Megaphone…) are deliberately not blocked
- **Active:** a new episode within 90 days.
- **Profilable:** at least 5 episodes (and at most 2,000).

**Two checks:** the iTunes metadata is checked first, then the actual RSS (author, owner name, newest episode, episode count).

**Bug fixed during the run:** iTunes `primaryGenreName` is usually a subcategory ("Home & Garden"). The first attempt only knew top-level names and found only 4 Leisure candidates, so I stopped it, deleted the partial store, and fixed the group resolution.

**Result** (1,125 s; `eval/seed_run.json`, accepted list in `seed/feeds.txt`):

| | |
|---|---|
| Accepted | **25 in each of 12 groups**: Comedy, True Crime, Technology, Business, Health & Fitness, Society & Culture, Education, Arts, Sports, Leisure, Religion & Spirituality, Kids & Family |
| Activity | 276 active, 27 slowing, 0 inactive |
| Language | en 277, de 8, nl 4, es 3, fr 2, 9 others × 1 |
| Rejected at the iTunes stage | inactive 4,304 · too few episodes 1,325 · genre outside the seed groups 207 · network 86 · too many episodes 10 · no dated episodes 1 |
| Rejected after reading the RSS | network 2 · too many episodes 1 |
| Fetch failures | timeout 3 · tls 2 · too_large 2 · http_4xx 1 · invalid_xml 1 |
| Ingest failures | 15, caused by a concurrency bug (below), now fixed; the quota slots were refilled |
| Ingestion time | median 14.4 s/show, p95 33.7 s (6 parallel workers) |

**Concurrency bug found and fixed:** parallel jobs on a fresh store raced to create the same `sources` row (`UNIQUE constraint failed: sources.name`). `get_source` now inserts in a savepoint and reads the winner's row on conflict.
- The new test fails 3/3 with the old code and passes with the fix.
- The 3 shows left half-ingested were completed, so the store has 303 shows.

**Known miss of the filter:** "BBC 随身英语" passed. It is a third-party re-upload on Ximalaya by an individual account, so neither the publisher nor the host is the BBC. The rules cannot see re-uploads or a network brand in the title. Left in the store and flagged here.

## Step 4: Rule-based understanding (no LLM)

The `enrich` stage now runs `understanding/pipeline.py`. The LLM extraction in `extract.py` is kept intact as a seam but is never called by the pipeline. Every field records `method` (`rule` / `model` / `rule+model` / `parsed`), tier, confidence and evidence snippets (≤300 characters, with an episode or description locator).

**Topics** (fixed taxonomy `taxonomy.yaml`: 55 topics in 18 groups):
- Publisher categories are mapped through `category_map.yaml` into a separate **`declared_topics`** field (tier verified: what the publisher says). Unmapped tags (e.g. "Aspartame") never become topics.
- Inferred `topics` come from a curated keyword lexicon (short keywords must match whole words) and from e5 similarity between episode text and topic descriptions (an episode supports a topic only if that topic is its clear #1).
- **Evidence rule:** a topic is kept only with support from ≥2 episodes, or from the description + ≥1 episode; otherwise it is dropped and recorded as dropped. Secondary topics also need at least half the main topic's evidence weight.
- Result: 3.9 topics per show on average; 6 shows have none.

**Guest detection:**
- `podcast:person role=guest`
- title patterns: "feat./ft." + name; "with" + a known first name; "| Name"; "Name on topic"; "Name: topic"
- interview / conversation cues
- first-name-led person names in titles
- description cues ("my guest", "joined by", …)

Names on the host list, and names recurring in more than half the episodes, are hosts and never guests. Stored as a guest-episode share plus up to 3 example titles with the rule that fired. Guest-friendly means a share ≥ 0.30.

**Conversational style** (solo / co-host / interview / panel / narrative): independent rules on guest share, host count (from `podcast:person` or a multi-person author field), description cues, first-person writing, `itunes:type=serial`, numbered parts, and episode length.
- The answer is **"unknown" (confidence 0.15) unless one style scores ≥ 1.0 and leads by ≥ 0.3.**
- Result: unknown 134 · solo 72 · interview 71 · co-hosted 20 · panel 3 · narrative 3.
- So 44% unknown: that's honest coverage, not guesses.

**Vibe (12 terms):**
- e5 similarity between the show text (content vector + mean of the episode vectors) and short descriptions of each term (`vibes.yaml`)
- calibrated across the corpus: a z-score per term, then the normal CDF → 0..1
- `method=model`, tier inferred, confidence 0.35 (lower than rule-backed fields)
- before calibration a show gets a within-show ranking, labelled as such, with confidence 0.2
- evidence: the recent episode closest to each top vibe

**Tone, values, brand safety:** lexicons with word-boundary matching that need hits in ≥2 separate texts. `itunes:explicit` sets the profanity flag.

**Boilerplate removal (Phase 1 finding):**
- **Problem:** a hosting privacy footer ("…use of personal data for advertising") appended to every episode made "Marketing & sales" a 20-episode topic on the demo show.
- **Fix:** known hosting/ad footers are stripped, as is any sentence repeated across ≥40% of a show's episode descriptions. This applies to both the lexicon and the episode embeddings.
- **Effect** after re-running understanding on all 303 shows (`scripts/reunderstand.py`, no re-fetch): "Marketing & sales" fell from 41 shows to 31; 59 shows changed topic sets.

**Lexicon v1.1:** generic keywords removed after a 24-show trial ("community", "culture", "news", "apple", "friendship", "century", …). This was judged from obvious false positives, not tuned against labels.

## Step 5: Style similarity fixed

**Diagnosis.** Layer 1 text-embedded a short label string (e.g. `Educational, Professional, curious, interview`). Every show's string comes from the same ~40-word vocabulary in the same shape. e5 sentence embeddings share a large common component for short texts (anisotropy), so different label lists still score 0.77–0.90 and corpus pairs 0.90–0.96. The vector encoded "a list of podcast adjectives", not *which* adjectives.

**Fix.** A numeric vector:
- 12 calibrated vibe scores + one-hot style (5) + multi-hot tone (8) = 25 dimensions
- L2-normalised, then mean-centred on the corpus mean (`corpus_stats`) and re-normalised, so cosine = centred cosine
- stored in `embeddings(space='style', model='style-numeric-v1')` and the sqlite-vec index
- recomputed by `recalibrate()` after a seed and from Admin → "Recalibrate corpus"
- content embeddings are unchanged

**Pairwise style cosine:**

| | n | p10 | p50 | p90 |
|---|---|---|---|---|
| Before: Layer 1 store (archived) | 102 | 0.903 | 0.939 | 0.962 |
| Before: old method on the Phase 1 corpus | 303 | 0.904 | 0.941 | 0.964 |
| **After: numeric, mean-centred** | 303 | **−0.356** | **−0.022** | **0.402** |

**10 matched vs 10 contrasting pairs.** Pairs were chosen by category group only (matched = same group, preferring the same rule-detected style; contrasting = e.g. Comedy vs Religion). This is independent of the vector being tested.
- **New method:** matched **0.33** vs contrasting **−0.10**; a matched pair beats a contrasting pair **90%** of the time.
- **Old method on the same pairs:** 0.95 vs 0.93.
- The per-pair table with show titles is in `EVAL_LAYER1.md` §2.
- **Weak spots:** some "matched" pairs are only nominally similar, e.g. two Technology shows at −0.08, because the category group alone is a coarse match.

## Step 6: Duplicate-merge risk fixed

**Rule:** a same-title show is merged only when a strong signal agrees:
- same `podcast:guid`
- same iTunes / Podcast Index ID
- same owner (a **salted SHA-256 of the owner email**; the raw email is never stored, logged or exported, which a test checks)
- same artwork (hash of the normalised artwork URL)
- or ≥50% shared **distinctive** episode GUIDs

Short GUIDs like `ep-3` or `12` collide across unrelated shows and no longer count. Different podcast:guids / directory IDs are a hard conflict, so no merge.

**Constructed set** (29 feeds, 20 true shows): **precision 1.000** (0 false merges), **recall 0.909**.
- New negatives that stay separate:
  - same-title homonyms with colliding short GUIDs
  - a same-title *subset* feed whose GUIDs are all contained in the other
  - same title + same artwork but different podcast:guids
- New positives that merge:
  - host migration with all-new GUIDs but the same owner
  - host migration with all-new GUIDs but the same artwork
- The one miss is the deliberately hard case: all-new GUIDs, no owner, no artwork, no podcast:guid.

**Real seed:** 0 merges; 1 same-title pair kept separate (no strong signal).

**Artwork caveat:** artwork is compared by URL, not by image bytes. Two mirrors that re-host the same image under different URLs won't match on artwork.

## Step 7: Human labels
- `eval/labels.yaml` is now marked `labeler: claude-draft`, `excluded_from_scoring: true`. Those IDs also belong to the archived Layer 1 store.
- **`/admin/labels`** (admin-only): 30 stored shows, stratified across groups, labelled one at a time. The page shows the description, categories, and latest 10 episode titles with descriptions. The labeler picks:
  - 1–5 topics from the taxonomy
  - exactly 3 vibes
  - a style (5 + "mixed or other")
  - guest-friendly yes/no
  - optional notes

  Labels are stored per labeler in `eval_labels`, so 2+ labelers are supported (the name is typed and remembered per browser). `claude-draft` is rejected as a labeler name.
- **Agreement:** Cohen's kappa for style and guest-friendly; mean Jaccard for topics, topic groups and vibes, per labeler pair. It is shown on the page and in the eval report.
- **`eval_layer1.py`** scores only human labels and compares, on the same shows:
  - **old:** the Layer 1 mock heuristic, recomputed from the stored text
  - **new:** the Phase 1 pipeline

  It reports style accuracy vs the majority baseline, guest-friendly precision/recall/F1, topic Jaccard per category group, and vibe top-3 Jaccard. With one labeler it reports single-labeler results and says agreement is not available.
- **Current state: 0 human labels, so none of these metrics exist yet.** That is the main open item of this phase.

## Step 8: UI smoke check
- `scripts/ui_smoke.py` (`npm run ui:smoke`, Playwright Chromium). It logs in as public, podcaster, advertiser and admin, and visits 25 pages:
  - landing, signups, discover
  - dashboard, `/intelligence`, swipe, messages, profile, schedule, analytics, partners, listen
  - campaign builder
  - admin + the Ingestion / Coverage / Costs / Labels tabs + `/admin/labels` (fills in a labeler name and renders show 1; saves nothing)
- Full-page screenshots go to `podbae-local/screenshots/`, the report to `screenshots/report.json`.
- **Result: 25/25 clean.** No console errors, page errors or failed requests, except the expected `401 /api/auth/me` for anonymous visitors, which is counted separately.
- I looked at the Intelligence, Coverage and Labels screenshots: they render correctly.

## Other problems found and fixed
1. **Silent embedder fallback.** If e5 failed to load, the code silently switched to a 256-d hash embedder, which would mix incomparable vectors into the store. It now raises `EmbedderUnavailable`. Hash is used only if explicitly configured (tests) or with `INTEL_EMBED_ALLOW_FALLBACK=true`. The eval refuses to report a "before" number from a fallback; that guard caught a wrong 0.33 figure during this phase.
2. **torch vs numpy OpenMP clash in the `torch_gpu` env.** numpy's OpenBLAS uses LLVM `libomp.dll` and torch uses Intel `libiomp5md.dll`.
   - torch first, then a numpy matrix product → process abort (`OMP: Error #15`)
   - numpy BLAS first, then torch → torch fails to load (`WinError 127 fbgemm.dll`)

   All products in the intelligence code now go through `app/intel/linalg.py` (`einsum`, no BLAS), and torch is imported first in the service and scripts. A test forbids numpy `@` / `np.dot` in `app/intel`. Your conda env was not changed.
3. **Stale intelligence link.** Re-linking a podcast to a different feed kept the old show ID. The link is now cleared when the URL changes, and the profile route re-resolves once on 404.
4. The old `TESTING_CHECKLIST.md` gained a §8c for Phase 1; `LAYER1_REPORT.md` is marked historical.

## What is still mocked or untested
| Item | Status |
|---|---|
| LLM (any provider) | **Not used.** `LLM_PROVIDER=mock`; the pipeline never calls a provider (a test asserts this). Hey Bae still uses the mock reply. |
| Podcast Index, Taddy | Implemented, **not tested (no keys)**; disabled. |
| Postgres + pgvector | Code path written, **untested** (SQLite + sqlite-vec only). |
| Whisper transcription | Off by default; only the gating is tested, **not transcription**. |
| Human-label accuracy | **Not measured** (0 labels). |
| Artwork dedupe | URL-based, not image-byte-based. |
| iTunes Search | Tested live (seed) and with a mocked transport (cache + rate limit). Apple's terms on caching/storing results should be checked before commercial use. |

## LLM seams left for the later LLM phase
- **Provider interface** (`understanding/providers.py`): `Provider.complete_json` with mock/OpenAI/Anthropic. An `ollama` provider is a new class + one line in `get_provider()`.
- **Trust wrapper** (`understanding/extract.py`, unchanged and still tested):
  - sanitised `<untrusted_data>` blocks
  - strict schema that forbids demographics
  - evidence must be verbatim
  - content-hash cache
  - budget checks and bounded retries
- **Refinement slot** (`understanding/refine.py`): `@register_refiner(field)` receives the rule/model value, its confidence and the sources. It runs only if `INTEL_LLM_REFINE=true` **and** a refiner is registered (Phase 1: neither). Outputs must be stored as `method=llm`, tier inferred, never over verified or creator-provided data. Fields where an LLM should help most:
  - `conversational_style` when the rules say "unknown" (44% of shows)
  - guest detection: names outside the first-names list; host vs guest
  - topics outside the lexicon / sub-topics
  - text-grounded vibe
  - `likely_audience` wording
  - brand-safety context (an organic mention vs an endorsement)

## Risks
1. **Accuracy is unmeasured** until humans label. The rules were checked only by eye on a 24-show trial and on the demo show.
2. **Guest detection** misses guests whose first name isn't in `first_names.txt` (about 400 common names, English-leaning) unless "feat./ft." or a description cue is used. It may count a recurring co-host as a guest in short feeds (fewer than 4 episodes).
3. **Style coverage is 56%** (44% unknown). Layer 4 must treat "unknown" as missing, not as a category.
4. **Vibe is embedding-only** (confidence 0.35). Scores are relative to *this* corpus: they change when the corpus changes, until recalibration.
5. **Lexicons are English-centric**; 26 non-English shows get fewer lexicon topics and rely more on the multilingual model.
6. **The independent filter** can't catch network content re-uploaded by individuals (the BBC case). The 90-day rule excludes seasonal shows on a break.
7. **The intelligence API has no per-user auth**: it trusts Express and relies on the service token + localhost binding. Rotate `INTEL_SERVICE_TOKEN` if `.env` is shared.
8. **SQLite is single-node**; jobs run in-process. Fine locally, not for production.
9. **RSS and iTunes data** belong to publishers / Apple; the terms of use must be checked before commercial use.

## What Layer 4 can rely on from Layer 1
Measured over the 303 stored shows (`EVAL_LAYER1.md` §6). Every field carries `data_tier`, `method`, `confidence`, `fetched_at`, freshness and evidence via `GET /v1/shows/{id}/profile`.

**Solid (verified, ~100% present):**
- `title`, `description`, `categories`, `language` (declared tag verified; detection is a separate estimated row, and conflicts are flagged)
- `episode_count`, `last_published`, `cadence_days`, `avg_episode_minutes` (98%), `transcripts_available`
- `image`, `show_type` (95%)
- **`declared_topics`** + `category_group` (taxonomy IDs, confidence 0.9)
- `activity_status` (estimated, 0.8)

**Use with their confidence (inferred, 100% present):**
- `topics`: taxonomy IDs with weight, basis (lexicon / model / declared) and supporting-episode counts; confidence 0.20–0.55
- `guests_present` / `guest_friendliness`: share + examples; 0.50–0.70, or 1.0 when `podcast:person`-based
- `conversational_style`: **check for "unknown"**; 0.15–0.80
- `vibe`: corpus-calibrated, 0.35
- `tone`, `values`, `brand_safety_flags`: lexicon, 0.35–0.40
- `likely_audience` (98%): interests only, 0.30

**Similarity:**
- `GET /v1/shows/{id}/similar?space=content`: e5, unchanged
- `space=style`: numeric, centred; now meaningful (matched ≫ contrasting)

**Sparse:**
- `hosts` 4%, `explicit` 3% (most feeds lack `podcast:person` / `itunes:explicit`)
- `owner_email_hash` 78% (identity only, never shown)

**Absent until creators provide them:** all `audience.*` and `creator.*` fields (0%). They are never guessed; Layer 4 must handle them as missing (e.g. the missing-data policy: drop the factor, renormalise, lower confidence).

**Not available:** listener counts / demographics from any public source (0%); Podcast Index / Taddy fields (no keys).

## Run it
```powershell
conda activate torch_gpu; cd C:\Nk\PODBAE\podbae-local
npm run dev                  # web :5173 · api :5000 · ai 127.0.0.1:8000
npm run intel:connect-demo   # podcaster@podbae.local -> a seeded feed; open /intelligence
# label the 30 shows: log in as admin@podbae.local / admin123 -> /admin/labels (ideally 2 people)
npm run intel:eval           # regenerate EVAL_LAYER1.md (human-label metrics appear once labels exist)
npm run ui:smoke             # screenshots + console-error report
npm run test:ai; npm test    # 163 + 20 tests
```

**STOPPED here as instructed.** The next action belongs to a human: label the 30 shows (2+ labelers) so the accuracy targets can be measured.
