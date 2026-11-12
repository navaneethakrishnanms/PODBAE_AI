# EVAL_LAYER1: measured numbers (after Phase 1)

_Generated 2026-11-12 10:30 by `python scripts/eval_layer1.py report` from the local intelligence store. No LLM was used to produce any value measured here._

## 1. Extraction vs HUMAN labels

Label set: **30 shows** (stratified across category groups, `label_items`). Human labels stored: **0** from **0** labeler(s). Claude-written drafts excluded from scoring: 30 (`labeler: claude-draft`).

**Not available yet: no human labels exist.** Label the 30 shows at http://localhost:5173/admin/labels (admin login), then re-run `python scripts/eval_layer1.py report`. Until then there is NO accuracy number for topics, vibe, style or guest-friendliness, and the acceptance targets (style above the majority baseline, guest-friendly F1 >= 0.7, topic Jaccard per category) are **not yet measurable**.

## 2. Style similarity: diagnosis and fix (Step 5)

**Cause.** Layer 1 embedded a short comma-joined label string (e.g. `Educational, Professional, curious, interview, tech innovation`) with the sentence model. Every show's string is drawn from the same ~40-word vocabulary and has the same shape, and e5 sentence embeddings have a large shared component for short texts (anisotropy), so nearly all pairs land at cosine 0.95-0.99 whatever the labels say. The vector mostly encoded 'this is a short list of podcast adjectives', not which adjectives.

**Fix.** A numeric style vector: 12 calibrated vibe scores + one-hot conversational style (5) + multi-hot tone (8), L2-normalised, then mean-centred across the corpus and re-normalised, so cosine measures how a show *differs from the average show*. Content embeddings are unchanged.

| Pairwise style cosine | n shows | p10 | p50 | p90 |
|---|---|---|---|---|
| BEFORE: Layer 1 store as it was (archived) | 102 | 0.903 | 0.939 | 0.962 |
| BEFORE: old method re-applied to the Phase 1 corpus | 303 | 0.904 | 0.941 | 0.964 |
| AFTER: numeric, mean-centred (Phase 1) | 303 | -0.356 | -0.022 | 0.402 |

**Matched vs contrasting pairs** (pairs chosen by category group only: matched = two shows of the same group, preferring the same rule-detected style; contrasting = groups with opposite registers, e.g. Comedy vs Religion). NEW mean cosine: matched **0.33** vs contrasting **-0.10** (gap +0.43; a matched pair beats a contrasting pair 90% of the time). OLD method on the same pairs: matched 0.95 vs contrasting 0.93 (gap +0.01).

