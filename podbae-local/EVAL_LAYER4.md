# EVAL_LAYER4: Opportunity Engine (podcast partners), measured numbers

_Phase 2 close-out, 2026-11-12._
- Engine **`fit-draft-v2`**, status **draft-unapproved-by-founder**.
- No LLM was used for any value here.
- Regenerate: `npm run intel:eval4`. Raw data: `services/ai/eval/layer4_before.json` (v1 rules) and `layer4_after.json` (v2).
- Method: every store show is treated as a hypothetical member, run with an empty interaction history, read-only.

## 1. Quality vs human labels: NOT MEASURED YET
- The blind pair-label set is frozen: **20 member shows, 162 pairs** (union of the engine top 5 and the legacy top 5, shuffled; the payload never names the system).
- **0 human pair labels exist.** So **Precision@3, nDCG@5 and Coverage@3 for engine vs legacy do not exist**, and quality is unmeasured.
- To label: admin → `/admin/labels/pairs`, ideally 2+ people.
- Definitions: gains good=2 / ok=1 / bad=0.
  - **P@3:** share of top-3 slots rated good; an empty slot counts as not good, because the engine never pads.
  - **nDCG@5:** against the ideal ordering of all labelled pairs.
  - **Coverage@3:** share of member shows with 3 results, all rated ok or better.
- Agreement: Cohen's kappa and exact agreement per labeler pair.

## 2. Language gate: before vs after
**Rule change:**
- Tags are normalised to the base language (en-US / en-GB → en).
- A hard reject happens **only when both languages are confidently known and different**.
- When declared and detected tags disagree, the detected language is used if its confidence is ≥ 0.9. Otherwise the language is *uncertain*: the pair is not rejected, its confidence is multiplied by 0.8, and the reason is shown in the breakdown.

| | Before (v1) | After (v2) |
|---|---|---|
| Language rejections | **5,572** | **5,312** |
| … with no declared/detected disagreement (confidently different languages) | 5,007 | 5,007 |
| … where a side had a declared/detected disagreement | 565 | 305 (detection conf ≥ 0.9, so the detected language is trusted) |
| Pairs now scored with an uncertain language (confidence × 0.8) | 0 | 260 |
| Shows with ≥1 / ≥3 qualifying | 275 / 247 | 275 / 247 |
| No-match rate | 28 / 303 (9.2%) | 28 / 303 (9.2%) |

Notes:
- The 5,572 differs slightly from the earlier 5,609 because the demo membership changed in between.
- Top language pairs rejected (after): de→en 1,134 · en→de 646 · nl→en 583 · en→nl 319 · fr→en 291 · en→fr 182 · sv→en 173 · tr→en 168 · el→en 155 · sk→en 152.
- **Why `en-US` vs `en` never mattered here:** Layer 1 already stores base codes. Declared tags: en 277, de 8, nl 4, es 3, fr 2, one each of pt / no / el / tr / so / sk / zh / fil / sv.
- Only 6 shows have a declared/detected disagreement. One declares `en`, but detection says `ro` with confidence 1.0. Under the rule, that show is treated as Romanian, which is probably a detector error.
- Coverage did not change: the 260 newly scored pairs did not reach the Fit / confidence thresholds.

## 3. Commercial status: before vs after
**New rule:**
- **Verified:** a member who opted into collaboration (unchanged).
- **Potential lead:** a member without stated openness, **or** the feed itself declares a contact / booking / guest-application / collaboration page. Detected from URL paths in the show description, episode notes, the website-link path, or a `podcast:person` href. The page is stored as evidence.
- **Discovery lead:** everyone else. A plain homepage alone is not a route.
- No e-mail is ever read or stored: anything with `@` or `mailto` is dropped.

| | Before (homepage counted) | After (declared route required) |
|---|---|---|
| Store shows: Verified / Potential / Discovery | 17 / 279 / 7 | **17 / 19 / 267** |
| Qualified opportunities: Verified / Potential / Discovery | 449 / 4,119 / 105 | **449 / 488 / 3,736** |
| Shows with a declared route (backfill, no fetching) | – | 9 of 303 (7 contact pages, 2 collaboration, 1 guest application; all found in episode notes / show description) |

A strict path rule keeps out false routes. Checked by hand, the URLs it rejected were ads, other companies' "partners" pages, news links and job postings.

## 4. Other numbers without labels (after)
| Measure | Value |
|---|---|
| Fit over all scored pairs (p10 / p50 / p90 / p99) | 19.6 / 33.7 / 55.7 / 74.7 |
| Evidence confidence (p10 / p50 / p90) | 0.457 / 0.536 / 0.656 |
| Qualifying by confidence level | Medium 3,798 · Low 574 · High 301 |
| Gate rejections | language 5,312 · closed_to_collaboration 537 (demo members set to "closed") · same_owner 31 |
| Factor coverage | 6 core factors used in 100% of scored pairs; audience_size_parity and geo_overlap disabled in 100% (no audience data) |
| Top-3 diversity (257 shows with ≥2 results) | mean pairwise content cosine 0.877, i.e. z = 1.3 above a typical pair: related but not clones |
| Explanation faithfulness problems | **0** |
| Determinism (25 shows recomputed) | identical result hashes |
| Latency per show (compute) | p50 172 ms · p95 322 ms · max 480 ms |
| Live run through the AI service, all 303 shows | **303 succeeded, 0 failed, 321 s; service healthy afterwards** |

## 5. Demo accounts (password `demo123`)
| Account | What it shows |
|---|---|
| `podcaster@podbae.local` (Flirt) | 4 qualify; **3 cards** shown (daily limit, never padded), all Verified members |
| `mindful@demo.podbae.local` (Commit) | **37 cards**, all three levels: Verified, Potential lead, Discovery lead (show: The Start My Wellness Podcast) |
| `nomatch@demo.podbae.local` | **No-match state** with suggestions (Somali-language show; candidates excluded by language) |

Demo members now have join dates spread over the past ~6 months, so "Recently joined PodBae" only fires for joins inside the 30-day window.
