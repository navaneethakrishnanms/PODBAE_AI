# EVAL_LAYER1: measured numbers

_Generated 2026-11-04 16:43 by `python scripts/eval_layer1.py report` from the real local intelligence store._


## 1. Extraction vs hand labels (30 shows)

**Caveat:** labels in `eval/labels.yaml` were written by Claude from each show's description and episode titles (see `eval/label_sheet.md`), not by a human listener. They are for you to review and correct; agreement against them measures consistency with a reader of the same text, not ground truth. The extractor under test is the **mock/heuristic provider** (no LLM key), so this is the floor a real LLM must beat.

| Field | Metric | Result | Baseline |
|---|---|---|---|
| topics | label topics found among extracted topics/categories (recall) | 54/90 = 60% | n/a |
| vibe top-3 | mean overlap of predicted vs labelled top-3 | 1.50 / 3 | random 3 of 12 = 0.75 / 3 |
| vibe top-1 | predicted #1 is in labelled top-3 | 19/30 = 63% | random = 25% |
| conversational style | exact match (7 classes) | 9/30 = 30% | always 'interview' = 27% |
| guest-friendly | accuracy @ threshold 0.4 | 18/30 = 60% (TP 3, FP 0, FN 12, TN 15) | majority = 50% |

Style disagreements (label -> predicted): narrative_storytelling -> solo_monologue; co_hosted_banter -> interview; co_hosted_banter -> interview; solo_monologue -> narrative_storytelling; co_hosted_banter -> educational_lecture; narrative_storytelling -> interview; panel -> interview; solo_monologue -> educational_lecture; interview -> narrative_storytelling; narrative_storytelling -> interview; educational_lecture -> solo_monologue; educational_lecture -> interview

<details><summary>Per-show detail</summary>

