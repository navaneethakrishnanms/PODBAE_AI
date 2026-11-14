# PHASE 3 REPORT: Layer 2 Sponsor Intelligence and sponsor opportunities

- **No LLM** anywhere. A test asserts zero LLM ledger rows and no `method=llm` provenance. Brand names come from local zero-shot NER (GLiNER) or rules.
- Venue, agent (Bae) and advertiser-side features were **not** built.
- **No git commands were run.**
- **No person or email address is shown, guessed or stored:** 0 of 59,875 stored snippets contain an email, and contact lines are redacted before storage.
- Numbers: `EVAL_LAYER2.md`.

## Step 0: backup
- A code and data backup was taken before the work started.
- **At the user's request, all backup folders were later deleted** (`C:\Users\nk\PODBAE\backups`, `C:\Nk\PODBAE\backups`), because the code is on GitHub.
- No backup of the pre-Phase-3 `intel.db` exists any more. Migrations 0004 and 0005 are additive (0005 compacts old opportunity rows).

## Step 1: Phase 2 leftovers
- **Language gate (the en → ro case):**
  - A show declared English, but language detection reported Romanian at confidence 1.0 from a very short description ("Salut."). The detected language overrode the declared one, so the show was hard-rejected against English shows.
  - Now detection may override the declared language only if the text sample is **≥ 400 characters** (`language_detected_min_chars`) *and* confidence ≥ 0.9. Otherwise the declared language wins.
  - Test: `test_language_detection_needs_a_long_enough_text_sample`.
- **Why-now pluralisation:** "1 recent guest episode" now uses its own `.one` template.
  - Test: `test_why_now_guest_episode_pluralised_and_faithful`.
- **Storage:**
  - The engine now persists only *qualified* opportunities. Run histograms live in `run.stats`, and old rejections are pruned.
  - `intel:compact` shrank `intel.db` from **733 MB to 234 MB**.
- **Engine fields:** the new creator fields (blocked brands, blocked categories, exclusive categories) and `contact_routes` are loaded by the engine, so gates actually see them.

## What was built
**Detection:** `services/ai/app/sponsors/detect.py` and `ner.py`.
- **Inputs:** all stored show notes for every episode (35,877), not only the latest 20, plus all 422 transcripts.
- **Rule tables:**
  - explicit sponsor phrases
  - ad headers
  - promo codes / offers
  - self-promotion cues (own domains, merch, Patreon)
  - podcast-link cues
  - network / ad-choices / hosting boilerplate
  - regulatory disclaimers (e.g. responsible gambling)
- **8 classes:**
  - declared_sponsorship
  - likely_sponsorship
  - affiliate
  - podcast_promo
  - self_promotion
  - network_disclosure
  - organic_mention
  - uncertain
- **Sponsorship history = declared + likely** (likely at weight 0.5), plus any event a human reviewed as correct.
- **Brand names:**
  - GLiNER `urchade/gliner_small-v2.1` runs on short windows after ad cues.
  - A capitalised-phrase rule is the fallback, cut at sentence punctuation; imperative ad words ("Use", "Get", "Visit") are never names.
  - The method that ran is recorded on every event (`method`, `model_version`).
  - `SPONSOR_NER=rules` forces rules only.
- **Why GLiNER:**
  - zero-shot ("brand / company / product") with no training data
  - Apache-2.0 (the multilingual GLiNER is CC BY-NC, so unusable)
  - about 166M parameters, about 2 GB GPU memory
  - gliner 0.2.16 keeps the pinned transformers 4.46; newer gliner would move the whole torch stack
- **URLs:**
  - Offline `tldextract` (no network suffix-list fetch).
  - Tenant link platforms (onelink.me, ubpages.com, …) are not brands.
  - Affiliate hosts are classed as affiliate; denylisted platforms (Spotify, Apple, YouTube, hosting providers, …) are never brands.
- **Privacy:**
  - Every snippet passes `no_contacts()` before storage: lines with emails, phone or booking contact are removed (6,328 lines).
  - Re-scans refresh stored snippets, so a new redaction rule applies to old events too.

**Brand resolution:** `resolve.py`.
- Domain first: one brand per registrable domain. Subdomains collapse into it, and a name next to its domain becomes an alias.
- Then names via seed aliases (`seed/brand_aliases.yaml`). Otherwise a name-only brand is created; name-only spellings are never auto-merged.
- Parents come from seeds (a product → its company).
- Status: active (an event within 180 days), inactive, unknown.
- Categories:
  - 28 categories (`seed/categories.yaml`); 9 are flagged sensitive: weight loss, alcohol, cannabis/CBD, gambling, crypto trading, firearms, political, adult, dating.
  - Inferred with e5 and a sensitive-word lexicon requirement, so a sensitive category is never assigned by similarity alone.
  - `seed/category_overrides.yaml` and manual edits always win and survive re-scans.