| Type | Show A | Show B | NEW cosine | OLD cosine |
|---|---|---|---|---|
| matched (Comedy) | The Edinburgh Fringe Comedy Podcast | Soder | 0.14 | 0.94 |
| matched (True Crime) | Going West: True Crime | The Minds of Madness - True Crime Storie | 0.62 | 0.96 |
| matched (Religion & Spirituality) | Plain Bible Teaching Podcast | Tabernacle Talk - A Bible Study Podcast  | 0.18 | 0.95 |
| matched (Health & Fitness) | Sound Bites A Nutrition Podcast | The Start My Wellness Podcast | 0.51 | 0.95 |
| matched (Technology) | TECHNOLOGY PODCAST | Podcasts SUCK! (a podcast about how to s | -0.08 | 0.96 |
| matched (Sports) | Unreasonable Doubt - A WVU Basketball Po | The Cheer Mom Podcast | 0.49 | 0.95 |
| matched (Kids & Family) | Sparkle Stories Podcast | Phases - A Parenting podcast with Dr Cou | 0.21 | 0.94 |
| matched (Business) | The Programming Languages Podcast with F | Personal Finance with Ravi Sharma | Aust | 0.56 | 0.96 |
| matched (Education) | Wellness Podcast | Listening Time: English Practice | 0.37 | 0.92 |
| contrasting (Comedy vs Religion & Spirituality) | The Edinburgh Fringe Comedy Podcast | Westheights Teaching Podcast | -0.43 | 0.93 |
| contrasting (True Crime vs Kids & Family) | Going West: True Crime | Sparkle Stories Podcast | -0.18 | 0.93 |
| contrasting (Sports vs Religion & Spirituality) | Locked On Cowboys - Daily Podcast On The | Westheights Teaching Podcast | -0.20 | 0.95 |
| contrasting (Comedy vs Education) | The Edinburgh Fringe Comedy Podcast | BBC 随身英语 | -0.07 | 0.92 |
| contrasting (True Crime vs Health & Fitness) | Going West: True Crime | Sound Bites A Nutrition Podcast | 0.17 | 0.92 |
| contrasting (Technology vs Kids & Family) | TECHNOLOGY PODCAST | Sparkle Stories Podcast | 0.30 | 0.95 |
| contrasting (Business vs True Crime) | The Programming Languages Podcast with F | Going West: True Crime | -0.03 | 0.95 |
| contrasting (Sports vs Education) | Locked On Cowboys - Daily Podcast On The | BBC 随身英语 | -0.27 | 0.90 |
| contrasting (Comedy vs Business) | The Edinburgh Fringe Comedy Podcast | The Programming Languages Podcast with F | -0.18 | 0.96 |

## 3. Dedupe (Step 6, constructed cases)

29 synthetic feeds (20 true shows -> 21 predicted). **Precision 1.000** (false merges: 0), **recall 0.909** (missed merges: 1).
New negatives: same-title homonyms with colliding short episode guids ('ep-1'...), a same-title SUBSET feed whose guids are all contained in the other, and same title + same artwork but different podcast:guid. New positives: host migration with all-new guids but the same owner (salted e-mail hash), and with the same artwork.
Missed: ["HARD: migrated host, all new episode guids, no podcast:guid [/hard1/b.xml]"]

Real seed run: 0 automatic merge(s); 1 same-title pair(s) kept separate because no strong signal agreed. 

## 4. Feed fetching, seed, coverage (Steps 2-3)

Same 279 Layer 1 feed URLs, three measurements:

| Outcome | Layer 1 run (as recorded) | Today, OLD fetcher settings | Today, Phase 1 fetcher |
|---|---|---|---|
| ok | 91 | 159 | 192 |
| connection | 14 | 1 | 1 |
| dns | 1 | 1 | 1 |
| empty | 0 | 2 | 2 |
| http_4xx | 35 | 46 | 51 |
| http_5xx | 3 | 3 | 3 |
| invalid_xml | 17 | 18 | 20 |
| other | 2 | – | 0 |
| timeout | 114 | 46 | 6 |
| tls | 2 | 3 | 3 |

Of the 192 feeds that fetch today, only 90 published in the last 90 days: the Layer 1 gPodder list was mostly old or dead shows, which is why the Phase 1 seed uses iTunes Search + the independent/active filter.

**Phase 1 seed** (2026-11-11 17:11:53, 1125.4 s): **303 shows** in the store (target 300). Feeds attempted 322, fetched OK 298 (93%), ingest failures 15.

| Group | Quota | Accepted |
|---|---|---|
| Comedy | 25 | 25 |
| True Crime | 25 | 25 |
| Technology | 25 | 25 |
| Business | 25 | 25 |
| Health & Fitness | 25 | 25 |
| Society & Culture | 25 | 25 |
| Education | 25 | 25 |
| Arts | 25 | 25 |
| Sports | 25 | 25 |
| Leisure | 25 | 25 |
| Religion & Spirituality | 25 | 25 |
| Kids & Family | 25 | 25 |

By activity: {'active': 276, 'slowing': 27}. By language: {'en': 277, 'es': 3, 'pt': 1, 'fr': 2, 'no': 1, 'nl': 4, 'de': 8, 'el': 1, 'tr': 1, 'so': 1, 'sk': 1, 'zh': 1, 'fil': 1, 'sv': 1}. Conversational style: {'solo_monologue': 71, 'unknown': 132, 'interview': 71, 'co_hosted_banter': 20, '?': 3, 'narrative_storytelling': 3, 'panel': 3}.
Rejections at the iTunes-metadata stage: {'network': 86, 'inactive': 4304, 'genre_outside_seed_groups': 207, 'too_few_episodes': 1325, 'too_many_episodes': 10, 'no_dated_episodes': 1}.
Rejections after reading the RSS feed: {'network': 2, 'too_many_episodes': 1}.
Fetch failures: {'timeout': 3, 'tls': 2, 'http_4xx': 1, 'too_large': 2, 'invalid_xml': 1}.
Ingestion time per show: median 14.4 s, p95 33.74 s.

**Coverage, connector `rss`** (303/303 shows):

| Field | % |
|---|---|
| title | 99.7% |
| description | 99.7% |
| language | 99.7% |
| link | 98.0% |
| image | 99.3% |
| author | 99.7% |
| categories | 99.3% |
| explicit | 2.6% |
| podcast_guid | 30.7% |
| new_feed_url | 25.1% |
| owner_email_hash | 77.2% |
| show_type | 94.7% |
| episodes | 99.7% |
| episode_dates | 99.7% |
| episode_durations | 98.0% |
| episode_descriptions | 99.3% |
| transcripts | 31.7% |
| persons | 5.0% |

Podcast Index and Taddy: **not tested (no keys)**.

## 5. Costs and the no-LLM check

- LLM ledger rows: **0**; provenance rows with method=llm: **0** (Phase 1 requires 0).
- Live provenance rows by method: {'api': 303, 'model': 913, 'parsed': 3271, 'rule': 4563, 'rule+model': 571}.
- Total estimated spend $0.059683 (local GPU time only); avg $0.000197/show, p95 $0.000825/show.
- Embedding cache-hit rate in the ledger: 0.228.
- rss_fetch: 307 ledger rows, 1 cache hits, 0 skipped, $0.0
- embed: 4654 ledger rows, 1062 cache hits, 0 skipped, $0.059683
- transcript_fetch: 422 ledger rows, 0 cache hits, 0 skipped, $0.0

## 6. What Layer 4 can rely on (measured over the store)

303 shows. One row per profile field; 'present' = share of shows with a live value.

| Field | Present | Tier(s) | Method(s) | Confidence min / median / max |
|---|---|---|---|---|
| title | 100% | verified | parsed | 1.00 / 1.00 / 1.00 |
| description | 100% | verified | parsed | 1.00 / 1.00 / 1.00 |
| language | 100% | estimated, verified | model, parsed | 0.71 / 1.00 / 1.00 |
| categories | 100% | verified | parsed | 1.00 / 1.00 / 1.00 |
| declared_topics | 100% | verified | rule | 0.90 / 0.90 / 0.90 |
| explicit | 3% | verified | parsed | 1.00 / 1.00 / 1.00 |
| hosts | 4% | verified | parsed | 1.00 / 1.00 / 1.00 |
| episode_count | 100% | verified | rule | 1.00 / 1.00 / 1.00 |
| last_published | 100% | verified | rule | 1.00 / 1.00 / 1.00 |
| cadence_days | 100% | verified | rule | 1.00 / 1.00 / 1.00 |
| avg_episode_minutes | 98% | verified | rule | 1.00 / 1.00 / 1.00 |
| activity_status | 100% | estimated | rule | 0.80 / 0.80 / 0.80 |
| guests_present | 100% | inferred, verified | parsed, rule | 0.50 / 0.56 / 1.00 |
| transcripts_available | 100% | verified | parsed | 1.00 / 1.00 / 1.00 |
| topics | 100% | inferred | model, rule, rule+model | 0.20 / 0.55 / 0.55 |
| vibe | 100% | inferred | model | 0.35 / 0.35 / 0.35 |
| tone | 100% | inferred | rule | 0.35 / 0.35 / 0.35 |
| conversational_style | 100% | inferred | rule | 0.15 / 0.55 / 0.80 |
| values | 100% | inferred | rule | 0.35 / 0.35 / 0.35 |
| guest_friendliness | 100% | inferred | rule | 0.50 / 0.50 / 0.70 |
| brand_safety_flags | 100% | inferred | rule | 0.40 / 0.40 / 0.40 |
| likely_audience | 98% | inferred | rule | 0.30 / 0.30 / 0.30 |
| audience.totals | 0% | – | – | – |
| audience.top_countries | 0% | – | – | – |
| audience.top_cities | 0% | – | – | – |
| audience.age_bands | 0% | – | – | – |
| creator.goals | 0% | – | – | – |
| creator.collaboration_openness | 0% | – | – | – |
| creator.blocked_categories | 0% | – | – | – |
| vibe_similarity | 100% | inferred | model | 0.30 / 0.30 / 0.30 |
| style_features | 100% | inferred | rule+model | 0.30 / 0.30 / 0.30 |
| category_group | 100% | verified | rule | 0.90 / 0.90 / 0.90 |
| image | 100% | verified | parsed | 1.00 / 1.00 / 1.00 |
| owner_email_hash | 78% | verified | parsed | 1.00 / 1.00 / 1.00 |
| show_type | 95% | verified | parsed | 1.00 / 1.00 / 1.00 |
| directory_categories | 100% | estimated | api | 0.80 / 0.80 / 0.80 |

Conversational style distribution: {'solo_monologue': 72, 'unknown': 134, 'interview': 71, 'co_hosted_banter': 20, 'narrative_storytelling': 3, 'panel': 3}.
Topics per show (after the evidence rule): mean 3.9, shows with none 6.