| Show | Label topics | Predicted topics | Label vibe | Pred vibe | Label style | Pred style | Guest label | Guest pred |
|---|---|---|---|---|---|---|---|---|
| Mike Tech Show Podcast | technology, software, productivity | general interest | Educational, Casual, Professional | Energetic | solo_monologue | solo_monologue | False | False |
| Just So Stories (version 4) by Rudyard | children stories, kipling, audiobook | Arts, Literature, stories, kipling | Compelling, Relaxed, Educational | Uplifting, Energetic | narrative_storytelling | solo_monologue | False | False |
| Bootstrapped Web | For Entrepreneurs B | entrepreneurship, startups, software | Business, Society & Culture, bootstrapping, startups | Professional, Personal Narrative, Casual | Casual, Professional, Educational | co_hosted_banter | interview | False | False |
| Adam Carolla Show | comedy, interviews, pop culture | Comedy, adam, carolla, classics | Humorous, Casual, Energetic | Humorous, Personal Narrative, Professional | interview | interview | True | False |
| iinnovate | innovation, entrepreneurship, venture capital | Consumer Internet, Media, Information Technology, Venture Capital | Professional, Educational, Inspirational | Educational, Personal Narrative, Professional | interview | interview | True | False |
| Programming Throwdown | programming, software engineering, technology | Education, How To, News, Tech News | Educational, Professional, Casual | Casual, Educational, Uplifting | co_hosted_banter | interview | True | True |
| Catholic:Under The Hood | catholic, church history, theology | Franciscan, Catholic, Catholicism, Pope | Educational, Reflective, Humorous | Compelling, Educational, Inspirational | solo_monologue | narrative_storytelling | False | False |
| Feral Attraction | relationships, sexuality, advice | Health>Sexuality, feral, attraction, relationship | Casual, Personal Narrative, Wellness-Focused | Casual, Educational, Personal Narrative | co_hosted_banter | educational_lecture | False | False |
| MUBI Podcast | film, cinema, filmmakers | MUBI, Film, Movie, Cinema | Compelling, Educational, Reflective | Compelling, Educational, Energetic | narrative_storytelling | interview | True | False |
| Nora En Pure - Purified Radio | music, electronic, dj mix | Music, purified, radio, nora | Energetic, Uplifting, Relaxed | Uplifting, Relaxed, Compelling | solo_monologue | solo_monologue | False | False |
| The Reason Interview With Nick Gillesp | politics, libertarian, economics | News, Politics, reason, nick | Professional, Educational, Compelling | Educational, Professional, Wellness-Focused | interview | interview | True | False |
| Pappy's Flatshare | comedy, panel show, sketch | Pappys, Flatshare, Slamdown, Live | Humorous, Casual, Energetic | Educational, Humorous, Personal Narrative | panel | interview | True | False |
| Tony Evans' Sermons - Audio | christianity, sermons, faith | Religion & Spirituality, Christianity, kingdom, becoming | Inspirational, Educational, Uplifting | Educational, Inspirational, Uplifting | solo_monologue | educational_lecture | False | False |
| Open Science Stories | open science, science communication, research | Science, open, stories, story | Educational, Personal Narrative, Inspirational | Educational, Personal Narrative, Compelling | interview | narrative_storytelling | True | False |
| LSE: Public lectures and events | social science, public lectures, economics | Social Science, Education, Higher Education, public | Educational, Professional, Reflective | Educational, Uplifting, Professional | educational_lecture | educational_lecture | True | False |
| The Ballad of Billy Balls | true crime, history, mystery | Society & Culture, History, ballad, billy | Compelling, Personal Narrative, Reflective | Compelling, Educational, Personal Narrative | narrative_storytelling | narrative_storytelling | False | False |
| TREKS in SCI-FI | star trek, science fiction, entertainment | TV & Film, Sci-Fi, Star Trek, Star Wars | Casual, Energetic, Humorous | Uplifting | solo_monologue | solo_monologue | False | False |
| Murder Book | true crime, serial killer, investigation | True Crime, Society & Culture, killer | Compelling, Professional, Reflective | Personal Narrative, Compelling, Casual | narrative_storytelling | interview | False | False |
| Zencast | buddhism, meditation, dharma | Zen, Buddhism, Buddhist, Buddha | Reflective, Relaxed, Wellness-Focused | Educational, Inspirational, Wellness-Focused | educational_lecture | solo_monologue | True | False |
| StickyMinds - Software testing and sof | software testing, quality, conferences | better, software, stickyminds, testing | Professional, Educational, Casual | Educational, Professional, Inspirational | educational_lecture | interview | True | True |
| The Scamcast with Kitboga | scams, improv comedy, fraud | improv, scambait, prank calls, true crime | Humorous, Compelling, Energetic | Professional, Humorous, Educational | solo_monologue | educational_lecture | False | False |
| Common Sense with Dan Carlin | politics, current events, history | libertarian, independent, constitution, freedom | Compelling, Reflective, Educational | Educational, Personal Narrative | solo_monologue | educational_lecture | False | False |
| Skepticality - The Official Podcast of | skepticism, science, critical thinking | medicine, Medicine, kinesiology, Aspartame | Educational, Humorous, Compelling | Educational, Inspirational, Compelling | co_hosted_banter | interview | True | False |
| I Should Be Meditating with Alan Klima | meditation, mindfulness, stress | meditation, mindfulness, Buddhist, Eckhart | Relaxed, Wellness-Focused, Reflective | Educational, Wellness-Focused, Energetic | solo_monologue | educational_lecture | False | False |
| The School of Greatness | success, interviews, mindset | mental health, celebrity, inspiration, education | Inspirational, Uplifting, Personal Narrative | Educational, Inspirational, Personal Narrative | interview | educational_lecture | True | False |
| SourceTrunk | open source, software, linux | software, linux, source, open | Educational, Casual, Professional | Compelling, Educational | co_hosted_banter | solo_monologue | False | False |
| Surprisingly Free | technology policy, entrepreneurship, interviews | technology, policy, public, politics | Professional, Educational, Inspirational | Inspirational, Personal Narrative, Professional | interview | educational_lecture | True | False |
| Hanselminutes with Scott Hanselman | software development, technology, ai | technology talk inclusion web open source diversity discussi, Technology, Science, Education | Educational, Professional, Casual | Educational, Professional, Energetic | interview | interview | True | True |
| The Sound of Economics | economics, policy, europe | Business, Business News, Government, News | Professional, Educational, Reflective | Educational, Energetic, Inspirational | interview | educational_lecture | True | False |
| The Kasper Hauser Comedy Podcast | sketch comedy, parody, humor | Comedy, Arts, Performing Arts, news | Humorous, Compelling, Casual | Humorous, Compelling, Uplifting | mixed | solo_monologue | False | False |

</details>

## 2. Dedupe precision (constructed duplicates)

