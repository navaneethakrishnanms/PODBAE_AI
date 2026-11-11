# PodBae × BIT — Complete Project Plan

**AI-Powered Podcast Growth & Monetization Platform**
Version 1.0 · 4 November 2026 · Prepared for the BIT student engineering team

---

## Table of Contents

1. [Project Summary](#1-project-summary)
2. [Company & Market Analysis](#2-company--market-analysis)
3. [What the Existing MVP Does](#3-what-the-existing-mvp-does)
4. [Official Requirements (PodBae × BIT PDF)](#4-official-requirements-podbae--bit-pdf)
5. [Guiding Principles](#5-guiding-principles)
6. [Development Strategy](#6-development-strategy)
7. [Overall Architecture](#7-overall-architecture)
8. [The Trust Spine](#8-the-trust-spine)
9. [Layer 1 — Podcast Intelligence](#9-layer-1--podcast-intelligence)
10. [Layer 2 — Sponsor Intelligence](#10-layer-2--sponsor-intelligence)
11. [Layer 3 — Venue & Partnership Intelligence](#11-layer-3--venue--partnership-intelligence)
12. [Layer 4 — Opportunity Engine (Vibe Logic™)](#12-layer-4--opportunity-engine-vibe-logic)
13. [Layer 5 — Bae Agent & Opportunity Execution](#13-layer-5--bae-agent--opportunity-execution)
14. [Layer 6 — Outcomes, Learning & Economics](#14-layer-6--outcomes-learning--economics)
15. [Predictive Intelligence — Honest Progression](#15-predictive-intelligence--honest-progression)
16. [Models & Technology Choices](#16-models--technology-choices)
17. [Data Model](#17-data-model)
18. [API Contract & Integration](#18-api-contract--integration)
19. [End-to-End Flows](#19-end-to-end-flows)
20. [Business Strategy & Monetization](#20-business-strategy--monetization)
21. [Unit Economics & Cost Control](#21-unit-economics--cost-control)
22. [KPIs & Evaluation Framework](#22-kpis--evaluation-framework)
23. [Failure Scenarios & Required Handling](#23-failure-scenarios--required-handling)
24. [Security, Privacy & Compliance](#24-security-privacy--compliance)
25. [Six-Month Roadmap](#25-six-month-roadmap)
26. [Team Responsibilities](#26-team-responsibilities)
27. [Acceptance Criteria](#27-acceptance-criteria)
28. [Questions for the Founder & CTO](#28-questions-for-the-founder--cto)
29. [Appendix A — Build Prompts](#appendix-a--build-prompts)
30. [Appendix B — Design Tokens of the Live Site](#appendix-b--design-tokens-of-the-live-site)
31. [Appendix C — Sources](#appendix-c--sources)

---

## 1. Project Summary

PodBae is building predictive revenue infrastructure for independent podcasters. Over six months (Nov 2026 → Mar/Apr 2027), the BIT team will turn PodBae's MVP into a functional AI-powered growth and monetization agent ("Bae") that:

- **Observes** podcast, sponsor and venue signals
- **Analyzes** fit, vibe, values, audience and geography
- **Predicts** which opportunities are worth pursuing now
- **Recommends** them with evidence ("why this, why now")
- **Acts** — helps the creator save, pitch, follow up and track outcomes

**The target experience:** instead of the creator asking *"Who should I contact?"*, Bae says *"I found an opportunity that fits your show. Here's why, here's the supporting evidence, and here's what I recommend you do next."*

**Our approach:** build a faithful localhost replica of the MVP first (done), then build the AI layer as a separate, portable service — one intelligence layer at a time — so it can later plug into PodBae's real backend with minimal change.

---

## 2. Company & Market Analysis

### 2.1 Company

| Item | Detail |
|---|---|
| Product | PodBae — "AI Podcast Matchmaking", tagline *Connecting Podcasters, One Match at a Time™* |
| Entity | FM Digital LLC and PodBae Incorporated (Atlanta, GA) |
| Founder & CEO | 15+ years in digital/audio/music marketing and brand partnerships; MBA |
| CTO | Android and full-stack developer |
| Stage | Pre-launch (site says "Launching May 2027"); waitlist; paid tiers "Coming Soon" |
| Positioning | SaaS platform with a marketplace layer, powered by proprietary **Vibe Logic™**, connecting micro-podcasters with micro-brands, sponsors, venues and collaborators — alignment over volume |

### 2.2 User types (multi-sided)

Podcaster · Advertiser · Venue · Guest (+ creative collaborators, professional advocates)

### 2.3 Match types offered

| Match type | Description |
|---|---|
| Podcast Partners | Cross-promos, guest swaps, feed drops |
| Brand Sponsors | Companies seeking authentic creator partnerships |
| Expert Guests | Industry experts aligned with topics |
| Event Partners | Venues, local businesses (NYC, ATL, LA) |
| Creative Collaborators | Engineers, musicians, producers, writers |
| Professional Advocates | Marketers, financial advisors, merchandisers |

### 2.4 Revenue model

| Stream | Evidence | Type |
|---|---|---|
| Creator subscriptions (primary) | Flirt free → Date $19–24/mo → Commit $29–34/mo | Freemium SaaS |
| Ads on free tiers | Flirt and Date marked "Ads enabled" | Advertising |
| Advertiser campaigns | "Campaigns can start at $150" | Marketplace (fee structure unconfirmed) |
| Premium Partnership | Concierge: account manager, custom strategy, ad-buying | Services / retainer |

Note: the live site has pricing inconsistencies (card vs FAQ), placeholder-looking testimonials, broken footer links (About / Privacy / Terms → `#`), and unverified headline stats (1000+ matches, $67,000, 96%).

### 2.5 What customers actually need

Independent-podcaster surveys (Alitu 2025, RSS.com 2026):

- **72%** cite audience growth / discoverability as a core challenge
- **39%** cite making money; only **7%** cite finding guests
- **85%** of indie podcasts earn no money; only ~39% of active creators monetize
- Indies earn mostly by selling their own services/products, not ads

**Implications:**
1. Cross-promo / podcast-partner matching addresses the #1 pain (growth) → hero feature.
2. Sponsor matching for small shows is the money hook — local businesses, affiliate-style and host-read deals fit small audiences better than CPM ads.
3. Guest matching is the least painful and most crowded problem.
4. Many users are hobbyists → the product must visibly produce growth or money to retain paid users.

### 2.6 Competitive landscape

| Need | Existing players | Note |
|---|---|---|
| Guest ↔ host matching | PodMatch, Talks.co, Matchmaker.fm, PodcastGuests | PodMatch from $6/mo hosts, $32/mo guests; 25k+ users |
| AI pitching / outreach | PodPitch, CastFox | Pricing demo-gated |
| Podcast data, sponsors, cross-promo research | Rephonic, Podchaser Pro | Rephonic from $99/mo; API $299/mo (10k req) incl. sponsors/promotions endpoint |
| Sponsorship marketplaces | Podcorn, Gumball, AdvertiseCast, Podbean Ads | Podcorn 10% fee, no download minimum |
| Venue / live-event matching | **No dedicated player found** | Whitespace |

**Defensible differentiation for PodBae:**
1. Evidence-backed, proactive opportunities (not a searchable database)
2. Vibe Logic — fit beyond keywords
3. Small-creator monetization focus
4. Local venue and business partnerships
5. Execution and outcome tracking
6. **Long-term moat: accumulated relationship and outcome data**

---

## 3. What the Existing MVP Does

No public GitHub repo exists (PodBae and CTO accounts have no public repos). The MVP runs on **Replit**. Its architecture was mapped from the live site's public frontend and public endpoints.

### 3.1 Stack

React · wouter · TanStack Query · Radix/shadcn · Zod · Drizzle · Vite · Express (`/api/*`) · Postgres · **Lemon Squeezy** checkout (not Stripe, despite the PDF) · **CometChat** messaging · **Taddy** podcast import · RSS ingestion · Google Analytics/Ads.

### 3.2 AI pipeline skeleton already present

| Stage | Existing endpoints / fields |
|---|---|
| Observe | `/api/agent/ingest-rss`, `/api/admin/taddy-import/*`, `/api/enrich-directory` |
| Analyze | Podcasts carry LLM-style `vibeTags`, `toneTags`, `collaborationType`, AI summary + audience description |
| Score | `genreScore`, `locationScore`, `toneScore`, `keywordScore`, `vibeScore`, `performanceScore`, `listenScore`, `vibeWeight` → `totalScore` / `matchScore` |
| Predict | `/api/predictions` (with `status`), `/api/admin/generate-opportunities`, `/api/admin/vibe-logic-metrics`, `/vibe-logic-recommendations` |
| Recommend | `/api/member/matches`, `/insights`, `/reach-estimate`, `/api/listener-recommendations` |
| Agent | "Hey Bae": `/api/hey-bae/chat` with member's episodes as context |
| Act | `/api/member/swipe` (mutual match), save/unsave, partnership invites, chat, `/api/campaigns`, venue/guest submissions |

Public directory vocabulary: 4 categories, 12 vibe tags (Casual, Compelling, Educational, Energetic, Humorous, Inspirational, Personal Narrative, Professional, Reflective, Relaxed, Uplifting, Wellness-Focused).

### 3.3 Gap analysis

| PDF requirement | Current state |
|---|---|
| Podcast intelligence | RSS + Taddy import, tag-level enrichment only |
| Sponsor intelligence + verified contacts | Submission forms only |
| Venue intelligence by listener geography | Submission forms only |
| Deterministic Opportunity Engine | Hand-weighted tag-overlap sum |
| Explain "why / why now" | Not present |
| Agent that acts | Chat box, no tools |
| Act workflows + outcome tracking | Swipe/save/chat; no pipeline or outcomes |
| Reliable onboarding → payment → discovery | Waitlist only; plan names inconsistent |

**Conclusion:** the Observe → Analyze → Predict → Recommend → Act skeleton exists. The intelligence inside each step is what we build.

---

## 4. Official Requirements (PodBae × BIT PDF)

- Duration ~6 months (Sep 2026 – Mar/Apr 2027); initial team 2–3 students; collaboration with Founder, CTO, Faculty SPOC
- First 2–3 weeks: research, discovery, codebase evaluation, architecture recommendation
- Three intelligence layers: **Podcast**, **Sponsor**, **Venue & Partnership**
- Deterministic **PodBae Opportunity Engine** using **Vibe Logic™**
- Bae as orchestration layer that explains and helps act
- Proactive recommendations of partners, guests, sponsors, venues, growth opportunities
- Explain why an opportunity fits and why it matters now
- Verified professional contacts where appropriate
- Action workflows: save, draft outreach, contact, track outcomes
- Improve website and customer journey: onboarding → payment → discovery → continued use
- **Verified data and deterministic workflows over AI hallucination**
- Platform engineering: Replit → Git/GitHub migration, auth, payments, API security, secrets, testing
- Tech named: Python, TypeScript, React, Node/Express, PostgreSQL, Drizzle, OpenAI APIs/embeddings, NLP, semantic search, ranking, Rephonic API, Taddy API

---

## 5. Guiding Principles

### Three non-negotiable principles

1. **Trust before intelligence.** If the system cannot verify an opportunity, it says so clearly. No fabricated brands, contacts, sponsorships or audience information.
2. **Business outcomes before AI complexity.** A simple recommendation that produces a genuine partnership beats an advanced system producing hundreds of irrelevant matches.
3. **Sustainable economics before scale.** Every recommendation, API call, LLM operation and enrichment has an understandable cost and business justification.

### Engineering rules

- **LLM at the edges, engine in the middle.** LLMs extract structure from text and turn results into language. Scoring and ranking are deterministic, versioned and testable.
- **Every fact has provenance:** source, data tier, timestamp, confidence.
- **Four separate measures on every opportunity — never merged:**

| Measure | Meaning |
|---|---|
| Fit (0–100) | How well the opportunity matches |
| Evidence confidence (High/Med/Low) | How reliable the underlying data is |
| Commercial readiness (Discovery lead / Potential lead / Verified) | How actionable it is |
| Conversion probability | Shown only once validated; otherwise "Not enough data yet" |

- **Never pad results.** If only one good match exists, show one and explain why.
- **Vibe Logic belongs to the founder.** We propose implementations; she approves the methodology.
- **Separate customer-facing truth labels:** Verified · Creator-provided · Estimated · AI-inferred.

---

## 6. Development Strategy

1. **Phase 0 — Local MVP replica (DONE).** A faithful localhost copy of PodBae's UI, routes and `/api/*` surface: React + Express + Drizzle + PGlite (embedded Postgres) + FastAPI in the `torch_gpu` conda env. Windows, no Docker, zero-key mock mode.
2. **AI layer as a separate, portable service** (`services/ai`, Python/FastAPI) that owns its own intelligence store and exposes a versioned HTTP contract. The Node app never touches its DB directly.
3. **Build one layer at a time**, each demoable, each with tests and a measured report.
4. **Integrate into PodBae's real backend** once repo access is granted — only the Express calls change.

---

## 7. Overall Architecture

```
                         ┌──────────────────────── EXTERNAL SOURCES ────────────────────────┐
                         │ RSS · Podcast Index · Taddy · Rephonic (if licensed) · Charts      │
                         │ Places API · Creator analytics uploads · In-app submissions        │
                         └───────────────┬──────────────────────────────────────────────────┘
                                         │ OBSERVE
 ┌──────────────────────────── services/ai (FastAPI · Python · torch_gpu) ────────────────────────────┐
 │                                                                                                     │
 │  ┌──────────────── TRUST SPINE (used by every layer) ─────────────────────────────────────────┐    │
 │  │ provenance · data tiers · freshness · evidence · cost ledger · budgets · jobs · audit ·      │    │
 │  │ untrusted-content guard                                                                      │    │
 │  └──────────────────────────────────────────────────────────────────────────────────────────────┘    │
 │                                                                                                     │
 │  LAYER 1  Podcast Intelligence   ingest → normalize/identity → rules + LLM extraction (tiered)      │
 │                                  → embeddings → profile with completeness                            │
 │  LAYER 2  Sponsor Intelligence   brand identity → ad-read classification → sponsorship events       │
 │                                  → lookalike sponsorship → contacts (tiered)                         │
 │  LAYER 3  Venue & Partnership    listener geo (tiered) → discovery leads vs verified partners       │
 │                                                                    │ ANALYZE                         │
 │  LAYER 4  Opportunity Engine     ELIGIBILITY → COMPATIBILITY (Vibe Logic) → COMMERCIAL READINESS    │
 │                                  → CONFIDENCE → RANK (diversity, freshness, cooldown, no-match)      │
 │                                  → why-now triggers → explanation (faithfulness-checked)            │
 │                                                                    │ PREDICT / RECOMMEND             │
 │  LAYER 5  Bae + Execution        controlled workflow agent with permissioned tools                  │
 │                                  Opportunity-to-Outcome pipeline                                    │
 │                                                                    │ ACT                             │
 │  LAYER 6  Outcomes & Economics   exposure + outcome logs, KPIs, cost per qualified opportunity,     │
 │                                  weight tuning → later learned ranking                               │
 │                                                                                                     │
 │  INTELLIGENCE STORE  SQLAlchemy + Alembic · SQLite + sqlite-vec (local) · Postgres + pgvector (prod) │
 └───────────────────────────────▲─────────────────────────────────────────────────┬──────────────────┘
                                 │ HTTP /v1 (versioned JSON contract)              │
                     ┌───────────┴─────────────────────────────────────────────────▼──────────┐
                     │ apps/api (Express) — local replica now, PodBae's Replit backend later    │
                     │ owns: auth, users, tiers, payments, chat, UI data                         │
                     └───────────────────────────▲─────────────────────────────────────────────┘
                                                 │
                                     apps/web (React) — same UI as podbae.love
```

### 7.1 Data ownership

| Owner | Data |
|---|---|
| Express app DB | Users, sessions, tiers, payments, chat, swipes, UI state |
| AI intelligence store | Shows, episodes, profiles, provenance, evidence, brands, sponsorship events, venues, opportunities, features, embeddings, cost ledger, jobs |
| Shared via API only | Opportunity results, profiles, outcome events |

### 7.2 Why a separate intelligence store

PGlite runs inside Node, so Python cannot connect to it. The AI service owns its own store via SQLAlchemy with a configurable URL: SQLite + sqlite-vec locally (no install), Postgres + pgvector in production — same code. This also cleanly answers data ownership.

---

## 8. The Trust Spine

Built first. Every layer depends on it.

### 8.1 Data tiers

| Tier | Meaning | Example |
|---|---|---|
| **Verified** | Trusted measurement or opted-in confirmation | Brand registered on PodBae; venue confirmed availability |
| **Creator-provided** | Supplied by the creator (validated, labelled) | Uploaded Spotify/Apple analytics export |
| **Estimated** | Third-party modelled data | Rephonic listener estimates/demographics |
| **Inferred** | AI interpretation of content | Vibe scores, topics, likely-audience description |

Display priority: verified > creator-provided > estimated > inferred, then freshness. Conflicts are kept and flagged, never silently resolved.

### 8.2 Components

| Component | Purpose |
|---|---|
| `provenance` | Field-level value + source + tier + method + model version + fetched_at + expires_at + confidence |
| `evidence` | Snippets (≤300 chars) with locator (episode, timestamp, URL) supporting claims |
| Freshness policy | Per-field expiry (e.g. episodes 24h, profile 7d, sponsorship 90d); stale values flagged and refreshed |
| `cost_ledger` | Every external/LLM/GPU operation with estimated cost and cache-hit flag |
| `budgets` | Global / per-podcast / per-user / per-tier limits; checked before every paid call |
| `jobs` | Idempotency key, retries with backoff, max attempts, failure reasons, resumable |
| `audit_log` | All writes and agent actions |
| Untrusted-content guard | Sanitize external text; pass to LLMs only as delimited data; injection tests |

---

## 9. Layer 1 — Podcast Intelligence

**Business milestone:** a creator connects a podcast and receives a useful, honest intelligence profile.

### 9.1 Ingestion

| Source | Use | Cost |
|---|---|---|
| RSS (feedparser + httpx) | Metadata, episodes, `<podcast:transcript>`, `<podcast:person>`, iTunes tags; conditional GET; incremental | Free |
| Podcast Index | Canonical IDs, dedupe, discovery | Free key |
| Taddy (feature flag) | Episodes, transcripts, webhooks | Free tier → $75–150/mo |
| Creator upload | Verified audience analytics (CSV) | Free |

Each connector reports **which fields it actually returned** → measured data-feasibility matrix at `/v1/admin/coverage`.

### 9.2 Normalization & identity

- Canonical show identity with aliases: RSS URLs, Podcast Index ID, iTunes ID, `podcast:guid`
- Handle changed RSS URLs (`itunes:new-feed-url`, redirects), renamed shows, duplicate feeds
- Deleted episodes marked removed, not hard-deleted
- Language detection per show and episode
- Activity status: active / slowing / inactive
- Large feeds: store latest ~200 episodes' metadata, deeply process latest ~20

### 9.3 Content understanding

**Rules first:** cadence, average length, episode count, explicit flag, categories, last published, guest-format hints.

**LLM extraction (small model, strict JSON schema, tier = inferred):**

```json
{
  "topics": [{"name": "local history", "weight": 0.6}],
  "vibe": {"Humorous": 0.8, "Reflective": 0.3, "...": 0.0},
  "tone": ["conversational", "storytelling"],
  "conversational_style": "co-host banter | interview | solo | panel | narrative",
  "values": ["community", "entrepreneurship"],
  "guest_friendly": true,
  "brand_safety_flags": [],
  "likely_audience_description": "…",
  "evidence": [{"field": "topics", "episode_id": "…", "snippet": "…"}]
}
```

**Hard rule:** the LLM may never set age, gender, income, city or listener counts — enforced by schema.

- Cache by content hash + prompt version + model version
- Invalid JSON → bounded retries → rules-only fallback with low confidence
- Transcripts: use provided ones; faster-whisper is optional, budgeted, off by default, creator's own show only (latest 3 episodes, opt-in)
- Transcript quality check lowers confidence when poor

### 9.4 Embeddings (local GPU)

Small multilingual BGE/E5-class sentence-transformer. Separate vectors: **content**, **style**, **episode chunks**. Model name/version stored; re-embed on change. `GET /v1/shows/{id}/similar?space=content|style`.

### 9.5 Profile output

Per field: value, tier, source, timestamp, freshness, confidence, evidence. Plus completeness score and "what would improve this profile" list. New shows get a **preliminary** profile.

---

## 10. Layer 2 — Sponsor Intelligence

**Business milestone:** creators see real, evidence-backed sponsor leads — never invented ones.

### 10.1 Brand identity resolution

Canonical brand entity with domains, aliases, parent/subsidiary relations, acquisition handling, active/inactive status, fake-domain checks.

### 10.2 Sponsorship evidence classification

| Class | Treatment |
|---|---|
| Confirmed sponsorship | Counts as sponsorship history |
| Confirmed affiliate | Separate affiliate evidence |
| Promotional mention | No payment assumed |
| Organic mention | Not sponsorship evidence |
| Uncertain | Human review queue or excluded |

Detection pipeline: rules (ad-read phrases: "brought to you by", "use code", "promo code", "sponsored by", tracking URLs) → NER (GLiNER/spaCy) → small LLM classification → merge with Rephonic promotions data (if licensed) → `sponsorship_event(brand, show, episode, date, class, read_type, snippet, timestamp, source, method, verification_status)`.

### 10.3 Lookalike sponsorship (core idea)

Brands that already pay shows similar to yours:

```
lookalike_affinity(member, brand) = Σ_{s ∈ kNN(member)} sim(member, s) · 𝟙[brand sponsored s, confirmed, recent]
```

### 10.4 Contacts

| Contact status | Shown as |
|---|---|
| Brand registered on PodBae | Verified |
| Enrichment provider with verification result | Verified (with date) |
| Official partnerships page only | "Official channel" |
| Unknown | "Contact not verified" — no invented emails |

Re-verify before any outreach. Respect opt-outs.

### 10.5 Freshness

Sponsorship recency weighting, brand activity checks, stale-lead expiry, revalidation before outreach.

---

## 11. Layer 3 — Venue & Partnership Intelligence

**Business milestone:** creators discover realistic live-event markets and local partners — with honest status labels.

### 11.1 Two opportunity types (displayed differently)

| Type | Meaning |
|---|---|
| **Discovery lead** | A potentially suitable business from a Places provider — availability, pricing and willingness unknown |
| **Verified partnership** | Venue registered on PodBae or explicitly confirmed interest |

Never claim availability, capacity or pricing from a business listing.

### 11.2 Signals

- Listener concentration by city (verified creator data → estimated → none; labelled)
- Venue type (bar, café, theatre, studio), location, category fit
- Capacity / recording facilities / pricing only when verified
- Similar shows nearby (co-hosted live shows)
- Local business fit for sponsorship (geo-targeted brands)

### 11.3 Fields typically missing from Places APIs

Event hosting, recording facilities, external booking, availability, partnership openness, pricing → acquire through venue submissions and direct confirmation.

---

## 12. Layer 4 — Opportunity Engine (Vibe Logic™)

### 12.1 Pipeline

```
member show + creator preferences
   │
   ├─► A. CANDIDATE GENERATION   vector search + rules → ~200 candidates per type
   ├─► B. ELIGIBILITY (hard gates — before any scoring)
   │      blocked categories/brands · competitor conflicts · inactive entity · already partnered
   │      · already contacted · dismissed (cooldown) · missing consent · insufficient evidence
   │      · brand-safety violation · language mismatch
   ├─► C. COMPATIBILITY (Vibe Logic, founder-approved factors) → Fit 0–100
   ├─► D. COMMERCIAL READINESS → Discovery / Potential / Verified
   ├─► E. CONFIDENCE → completeness · source reliability · freshness · verification · agreement
   ├─► F. WHY-NOW TRIGGERS → only from real time-stamped signals
   ├─► G. RANK → relevance · diversity (MMR) · freshness · personalization · seen-suppression
   └─► H. OUTPUT → Opportunity{fit, breakdown, confidence, readiness, conversion:"n/a",
                              evidence[], why_now, scoring_version}
          or a NO-MATCH / FEWER-THAN-3 state with explanation and "expand search" option
```

### 12.2 Starting compatibility factors (to be validated with the founder)

**Podcast partner (cross-promo):**

| Factor | Computation | Draft weight |
|---|---|---|
| Audience similarity | cosine(content/audience vectors) + verified geo overlap | 0.25 |
| Vibe compatibility | cosine(vibe vectors) + tone overlap | 0.20 |
| Content complementarity | peaks at medium content similarity (not a clone) | 0.10 |
| Size parity | 1 − \|log Lₐ − log L_b\| / k (when sizes known) | 0.15 |
| Activity | both recently active, comparable cadence | 0.10 |
| Geo overlap | shared listener cities | 0.10 |
| Collaboration openness | opted in / guest-friendly / past swaps | 0.10 |

**Sponsor:** lookalike affinity 0.35 · momentum 0.15 · size fit 0.15 · category/values fit 0.15 · geo fit 0.10 · format fit (host-read share) 0.10.

**Venue:** listener concentration · venue fit · partner density · verification status.

**Guest:** topic match × appearances on similar shows × recency × on-platform opt-in.

### 12.3 Scoring rules

- Each factor normalized to [0,1]; stores inputs and sources
- **Missing-data policy:** a missing factor is excluded and weights renormalized, and confidence drops — never imputed silently
- Weights live in versioned YAML; every opportunity stores `scoring_version` and a feature snapshot
- Deterministic: same inputs + same version → same output (unit-tested)
- Contradictory evidence → flagged, confidence reduced

### 12.4 Why-now triggers (examples)

- Brand sponsored N similar shows in the last 30 days
- Brand's activity in your category increased this quarter
- Similar show recently opened to cross-promos / published on your topic
- Listener growth in a city (verified data only)
- Saved opportunity has new evidence

### 12.5 Explanation pipeline

1. **Deterministic skeleton:** top 3 contributing factors + trigger + evidence IDs
2. **LLM phrasing:** small model writes 2–3 friendly sentences from the skeleton only
3. **Faithfulness check:** every entity/number must exist in the skeleton → else regenerate or fall back to template

### 12.6 Example card

| Field | Value |
|---|---|
| Opportunity | Sponsor lead — *[brand]* |
| Fit | 88 / 100 |
| Evidence confidence | High (3 confirmed sponsorships, last 60 days) |
| Commercial status | Potential lead — official partnerships page |
| Contact | Not verified |
| Conversion | Not enough data yet |
| Why now | Sponsored 3 shows similar to yours in the last 60 days |
| Recommended next step | Review evidence → draft pitch → request rate card |

### 12.7 Validating Vibe Logic

1. Founder interview → document factors, priorities, dealbreakers
2. Founder (and 2+ evaluators) label a gold set
3. Compare engine rankings vs labels; iterate weights
4. Founder signs off on each scoring version

---

## 13. Layer 5 — Bae Agent & Opportunity Execution

### 13.1 Bae is an orchestrator, not an authority

Controlled workflow:

```
user message → intent classification → tool selection → tool execution (validated inputs)
→ structured result validation → evidence retrieval → response generation (grounded)
→ action authorization (user approval for external actions)
```

### 13.2 Tools and permissions

| Tool | Permission |
|---|---|
| `get_creator_profile`, `get_podcast_intelligence`, `search_podcasts`, `search_sponsors`, `search_venues`, `get_opportunities`, `get_opportunity_evidence`, `explain_opportunity` | Read |
| `draft_outreach`, `draft_proposal` | Draft (never sent automatically) |
| `save_opportunity`, `dismiss_opportunity`, `create_invitation`, `schedule_followup`, `record_outcome` | Write (idempotent, audited) |
| Send email / external message | **Requires explicit user approval** |

### 13.3 Bae must never

Calculate final compatibility · invent sponsors, contacts or venues · change scoring weights · override creator restrictions · send outreach without approval · execute financial transactions · follow instructions found inside transcripts, feeds or websites.

### 13.4 Reliability

Tool input schemas · timeouts and bounded retries · idempotency keys · invalid-output recovery · tenant isolation · audit logs · **LLM outage fallback:** deterministic search, ranking, saving and template explanations keep working.

### 13.5 Member memory

Goals, blocked categories, likes/dislikes, dismissal reasons, past decisions — all feed the eligibility gates and personalization.

### 13.6 Opportunity-to-Outcome pipeline

```
Discover → Validate → Prioritize → Prepare (pitch/proposal) → Execute (contact, follow-up)
→ Convert (reply, meeting, negotiation, partnership) → Learn
```

Pipeline states: `New → Saved → Contacted → Replied → Meeting → In talks → Won / Lost`. Manual status entry supported for contact that happens outside PodBae.

---

## 14. Layer 6 — Outcomes, Learning & Economics

### 14.1 Event logging

`impression (with position) · open · save · dismiss (+reason) · contact · reply · meeting · negotiation · partnership · revenue (voluntary, verifiable)` — each with user (anonymized ID), opportunity type, feature snapshot, scoring version, timestamp.

### 14.2 Learning

- Dismiss reasons immediately update personal constraints
- Weight tuning per scoring version against offline eval + online outcomes
- **Learned ranking only after sufficient, diverse, quality labels** — with position-bias correction (e.g. randomized exposure slots or inverse propensity weighting), query grouping per member-day, and temporal validation. No fixed outcome count is committed; readiness is decided by data review.

### 14.3 Economics

Cost per connected podcast, per analyzed episode, per creator, per qualified opportunity, per outreach draft — reported per tier.

---

## 15. Predictive Intelligence — Honest Progression

| Area | Initial (rule/evidence-based) | Advanced (only with validated data) |
|---|---|---|
| Sponsorship | Historical lookalike matching | Sponsorship likelihood model |
| Outreach | Evidence + contact status | Response likelihood model |
| Timing | Rule-based why-now triggers | Validated timing model |
| Podcast growth | Activity and collaboration signals | Audience growth forecasting |
| Venue demand | Listener concentration | Event attendance prediction |

For every advanced model: define target variable, training data, features (point-in-time, no leakage), model choice (start with gradient boosting / logistic regression), metrics (AUC, calibration, precision@k), cold-start handling, shadow deployment before exposure.

**We never claim the platform predicts revenue until validated data supports it.**

---

## 16. Models & Technology Choices

| Job | Choice | Runs on | Rationale |
|---|---|---|---|
| Embeddings | Small multilingual BGE/E5-class (sentence-transformers) | Local GPU | Free, fast, controllable |
| Brand / guest NER | GLiNER or spaCy | Local GPU/CPU | Cheap, accurate entity extraction |
| Transcription fallback | faster-whisper | Local GPU | Optional, budgeted |
| Profile extraction, ad-read classification | Small LLM tier, JSON-schema output | API (mock locally) | High volume → low cost |
| Explanation phrasing | Small LLM tier + faithfulness check | API | Short outputs |
| Bae agent | Stronger LLM tier with tool calling | API | Reasoning quality |
| Ranking | Deterministic weighted scoring → later gradient-boosted ranking | CPU | Explainable, testable |
| Vector search | sqlite-vec (local) / pgvector HNSW (prod) | DB | Same interface |
| Jobs | In-process worker with DB-backed idempotent job table (local) → dedicated queue + workers (prod) | — | Portable |
| Provider abstraction | OpenAI / Anthropic / mock via config | — | No lock-in |

**Production notes:** in-process schedulers are prototype-only; production needs separate workers, retries, dead-letter handling, distributed scheduling, monitoring. Validate against real Postgres + pgvector before integration.

---

## 17. Data Model

### 17.1 Trust spine

```
sources(id, name, kind, terms_note)
provenance(id, entity_type, entity_id, field, value_json, source_id, source_ref, data_tier,
           method, model_version, fetched_at, expires_at, confidence, superseded_by)
evidence(id, entity_type, entity_id, kind, snippet, locator_json, source_id, created_at)
cost_ledger(id, ts, operation, provider, units, unit_cost_estimate, cost_estimate_usd,
            podcast_id, user_id, cache_hit)
budgets(scope, key, period, limit_usd, used_usd)
jobs(id, type, idempotency_key, status, attempts, max_attempts, last_error, payload, result, ts…)
audit_log(id, ts, actor, action, entity_type, entity_id, detail)
```

### 17.2 Intelligence entities

```
shows(id, canonical_name, language, activity_status, owner_user_id, created_at, updated_at)
show_identifiers(show_id, kind[rss|podcastindex|itunes|guid|taddy], value, is_current)
episodes(id, show_id, guid, title, description, published_at, duration_sec, audio_url,
         transcript_url, transcript_quality, removed_at)
episode_chunks(id, episode_id, text, start_ts, end_ts)
show_profiles(show_id, profile_json, completeness, preliminary, version)
embeddings(id, entity_type, entity_id, space, model, model_version, vector)
creator_preferences(user_id, show_id, goals, blocked_categories, blocked_brands, openness)
audience_data(show_id, field, value, data_tier, source_id, period)

brands(id, canonical_name, domains[], parent_brand_id, status, categories[])
sponsorship_events(id, brand_id, show_id, episode_id, class, read_type, ts_in_episode,
                   detected_at, method, verification_status, evidence_id)
contacts(id, brand_id|venue_id, role, channel, value, status, verified_at, source_id)

venues(id, name, city, type, address, verified, capacity, recording_facilities, source_id)
cities(id, name, region, country)

opportunities(id, member_show_id, type, target_entity, fit, breakdown_json, confidence,
              readiness, conversion_status, why_now, evidence_ids[], scoring_version,
              feature_snapshot_json, status, expires_at, created_at)
opportunity_events(id, opportunity_id, user_id, type, position, reason, ts)
```

---

## 18. API Contract & Integration

### 18.1 AI service endpoints (`/v1`)

```
# Layer 1
POST /v1/ingest/rss              {rss_url, user_id?} → job_id
POST /v1/ingest/discover         {query|category, limit} → job_id
GET  /v1/jobs/{id}
GET  /v1/shows                   ?q&category&language&activity
GET  /v1/shows/{id}/profile | /episodes | /similar?space=content|style
POST /v1/shows/{id}/refresh
POST /v1/shows/{id}/audience-upload
# Layer 2–3
GET  /v1/brands/{id} | /v1/brands/{id}/evidence
GET  /v1/venues?city&type
# Layer 4
POST /v1/opportunities/generate  {member_show_id, types[]}
GET  /v1/opportunities           ?member_show_id&type&limit
GET  /v1/opportunities/{id}/explain
# Layer 5
POST /v1/agent/chat              {member_id, message} → streamed reply + tool trace
POST /v1/agent/actions/{id}/approve
# Layer 6
POST /v1/events                  {user, opportunity, type, position?, reason?}
GET  /v1/metrics
# Admin
GET  /v1/admin/coverage | /costs | /jobs
GET  /v1/health
```

### 18.2 Express ↔ AI mapping

| Existing app endpoint | AI service call |
|---|---|
| `/api/agent/ingest-rss`, `/submit` flow | `/v1/ingest/rss` |
| `/api/public/directory`, `/discover` | `/v1/shows` |
| `/api/predictions`, `/api/member/matches` | `/v1/opportunities` |
| `/api/hey-bae/chat` | `/v1/agent/chat` |
| `/api/predictions/:id/action`, `/swipe`, `/save-match` | also `POST /v1/events` |
| `/api/admin/generate-opportunities` | `/v1/opportunities/generate` |
| `/api/admin/vibe-logic-metrics` | `/v1/metrics` |
| `/api/admin/taddy-import/*` | `/v1/ingest/*`, `/v1/jobs` |

Integration into PodBae's real backend = changing these calls only. If the AI service is down, the app shows cached results with a "may be outdated" banner.

---

## 19. End-to-End Flows

### 19.1 New creator onboarding

```
Sign up → paste RSS URL → /v1/ingest/rss (job) → normalize + identity → rules + LLM extraction
→ embeddings → preliminary profile (minutes) → creator sets goals + blocked categories
→ optional analytics upload (→ verified audience) → first opportunities generated
→ top opportunities shown with fit / confidence / status / evidence
```

### 19.2 Daily cycle

```
Nightly: refresh feeds (incremental) → re-extract changed content only (hash cache)
→ update sponsorship events → regenerate opportunities → apply eligibility, cooldowns, diversity
→ publish up to 3 (Flirt) / all (Commit) at peak times → no padding if fewer qualify
```

### 19.3 Retention cadence

| When | Experience |
|---|---|
| Onboarding | Profile + goals |
| Daily | Genuinely new, relevant opportunities |
| Weekly | Summary of new matches, activity, recommended actions |
| After outreach | Reply tracking, follow-up suggestions |
| Monthly | Partnership progress and growth insights |

Notifications fire only when real signals exist.

### 19.4 Act flow

```
Open opportunity → view evidence → Bae drafts pitch (grounded) → creator edits + approves
→ send (or mark sent manually) → follow-up reminder → record reply / meeting / outcome
→ outcome feeds Layer 6
```

### 19.5 Advertiser flow (P2)

```
Brand enters objective, category, audience, geo, topics, budget, dates, format
→ ranked creator candidates with fit + available analytics (tier-labelled)
→ proposed collaboration → campaign tracking → reported results where measurable
```

---

## 20. Business Strategy & Monetization

### 20.1 Five customer outcomes

| Outcome | Capability | Business value |
|---|---|---|
| Help creators grow | Podcast-partner / cross-promo recommendations | Acquisition and retention |
| Help creators earn | Evidence-backed sponsor leads + pitch support | Subscription retention, marketplace revenue |
| Help creators build relationships | Guests, collaborators, advocates | Engagement |
| Help creators go offline | Venue and local business partnerships | Differentiation |
| Help creators execute and measure | Opportunity pipeline and outcomes | Retention, ROI proof, data moat |

### 20.2 Value per customer type

| Customer | Pays for | Reason to stay |
|---|---|---|
| Creator | Subscription tiers | Opportunities that produce growth or money |
| Advertiser | Campaign fees | Trustworthy creator fit + reporting |
| Venue / local business | (TBD) | Event bookings, local audience |
| Guest / collaborator | (TBD, possibly guest tier) | Bookings, visibility |

### 20.3 Marketplace liquidity

Track: eligible opportunities per creator · eligible creators per advertiser · sponsor demand vs creator supply · time to first useful match · match acceptance · campaign completion. Recruit verified advertisers and venues alongside creators. Use the full ingested directory (not just members) to avoid cold-start emptiness, labelling non-members "not on PodBae yet — invite them".

### 20.4 Assumptions requiring validation

Creator willingness to pay at each tier · advertiser fee structure · venue participation · guest monetization · conversion of evidence-backed leads. **No market sizes, revenue projections or willingness-to-pay figures are claimed in this plan.**

---

## 21. Unit Economics & Cost Control

```
Contribution margin per creator = revenue per creator − variable cost per creator
```

| Cost driver | Control |
|---|---|
| Podcast data APIs | Shared show intelligence (one show analyzed once, used by everyone), quotas, caching |
| LLM extraction | Content-hash cache, small model tier, batch processing, re-run only on change |
| Transcription | Off by default, creator opt-in, latest 3 episodes only |
| Embeddings | Local GPU, no API cost |
| Contact enrichment | Only on demand when a creator acts, then cached |
| Agent conversations | Tier limits (Commit only), stronger model only for agent |
| Human verification | Review queue only for sponsor/venue leads above a fit threshold |

Tier budgets enforced through `budgets`; graceful degradation when exceeded. Report: cost per creator, per qualified opportunity, gross margin per tier. Provider prices quoted in this plan are from public pages at time of research and must be confirmed.

---

## 22. KPIs & Evaluation Framework

### 22.1 Business KPIs

| Group | Metrics |
|---|---|
| Acquisition | Registrations, podcast connections, onboarding completion |
| Activation | Time to first useful opportunity, first saved opportunity |
| Engagement | Weekly active creators, opportunity views, action rate |
| Monetization | Paid conversion, subscription revenue, advertiser revenue |
| Outcomes | Contacts, replies, meetings, partnerships, creator-reported revenue |
| Retention | 30 / 60 / 90-day creator retention |
| Trust | % opportunities with verified evidence, false-sponsor reports |
| Economics | Cost per qualified opportunity, gross margin per tier |

**North-star KPI: successful opportunities per active creator** — not number of matches.
Targets are agreed with the founder after a baseline is measured.

### 22.2 Offline evaluation

- Existing MVP tag-overlap scoring as **baseline**
- Founder-approved **gold set**, multiple evaluators, inter-rater agreement reported
- Precision@3 (primary), nDCG@10, Coverage@3, diversity, evidence coverage, freshness
- Extraction quality per field vs hand labels; sponsor-classification precision/recall; dedupe precision
- Explanation faithfulness = 100% required
- Agent: tool-call success, task completion, grounded-entity rate

### 22.3 Online evaluation

Save → contact → reply → partnership funnel per type and scoring version · A/B tests · position-bias controls · temporal validation · version tracking. Engagement alone is never treated as proof of business success.

---

## 23. Failure Scenarios & Required Handling

### 23.1 Podcast data

| Scenario | Handling |
|---|---|
| Invalid RSS URL | Validate, explain error |
| Feed offline | Serve cache with freshness warning |
| Malformed XML | Tolerant parsing, log |
| Duplicate feeds | Entity resolution |
| RSS URL changed / show renamed | Canonical identity with aliases |
| 10,000-episode feed | Incremental, bounded processing |
| No / poor transcripts | Metadata analysis, lower confidence |
| Multiple languages | Language detection, multilingual model |
| Deleted episodes | Mark removed |
| Podcast stopped publishing | Inactivity detection, exclude from partner recs |

### 23.2 Sponsor data

| Scenario | Handling |
|---|---|
| Organic brand mention | Classified, excluded from sponsorship history |
| Brand stopped advertising | Recency checks, expiry |
| Acquired brand / subsidiaries | Identity graph |
| Conflicting sources | Keep both, flag conflict |
| Fake company | Domain/identity verification |
| Contact left / unverifiable | Mark unverified, offer official channel, revalidate |
| No budget info | Never inferred; "budget unknown" |
| Competitor conflict / blocked category | Eligibility gate |
| Already contacted | Pipeline history suppression |

### 23.3 Recommendation engine

| Scenario | Handling |
|---|---|
| No good matches | No-match state + expand-search option |
| Fewer than three | Show the qualified ones, explain |
| Missing features | Missing-data policy, lower confidence |
| High similarity, poor audience fit | Separate content vs audience factors |
| Blocked category, fit 99 | Excluded before ranking |
| Repetition | Cooldowns, seen-suppression, rotation |
| All similar | Diversity constraints |
| Cold-start creator | Content + declared goals, "preliminary" label |
| Category change | Recompute profile and opportunities |
| Multiple podcasts per user | Show-level identity and goals |
| Weight change | Versioned scoring, snapshots |
| High confidence but stale | Confidence includes freshness |

### 23.4 Agent

Prompt injection → content treated as data · wrong tool → schema + intent validation · timeouts → retry policy · invalid JSON → bounded retries · invented entities → grounded-entity restriction · duplicate actions → idempotency · unauthorized sends → approval gate · data leakage → tenant isolation · LLM outage → deterministic fallback.

### 23.5 Business workflows

Account deletion (incl. during running jobs) → cancellation + deletion workflow · consent revoked → stop ingestion · goals changed → recompute · outreach outside PodBae → manual status · subscription expired → clear entitlements · payment failure → webhook retries and reconciliation · advertiser complaint → evidence, correction, suppression · venue unavailable → confirm before presenting as bookable.

### 23.6 Five mandatory pre-launch tests

1. Fewer than three good opportunities → shows only qualified ones, never invents
2. Brand detected but not a sponsor → labelled organic/unverified, excluded from history
3. Outdated contact → not shown as verified; revalidate or official channel
4. Creator-blocked category → excluded before ranking even at fit 99
5. LLM provider down → opportunities, search, ranking and saving still work; template explanations

All become automated integration tests.

---

## 24. Security, Privacy & Compliance

**Security:** prompt-injection resistance · input validation and HTML sanitization · secrets in env/secret manager · role-based access · tenant isolation · rate limiting · audit logs · encryption in transit/at rest · tool permission boundaries.

**Privacy & data:** creator analytics consent · transcript usage per provider/feed terms · professional contact data handling · retention periods · deletion requests · third-party data licensing · cross-border handling · outreach regulations (e.g. CAN-SPAM opt-out) · no automated sending without approval.

**Requires legal review (not claimed by the team):** jurisdiction-specific privacy obligations, contact-data enrichment legality, data licensing terms, outreach compliance.

---

## 25. Six-Month Roadmap

| Weeks | Phase | Business milestone | Key deliverables | Priority |
|---|---|---|---|---|
| 0 | Local MVP replica | Testable product shell | UI, routes, API surface, mock AI | ✅ Done |
| 1–2 | Discovery & validation | First problem PodBae can reliably solve | Founder Vibe Logic session, data-access confirmation, gold eval set, KPI baseline, podcaster interviews | Must |
| 2–5 | **Layer 1 + Trust Spine** | Creator connects a show → useful honest profile | Ingestion, identity, tiered extraction, embeddings, profile UI, coverage matrix, cost ledger | Must |
| 6–8 | **Layer 4 (podcast partners)** | First evidence-backed recommendations | Eligibility, compatibility, confidence, ranking, explanations, eval vs baseline | Must |
| 9–11 | **Layer 2 Sponsor** | Creators see real sponsor leads | Brand identity, ad-read classes, sponsorship events, lookalike, contact tiers | Must |
| 12–14 | **Layer 5 Bae + Execution** | Creator acts without leaving PodBae | Controlled agent, outreach drafts with approval, pipeline, reminders | Must |
| 15–16 | **Layer 3 Venue** | Differentiated offline opportunities | Discovery vs verified venues, geo signals | Should |
| 17–18 | **Layer 6 Outcomes & tuning** | Measuring real outcomes | Event logging, metrics dashboard, weight tuning, cost reports | Must |
| 19–20 | Advertiser-side intelligence | Two-sided marketplace start | Brand → creator recommendations, campaign tracking | Stretch |
| 20–22 | Production readiness & integration | Reliable end-to-end product | Real Postgres/pgvector, queue workers, edge-case tests, security review, integration into PodBae backend, handover docs | Must |

Every layer ships with: tests, measured report, demo in the local app.

---

## 26. Team Responsibilities

| Member | Focus |
|---|---|
| A — Data & Ingestion | Connectors, identity resolution, transcripts, sponsor/guest detection, coverage matrix |
| B — Engine & Evaluation | Features, Vibe Logic implementation, eligibility, ranking, gold set, metrics, cost reports |
| C — Agent, API & Integration (full-stack) | Trust spine APIs, Bae workflow, explanations, Express wiring, UI for profiles/opportunities/pipeline, final integration |

Shared: code review, weekly demo to founder/CTO, faculty SPOC updates.

---

## 27. Acceptance Criteria

**Project-level:**
- A creator can connect a real podcast and receive an honest profile with tier labels
- The creator receives evidence-backed opportunities with four separate measures, never padded
- Every opportunity has evidence and a faithful explanation
- Blocked categories/brands never appear
- Bae answers only from tools, drafts outreach, and never sends without approval
- The pipeline tracks outcomes; metrics are reported per scoring version
- The engine beats the MVP baseline on the founder-approved gold set (Precision@3)
- Cost per creator and per qualified opportunity are measured and within agreed budgets
- The five mandatory scenarios pass as automated tests
- The AI service integrates into PodBae's backend by changing Express calls only

**Per layer:** tests pass, measured report written, demo works in the local app, seams documented for the next layer.

---

## 28. Questions for the Founder & CTO

1. What exactly is Vibe Logic™ — factors, priorities, dealbreakers? Who approves scoring versions?
2. Which paid data sources does PodBae already have (Rephonic plan/API, Taddy tier, contact enrichment)?
3. Monthly LLM/API budget per creator and per tier?
4. Who performs human review of sponsor/venue leads ("AI + human review")?
5. Repo access: Replit → private GitHub; can the BIT team be added?
6. Payment provider of record: Lemon Squeezy or Stripe? Final plan names and prices?
7. Advertiser fee structure for campaigns from $150?
8. Legal/privacy review ownership for contacts, transcripts and analytics uploads?
9. Target launch scope for May 2027 — which match types must be live?
10. Success metrics the founder will judge the project by?

---

## Appendix A — Build Prompts

All prompts are run in Claude Code from the `podbae-local` folder. Each phase stops after a report.

| Step | Prompt | Status |
|---|---|---|
| Phase 0 | Local MVP replica (Windows, no Docker, PGlite, torch_gpu, live-site UI tokens) | ✅ Done — see `TESTING_CHECKLIST.md` |
| Layer 1 | Podcast Intelligence + Trust Spine | ▶ Next |
| Layer 4 | Opportunity Engine — podcast partners only | After Layer 1 report |
| Layer 2 | Sponsor Intelligence | After Layer 4 |
| Layer 5 | Bae + Execution | After Layer 2 |
| Layer 3 | Venue Intelligence | After Layer 5 |
| Layer 6 | Outcomes & Economics | Throughout, formalized after Layer 3 |

### A.1 Layer 1 prompt (Podcast Intelligence + Trust Spine)

````text
We are building the AI layer of PodBae Local (the localhost MVP replica in this folder is done and tested).
Build ONLY Layer 1: Podcast Intelligence, plus the Trust Spine that every later layer will reuse.
Do NOT build sponsor, venue, opportunity-engine, or agent features yet; leave clean seams for them.

NON-NEGOTIABLE PRINCIPLES (enforce in code and tests, not just docs)
1. Trust before intelligence: every stored fact has a source, a data tier, and a timestamp. If something
   cannot be verified, say so. Never fabricate podcasts, audience numbers, demographics, guests or brands.
2. Business outcomes before AI complexity: the deliverable is a podcast profile a creator finds useful,
   not the most advanced pipeline. Prefer rules and simple models; use an LLM only where it clearly helps.
3. Sustainable economics: every external call, LLM call and GPU job is logged in a cost ledger with an
   estimated cost and is subject to a budget. Shared intelligence is cached and never recomputed needlessly.

LOCAL CONSTRAINTS (unchanged)
- Windows, no Docker. Python runs in my conda env torch_gpu: install deps with
  `conda run -n torch_gpu pip install -r services/ai/requirements.txt`.
- Must work with zero API keys (mock LLM, local embeddings). Optional keys in .env:
  OPENAI_API_KEY or ANTHROPIC_API_KEY, PODCASTINDEX_API_KEY/SECRET, TADDY_USER_ID/TADDY_API_KEY.
- `npm run dev` must still start everything.

DATA OWNERSHIP AND STORAGE
- services/ai owns an "intelligence store", separate from the app DB. The Node API and web app access it only
  through the AI service HTTP API (never direct DB access).
- Use SQLAlchemy 2 + Alembic with INTEL_DATABASE_URL. Local default: SQLite file data/intel.db with WAL mode,
  plus sqlite-vec for vector search. Put vector search behind a VectorIndex interface with two
  implementations: sqlite-vec (local) and pgvector (production, Postgres). Tests run on SQLite.
  Keep the SQL portable so switching to Postgres+pgvector is a config change.

TRUST SPINE (build first)
Tables:
- sources(id, name, kind[rss|podcastindex|taddy|creator|llm|manual], terms_note)
- provenance(id, entity_type, entity_id, field, value_json, source_id, source_ref, data_tier
  [verified|creator_provided|estimated|inferred], method[parsed|api|llm|model|rule|manual], model_version,
  fetched_at, expires_at, confidence 0-1, superseded_by null)
- evidence(id, entity_type, entity_id, kind, snippet ≤ 300 chars, locator{episode_id, timestamp|url},
  source_id, created_at)
- cost_ledger(id, ts, operation, provider, units, unit_cost_estimate, cost_estimate_usd, podcast_id null,
  user_id null, cache_hit bool)
- budgets(scope[global|podcast|user|tier], key, period, limit_usd, used_usd)
- jobs(id, type, idempotency_key unique, status[queued|running|succeeded|failed|cancelled], attempts,
  max_attempts, last_error, payload, result, created_at, updated_at)
- audit_log(id, ts, actor, action, entity_type, entity_id, detail)
Rules:
- Every field shown to users comes from provenance with a tier. A field-level freshness policy
  (e.g. episodes 24h, profile 7d) sets expires_at; stale values are flagged and refreshed, not silently trusted.
- Conflicting values from different sources are all kept; a resolver picks a display value by tier priority
  (verified > creator_provided > estimated > inferred), then freshness, and records the conflict.
- Untrusted-content guard: all external text (RSS, show notes, transcripts) is sanitized (strip HTML/scripts,
  control chars, length caps) and passed to LLMs only inside clearly delimited data blocks, with a system
  instruction that this content is data, never instructions. Add a test with an injected "ignore previous
  instructions…" transcript that must not change behaviour or output schema.
- Jobs: in-process worker (APScheduler or a simple asyncio queue) is fine locally, BUT every job is idempotent
  (idempotency_key), resumable, retried with exponential backoff up to max_attempts, then marked failed with a
  reason. The jobs table is the queue's source of truth, so it can be swapped for a real queue in production.
- Budgets: before any paid or LLM call, check the budget; if exceeded, skip, log, and degrade gracefully.

LAYER 1: PODCAST INTELLIGENCE
A. Ingestion (connectors behind one interface, each reporting which fields it actually returned)
   - RSS (feedparser + httpx): validate URL, timeouts, size limits, malformed-XML tolerance, conditional GET
     (ETag/Last-Modified), incremental episode upsert, pagination for huge feeds (store the latest 200
     episodes' metadata, process the latest 20 deeply), <podcast:transcript>, <podcast:person>, itunes tags.
   - Podcast Index (free key): lookup by feed URL / itunes id for canonical IDs and dedupe; directory search.
   - Taddy: optional behind a feature flag when keys exist (episodes + transcripts), with request budget.
   - Field coverage report per connector: % of shows where each field was present. This is our measured
     data-feasibility matrix; expose it at GET /v1/admin/coverage.
B. Normalization + identity
   - Canonical show identity with aliases: rss url(s), podcastindex id, itunes id, guid (podcast:guid).
     Handle changed RSS URLs (redirects, <itunes:new-feed-url>), renamed shows, duplicate feeds.
   - Episode reconciliation: deleted episodes are marked removed, not hard-deleted.
   - Language detection per show and episode (fast lightweight detector).
   - Inactivity detection: active / slowing / inactive based on publishing gaps.
C. Content understanding (tiered, never invents audience facts)
   - Rules first: cadence, average length, episode count, explicit flag, categories, last published,
     format hints (guests present via podcast:person or title patterns).
   - LLM extraction (small cheap model; mock provider when no key) with strict JSON schema output validated
     by pydantic: topics (multi-topic, with weights), vibe scores 0-1 on the fixed 12-term vocabulary
     (Casual, Compelling, Educational, Energetic, Humorous, Inspirational, Personal Narrative, Professional,
     Reflective, Relaxed, Uplifting, Wellness-Focused), tone, conversational_style, values (fixed taxonomy
     file), guest-friendliness, brand-safety flags, and a short likely-audience description. Everything from
     the LLM is stored as data_tier=inferred with evidence snippets that support it. NO ages, genders,
     incomes, cities, or listener counts from the LLM, ever. Enforce this in the schema.
   - Cache by content hash + prompt version + model version; unchanged content = zero LLM calls.
   - Invalid JSON → bounded retries → fall back to rules-only profile with low confidence.
   - Transcripts: use provided transcripts only. faster-whisper on GPU exists as an optional, budgeted job,
     OFF by default, and only for the creator's own show's latest 3 episodes when they opt in.
   - Transcript quality check (length vs duration, garbage ratio); low quality lowers confidence.
D. Embeddings (local GPU, sentence-transformers; pick a small multilingual BGE/E5-class model and justify it)
   - Separate vectors: content (description + episode titles/descriptions), style (vibe/tone text),
     episode chunks (transcripts when available). Store model name + version; re-embed on model change.
   - GET /v1/shows/{id}/similar?space=content|style returns neighbours with similarity and the reason fields.
E. Creator-provided data (the main path to VERIFIED audience data)
   - POST /v1/shows/{id}/audience-upload: accept a CSV export (top countries/cities, age bands, totals) with a
     column-mapping step; store as creator_provided with the file as evidence; validate ranges and flag
     implausible numbers instead of rejecting silently.
   - Creator self-declared fields (goals, collaboration openness, blocked categories) stored as creator_provided.
F. Podcast Intelligence Profile (the deliverable)
   GET /v1/shows/{id}/profile returns, per field: value, data_tier, source, fetched_at, freshness status,
   confidence, evidence refs. Plus an overall profile completeness score and a "what would improve this
   profile" list (e.g. "upload audience analytics", "add a transcript feed").
   Cold start: a new show with 1-2 episodes still gets a profile, marked "preliminary".

API (FastAPI, versioned /v1, pydantic contracts mirrored into packages/contracts as TS types)
POST /v1/ingest/rss {rss_url, user_id?} → job_id   (idempotent per canonical feed)
POST /v1/ingest/discover {query|category, limit}   → job_id (Podcast Index, budgeted)
GET  /v1/jobs/{id}
GET  /v1/shows?q&category&language&activity        GET /v1/shows/{id}/profile
GET  /v1/shows/{id}/episodes                       GET /v1/shows/{id}/similar
POST /v1/shows/{id}/refresh                        POST /v1/shows/{id}/audience-upload
GET  /v1/admin/coverage   GET /v1/admin/costs   GET /v1/admin/jobs   GET /v1/health (incl. LLM/provider status)

WIRE INTO THE EXISTING MVP (Express + web)
- /api/agent/ingest-rss and the /submit flow call /v1/ingest/rss; show job progress in the UI.
- New page /intelligence (podcaster): the profile with tier badges (Verified / Creator-provided / Estimated /
  AI-inferred), source + date on hover, freshness warnings, completeness meter, "improve your profile"
  actions, and the audience CSV upload.
- /discover uses /v1/shows for real ingested shows (demo rows still flagged).
- Admin: existing Taddy/directory controls → jobs, coverage and cost dashboards.
- If the AI service is down, the app shows the last cached profile with a "may be outdated" banner.

SEED REAL DATA
Script `npm run intel:seed` ingests ~300 real independent shows across at least 8 categories via
Podcast Index (or a bundled list of public RSS URLs if no key), within a configurable budget.

TESTS (pytest; these are acceptance criteria)
- Invalid URL, offline feed (cached data + freshness warning), malformed XML, 5,000-episode feed
  (incremental, bounded time), duplicate feeds collapse to one show, changed feed URL keeps identity,
  deleted episode marked removed, non-English show detected, inactive show flagged.
- Re-running ingestion = no duplicates; killing a job mid-run then resuming completes it.
- LLM mock returns invalid JSON → retries → rules-only fallback, no crash.
- Prompt-injection transcript does not alter output schema or add fields.
- LLM output can never set age/gender/income/city/listener-count fields (schema rejects).
- Unchanged content = cache hit, zero LLM cost recorded.
- Budget exceeded → enrichment skipped gracefully and logged.
- Profile endpoint returns tier + source + timestamp for every field.

EVALUATION (write EVAL_LAYER1.md with real numbers)
- Hand-label 30 shows (I will review): topics, vibe top-3, conversational style, guest-friendly.
  Report agreement of the extraction vs labels, per field.
- Dedupe precision on a set of known duplicates you construct.
- Similarity sanity: for 10 shows, list top-5 neighbours; I judge them.
- Coverage matrix from real ingestion, cost per show (avg, p95), cache hit rate, ingestion time per show.

FINISH
Run all tests, run the seed, start everything, open http://localhost:5173/intelligence with the demo
podcaster connected to a real RSS feed. Write LAYER1_REPORT.md: what works, measured numbers, what is mocked,
which fields are actually available from which source (from the coverage matrix), known risks, and the exact
seams left for Layer 2 (sponsor intelligence) and Layer 4 (opportunity engine). Then STOP.
````

---

## Appendix B — Design Tokens of the Live Site

Extracted from podbae.love (shadcn theme variables):

| Token | Light | Dark |
|---|---|---|
| `--background` | hsl(330 40% 96%) · #F9F1F5 | hsl(0 0% 4%) |
| `--foreground` | hsl(210 40% 14%) · #152432 | hsl(210 20% 90%) |
| `--primary` | hsl(326 100% 66%) · #FF52B4 | same |
| `--card` | hsl(0 0% 100%) | hsl(0 0% 8%) |
| `--muted` / `--secondary` / `--accent` | hsl(210 40% 96%) | hsl(0 0% 11–13%) |
| `--muted-foreground` | hsl(210 22% 54%) | hsl(210 15% 55%) |
| `--border` / `--input` | hsl(214 32% 91%) | hsl(0 0% 15–18%) |
| `--radius` | .75rem (buttons ~10px) | — |

Fonts: Inter (body/headings), DM Sans. Section gradient `.gradient-bg`: `linear-gradient(135deg, #F9F1F5, #F1E4ED)`. Hero wordmark: pink → purple gradient (#FF52B4 → #A855F7).

---

## Appendix C — Sources

- PodBae live site — https://podbae.love/
- PodBae × BIT project requirements PDF (provided)
- PodBae business listing — https://helloskip.com/b/fm-digital-llc
- Alitu, *The Independent Podcaster Report 2025* — https://alitu.com/creator/content-creation/the-independent-podcaster-report-2025/
- Podcast News Daily on the Indie survey — https://www.podcastnewsdaily.com/news/passion-over-profit-survey-finds-most-indie-podcasters-aren-t-monetizing-shows/article_e2e6876e-96e2-4d34-b131-0ac287539ba4.html
- RSS.com Podcaster Insights Survey — https://rss.com/blog/podcaster-insights-survey/
- MarketingCharts on podcaster monetization — https://www.marketingcharts.com/cross-media-and-traditional-80276
- PodMatch vs Talks.co (pricing) — https://talks.co/p/?p=7777
- PodMatch vs Matchmaker.fm — https://talks.co/p/?p=7467
- PodPitch pricing (Rephonic blog) — https://rephonic.com/blog/podpitch-pricing
- Rephonic API — https://rephonic.com/developers
- Rephonic review — https://vidpros.com/rephonic-review/
- Taddy developers — https://taddy.org/developers
- Taddy: best podcast APIs — https://taddy.org/blog/best-podcast-api-tools
- Podcorn sponsorships — https://podcorn.com/sponsorships
- Buzzsprout: getting sponsors — https://www.buzzsprout.com/blog/get-podcast-sponsors

*Provider prices and capabilities were taken from public pages at the time of research (Nov 2026) and must be confirmed before being relied on.*