**Human review:** `review.py`.
- `/admin/sponsors/review`: stratified queue over classes. The verdict is ok or reject, with an optional corrected class ("Not evidence" = reject).
- Precision and agreement are computed per class and per reviewer pair. The reviewer names "claude" and "claude-draft" are rejected, so machine-written reviews cannot count.
- `/admin/sponsors/brands`: list, detail with recent events, merge, split, set categories, link a registration.

**Sponsor opportunities:** `opportunities.py`, on the **same** engine as podcast partners, not a fork.
- Shared parts:
  - `engine.persist / list_for_member` with `kind="sponsor"`
  - `factors.combine_rows` (same Fit formula and missing-data renormalisation)
  - `explain.build` with sponsor templates (same faithfulness check: templates contain no digits, and every number comes from a slot)
  - the same confidence formula and the same events table
- Candidates: sponsors of the member's 30 nearest shows (e5) plus shows sharing declared topics; cap 150.
- Gates, each with a reason code:
  - inactive_brand
  - already_sponsors_member
  - blocked_brand, blocked_brand_category
  - sensitive_category_default (sensitive categories gated by default for Kids & Family / parenting shows)
  - competitor_exclusivity (the member's exclusive categories)
  - contact / dismiss / partnership cooldowns
  - no_sponsorship_evidence, insufficient_evidence
- Readiness:
  - **Verified** = the brand registered on PodBae, matched by domain only.
  - **Potential lead** = ≥ 2 declared sponsorships, recent within 90 days.
  - Otherwise **Discovery lead**.
  - No contact person or email is ever attached.
- Why-now:
  - sponsored similar shows in the last 30 / 60 days
  - started sponsoring the member's category in the last 60 days
  - rising (≥ 3 recent events at 1.5× the previous window)
  - campaign in the last 30 days

**Storage:** Alembic `0004` and `0005`.
- 0004 adds `brands`, `brand_domains`, `sponsorship_events`, `sponsor_reviews`, `brand_registrations` and `sponsor_scan_runs`.
- 0004 also adds `kind` and `stats` on opportunity runs.
- 0005 compacts runs.
- Express gets drizzle `0003`: `opportunity_cache.kind` with unique (user, kind).

**API (`/v1`, service token):**
- `/sponsor-opportunities`, `/sponsor-opportunities/generate`
- `/shows/{id}/sponsors` (public: declared / reviewed only)
- `/admin/engine/sponsor-metrics`
- `/admin/sponsors/{scan, stats, review/queue, review/{id}, review/precision, brands, brands/{id}, brands/merge, brands/{id}/split, brands/{id}/categories, brands/{id}/registration}`
- `/sponsors/registrations`

**App:**
- Sponsor cards show:
  - Fit, confidence, readiness and evidence as separate measures
  - why-now, evidence snippets, and "Show breakdown"
  - Save / Dismiss with a sponsor reason / Mark contacted
- Tier gating:
  - **Flirt** sees a locked notice.
  - **Date** gets 2 per day, stable within the day.
  - **Commit** sees all.
- If the AI service is down, the last list comes from `opportunity_cache` with a "may be outdated" banner.
- Sponsor settings on `/intelligence`: blocked brands, blocked categories, exclusive categories.
- Public "Sponsors seen" on Discover and Intelligence.
- Admin → Engine tab has a sponsor engine section; the two new admin pages are linked.
- "Set up demo members" also generates sponsor opportunities.

**Scripts:** `npm run sponsors:scan`, `npm run intel:eval2`, `npm run intel:compact`. `doctor` checks gliner and tldextract.

## Draft factors and weights: UNAPPROVED BY THE FOUNDER (`sponsor-draft-v1`)
| Factor | Weight | Definition |
|---|---|---|
| lookalike_affinity | 0.35 | Sum over the member's 30 nearest shows of similarity × that show sponsored the brand (declared 1.0, likely 0.5), 120-day half-life |
| category_fit | 0.20 | Brand categories vs member category groups / declared topics |
| momentum | 0.15 | Brand's events in the last 90 days vs the 90 before |
| recency | 0.15 | Days since the brand's last sponsorship anywhere, 60-day half-life |
| breadth | 0.15 | Distinct sponsored shows, diminishing returns (scale 3) |
| audience_size_fit | 0.10 | **Disabled**: no audience data |
| geo_fit | 0.05 | **Disabled**: no audience data |

- **Shown only if:** Fit ≥ 45 **and** confidence ≥ 0.40.
- Nothing is padded. If nothing qualifies, the member sees "No good match yet".

## Measured (details in EVAL_LAYER2.md)
- **Sponsorship history:** 111 / 303 shows (36.6%).
- **Ad boilerplate but no visible brand:** 30 shows (9.9%), most likely dynamic ad insertion, which text cannot see.
- **Brands:** 988; 260 active; **57 active on ≥ 2 shows**. The threshold was 30, so no corpus expansion was needed.
- **Sponsor opportunities:** ≥ 1 for **282 / 303**, ≥ 3 for 249, no match for 21.
  - Readiness: 1,458 potential / 760 discovery / **0 verified**.
  - Faithfulness problems: 0. Latency p50 73 ms / p95 176 ms.
- **Merge test:** 55 pairs, 3 true merges, 0 false, 0 missed.
- **Precision of every class: UNMEASURED.** There are 0 human reviews.

## Why 0 Verified
- Verified requires a brand registration matched **by domain**.
- The MVP advertisers in the Express database have no website, so `syncAdvertisers()` links none of them.
- Name matching was deliberately not used, because it would create false "verified" claims.
- To get Verified, advertisers need a website field, or an admin links them in `/admin/sponsors/brands`.

## Unmeasured until humans review
- Per-class detection precision; most important for likely_sponsorship and organic_mention.
- Whether sponsor opportunities are useful to creators: no sponsor pair labels exist.
- Inferred category accuracy. Spot checks show weak ones (Chime → Fashion), so treat categories as estimates.

## Risks
- **Dynamic ads are invisible.** Show notes and the few transcripts only see baked-in or disclosed reads, so coverage is a lower bound.
- **Transcripts are sparse:** 422 for 35,877 episodes.
- **Domain-derived display names** ("Uncommongoods", "Buyraycon") look unpolished until someone renames them.
- **Low confidence share:** 1,109 of 2,218 qualifying opportunities are Low, mainly because audience factors are disabled.
- **GLiNER pin:** gliner 0.2.16 with pure-python protobuf. Upgrading transformers to 4.51+ would allow newer GLiNER, but it moves the whole stack.
- **Sensitive-category policy** is a draft: gated by default only for Kids & Family / parenting shows.

## Questions for the founder
1. **Sponsor priorities:**
   - Are the factor weights right? Should lookalike (similar shows' sponsors) dominate, or category fit?
   - Is Fit ≥ 45 the right bar?
2. **Sensitive categories:**
   - Should the 9 sensitive categories (alcohol, gambling, cannabis/CBD, firearms, crypto trading, weight loss, political, adult, dating) be off by default for *all* creators (opt-in), or only for Kids & Family / parenting shows as now?
   - Should telehealth / pharmacy be added to the list? It is not sensitive today.
3. **Exclusivity:**
   - Should a creator's existing sponsor automatically block its competitors, or only when the creator declares an exclusive category (as now)?
4. **Verified:**
   - Should advertisers be required to give a website at signup, so that domain matching can mark them Verified?
5. **Tiers:**
   - Is Date = 2 sponsor recommendations per day right?

## Seams (built, disabled, return no fake data)
- **Rephonic** (`connectors/rephonic.py`): audience and sponsor data. It needs a key and is untested. It would feed audience_size_fit / geo_fit.
- **LLM phrasing:** `explain.py` keeps the seam from Phase 2. Explanations are templates only.
- **Bae (agent):** not built. Sponsor opportunities expose ids, readiness and reasons that an agent could use later.

## Verification (clean restart)
All checks ran on 2026-11-14 after the final re-scan.

**Final scan:**
- 303 shows, 35,877 episodes, 59,875 events.
- GLiNER on cuda:0, 322 s.

**Layer 2 eval:**
- 0 snippets with an email.
- Merge test: 0 false merges.
- Faithfulness problems: 0.

**pytest:** **237 passed** (full AI suite, 306 s). It includes 12 sponsor tests:
- organic mention is mandatory
- self / network / podcast-promo / affiliate classes
- repeated ad blocks
- domain merge and platform names
- sponsor opportunities
- Verified only when registered, never an email or a person
- gates and exclusivity
- determinism, missing data, no padding
- review
- no LLM and the service token
- events and public sponsors

**Node checks:**
- typecheck and lint clean.
- **vitest 33 passed**, including 3 sponsor tests.
- Web build clean.

**Clean restart:**
1. `npm run stop`; a stale `data/pglite/postmaster.pid` was removed.
2. `npm run doctor`: 13 PASS, 1 WARN (the known lxml-before-sentence_transformers order, which the service avoids), 0 FAIL.
3. `npm run dev`: AI :8000, API :5000 and web :5173 all returned 200.
4. Admin "Set up demo members" via the API.

**`npm run ui:smoke`:** 32 pages visited, **32 clean**, 0 with problems. This covers the new `/admin/sponsors/review` (116 queue items rendered) and `/admin/sponsors/brands` (100 brands listed, detail opened).
- Flirt podcaster and the no-match member: "Sponsor recommendations are locked" shown, 0 sponsor cards.
- Commit showcase member: **11 sponsor cards**.
- On the first smoke run this member showed 0 cards, because their sponsor list was still being generated on first request (the "Looking for sponsors…" state). The second run, after generation finished, showed 11.

**http://localhost:5173 is running.**