21 synthetic feeds (14 true shows -> 15 predicted shows); 210 feed pairs. **Precision 1.000** (FP=0), **recall 0.889** (FN=1).
Scenarios: tracking params, trailing slash, same `podcast:guid`, mirror/feedburner copy, 80% episode overlap, moved feed (`itunes:new-feed-url`); negatives: identical guid strings but different title, homonyms with disjoint episodes, same title in another language, near-identical titles, 30% overlap.
Misses: ["HARD: migrated host, all new episode guids, no podcast:guid [/hard1/b.xml]"]  (deliberately hard: host migration with all-new episode guids and no `podcast:guid`).
_synthetic duplicates/look-alikes built by us; includes 1 deliberately hard case (all-new episode guids) we expect to miss_

On the **real** seed run: 0 automatic merge(s) happened. None, so there is no real-world precision signal beyond the constructed set.

## 3. Similarity sanity: top-5 neighbours for 10 shows (you judge)


**Surprisingly Free**  _Broadband, Copyright, DMCA, Regulation, net, neutrality, policy, politics, public, technology_
- content: Podnutz Pro (0.89) · The Disciplined Investor (0.89) · Hanselminutes with Scott Hanselman (0.88) · The Reason Interview With Nick Gil (0.88) · Internet Marketing: Insider Tips a (0.88)
- style: The School of Greatness (0.98) · Skepticality - The Official Podcas (0.97) · Tony Evans' Sermons - Audio (0.97) · The Ballad of Billy Balls (0.96) · Go Guru (0.96)

**Common Sense with Dan Carlin**  _News, carlin, constitution, dan, freedom, independent, libertarian, nonpartisan, politics, rights_
- content: The Reason Interview With Nick Gil (0.86) · LewRockwell (0.85) · Adam Carolla Show (0.85) · ShopTalk (0.85) · The School of Greatness (0.85)
- style: This Week in Photo (0.97) · Sermons at St. Nicholas (0.96) · Embrace Running Podcast (0.96) · LewRockwell (0.96) · FLOSS Weekly (Audio) (0.96)

**Nora En Pure - Purified Radio**  _Music_
- content: MUBI Podcast (0.85) · Monday Morning Podcast (0.85) · Ben Greenfield Life – Health, Diet (0.85) · Philosophy For Our Times (0.85) · Jordan, Jesse, GO! (0.84)
- style: RatholeRadio.org (Ogg Version) (0.98) · Just So Stories (version 4) by Rud (0.97) · TREKS in SCI-FI (0.96) · Daily Boost Motivation and Coachin (0.96) · This Week in Science – The Kickass (0.96)

**LSE: Public lectures and events**  _Education, Higher Education, Social Science_
- content: The Sound of Economics (0.88) · The Reason Interview With Nick Gil (0.87) · Surprisingly Free (0.87) · Philosophy For Our Times (0.87) · The Disciplined Investor (0.87)
- style: ShopTalk (0.98) · Geek News Central Podcast (0.98) · Software Engineering Radio - The P (0.98) · Software Engineering Radio (0.98) · The Sound of Economics (0.97)

**The Reason Interview With Nick Gillespie**  _News, Politics_
- content: Philosophy For Our Times (0.89) · Singularity Weblog (0.88) · Internet Marketing: Insider Tips a (0.88) · The School of Greatness (0.88) · LewRockwell (0.88)
- style: StickyMinds - Software testing and (0.98) · The Paleo Diet – Robb Wolf on Pale (0.98) · Tony Evans' Sermons - Audio (0.97) · Ben Greenfield Life – Health, Diet (0.97) · Go Guru (0.97)

**Programming Throwdown**  _C, Education, How To, Java, News, Objective C, Programming Languages, Programming Throwdown, Python, Tech News_
- content: Geek News Central Podcast (0.88) · TWiT News (Video) (0.88) · Mike Tech Show Podcast (0.88) · ShopTalk (0.88) · Podnutz Pro (0.88)
- style: Ben Greenfield Life – Health, Diet (0.97) · The Changelog: Software Developmen (0.97) · Richard Herring's Edinburgh Fringe (0.97) · Podnutz – The Computer Repair Podc (0.97) · FLOSS Weekly (Video) (0.97)

**Just So Stories (version 4) by Rudyard Kipling (1865 - 1936)**  _Arts, Literature_
- content: Rationality: From AI to Zombies (0.85) · Comments on: (0.84) · MUBI Podcast (0.84) · The School of Greatness (0.84) · Numenera: The Signal Podcast (0.84)
- style: TREKS in SCI-FI (0.98) · Nora En Pure - Purified Radio (0.97) · RatholeRadio.org (Ogg Version) (0.97) · Mike Tech Show Podcast (0.96) · Rationality: From AI to Zombies (0.96)

**Skepticality - The Official Podcast of Skeptic Magazine**  _Aspartame, Cold, Committee, James, Medicine, Randi, for, kinesiology, medicine, reading_
- content: The School of Greatness (0.88) · Daily Boost Motivation and Coachin (0.87) · The Disciplined Investor (0.87) · Rationality: From AI to Zombies (0.87) · The Reason Interview With Nick Gil (0.87)
- style: The Ballad of Billy Balls (0.98) · Raising Saints (0.98) · Tony Evans' Sermons - Audio (0.97) · The School of Greatness (0.97) · Surprisingly Free (0.97)

**Catholic:Under The Hood**  _Bible, Catholic, Catholicism, Church, Franciscan, History, Pope, Priest, Religion, Theology_
- content: ShopTalk (0.87) · Philosophy For Our Times (0.87) · Sermons at St. Nicholas (0.86) · Grace to You: Radio Podcast (0.86) · 5 Minutes in Church History with S (0.86)
- style: Nordic True Crime (0.97) · The Who, What, Why? Game Design Po (0.97) · Skepticality - The Official Podcas (0.97) · The Ballad of Billy Balls (0.96) · The Kasper Hauser Comedy Podcast (0.96)

**Tony Evans' Sermons - Audio**  _Christianity, Religion & Spirituality_
- content: Line by Line with Albert Mohler (0.87) · Key Life with Steve Brown (0.87) · Sermons at St. Nicholas (0.86) · Raising Saints (0.86) · Vimeo / Kairos Sermons (0.86)
- style: I Should Be Meditating with Alan K (0.98) · The School of Greatness (0.97) · Skepticality - The Official Podcas (0.97) · This Week in Science – The Kickass (0.97) · Go Guru (0.97)

Proxy: 8/50 content-space neighbours share at least one declared category with the query show (16%).

## 4. Real ingestion: coverage, cost, cache, time

Shows in store: **102**.


**Coverage matrix: connector `rss`** (99 of 102 shows fetched OK). Share of fetched shows where the field was present:

| Field | Present | % |
|---|---|---|
| title | 98 | 99% |
| description | 97 | 98% |
| language | 96 | 97% |
| link | 97 | 98% |
| image | 94 | 95% |
| author | 87 | 88% |
| categories | 86 | 87% |
| explicit | 9 | 9% |
| podcast_guid | 14 | 14% |
| new_feed_url | 14 | 14% |
| episodes | 95 | 96% |
| episode_dates | 94 | 95% |
| episode_durations | 67 | 68% |
| episode_descriptions | 94 | 95% |
| transcripts | 9 | 9% |
| persons | 7 | 7% |

Connectors not listed (Podcast Index, Taddy) were **not run**: no keys in this environment.


**Seed run:** 279 feeds attempted, 91 ok, 188 failed; wall time 581.7 s (6 parallel workers, includes embedding on GPU).
Ingestion time per show (end-to-end, ok shows): mean 5.41 s, median 2.81 s, p95 25.19 s, max 33.02 s.
Failure causes: RuntimeError:ConnectTimeout x62, RuntimeError:ReadTimeout x52, RuntimeError:RuntimeError x38, RuntimeError:ValueError x17, RuntimeError:ConnectError x11, RuntimeError:RemoteProtocolError x5.

**Cache-hit measurement:** re-ingested 30/30 already-ingested shows with a forced re-fetch (180 s). Enrichment (LLM-call) cache hits: 30/30 = 100%; embedding cache hits: 130/130 = 100%. Misses are shows whose feed text changed between the seed run and now (new episode) and are re-processed by design.

**Cost ledger** (all numbers are *estimates*; the mock LLM and local embeddings have no API cost, GPU time is priced at the configured $/GPU-second):

- total estimated spend: $0.005022; shows costed: 102; **avg $4.9e-05 / show, p95 $0.000169 / show**
- overall enrichment/embedding cache-hit rate in ledger: 0.467
- rss_fetch: 159 ledger rows, 1 cache hits, 0 skipped, $0.0
- llm_extract: 269 ledger rows, 63 cache hits, 0 skipped, $0.0
- embed: 1072 ledger rows, 563 cache hits, 0 skipped, $0.005022
- transcript_fetch: 38 ledger rows, 0 cache hits, 0 skipped, $0.0

**Projection if a real LLM were used** (gpt-4o-mini-class list prices, input ~1.5k tokens + output ~400 tokens per show): roughly $0.0005 per show, i.e. about $0.15 for 300 shows; unchanged shows cost $0 thereafter because of the content-hash cache. This is arithmetic, not a measurement.
