# Testing checklist

Start with `npm run dev`, open http://localhost:5173. For a clean state run `npm run reset` first (stop dev before resetting).
Logins: `podcaster@podbae.local / demo123` · `brand@podbae.local / demo123` · `admin@podbae.local / admin123`.

## 1. Landing page (/)
- [ ] Navbar: logo, How It Works, Features, Pricing, "Advertise with Us" (pink), Log In (outline), Get Started (pink), moon icon. Anchor links scroll to the right sections.
- [ ] Hero: gradient "PodBae", h1 "Connecting Podcasters, One Match at a Time™", subtitle, two buttons, stats 1000+ / $67,000 / 96%.
- [ ] #how-it-works: 3 steps + 6 "Types of Matches" cards with emoji.
- [ ] #registration card: checklist + "Launching May 2027"; button goes to /submit.
- [ ] #advertise-with-shows: "Campaigns can start at $150".
- [ ] #features: 6 cards + water-mindful pledge.
- [ ] #pricing: toggle Monthly/Annual changes Date ($19↔$24) and Commit ($29↔$34); "Most Popular" on Commit; Premium shows "Contact Us".
- [ ] Testimonials, CTA band, #help-center: all 18 FAQ items expand/collapse (one open at a time).
- [ ] AI Support Chat: click a quick-reply chip → answer appears; type "how much does it cost" → pricing answer.
- [ ] Team section shows 5 placeholder members; footer links work.
- [ ] Dark mode: moon icon toggles; reload keeps the choice; cards/text remain readable.

## 2. Signups (all four roles) — /get-started
- [ ] Role picker shows Podcaster / Advertiser / Venue / Guest and routes to the right form.
- [ ] **Podcaster** (/submit): fill show name, pick category/vibe/tone/collab, location "New York, NY", add name/email/password (≥8 chars) → submit → /success → dashboard has matches + predictions.
- [ ] **Advertiser** (/advertiser-submit): "Step N of 6" progress; org type → budget (try 100: Next is disabled; 150 OK) → audience/vibe/values → categories → goals → contact + password → lands on /dashboard/campaign-builder.
- [ ] **Venue** (/venue-submit) and **Guest** (/guest-submit): submit creates the account and goes to /success.
- [ ] Duplicate email shows an error toast; log out and log back in via /login (also try "Forgot password?" → link is printed in the API console).

## 3. Podcaster dashboard (podcaster@podbae.local)
- [ ] Header shows plan "flirt"; banner shows swipes used/limit and matches/day = 3.
- [ ] **Predictions** tab: cards show why / why now / evidence; Save, Act, Dismiss each remove or update the card with a toast. Note "sponsor recommendations hidden" and forecast-locked notices (flirt).
- [ ] **Matches** tab: exactly 3 matches (flirt), "Your plan shows 3 matches per day" notice. Type filter chips work. "Show score breakdown" shows bars + sources. Save/Dismiss work. "Run matching" re-scores.
- [ ] **Saved** tab lists saved matches; unsave removes.
- [ ] **Insights** and **Reach Estimate** tabs show counts/budget derived from data.
- [ ] Notifications box: click an item to mark read; "Mark all read".

## 4. Swipe → match → message
- [ ] /swipe (also /matching, /mymatches): card deck; ✕ passes, ♥ likes.
- [ ] Liking a demo user shows the toast **"It's a Match! 💕"**.
- [ ] /messages: a new conversation exists; send a message; log in as that demo user (e.g. `crime@demo.podbae.local / demo123`) in another browser/incognito → unread badge appears in the nav within ~5 s; opening the thread clears it.
- [ ] As flirt, keep swiping: after 10 swipes the toast says the daily limit is reached.

## 5. Upgrade + Hey Bae
- [ ] On flirt, Hey Bae tab shows a lock notice; sending is blocked.
- [ ] "Upgrade to Commit $29" → confirmation dialog → mock checkout page → "Pay" → back on dashboard with plan **commit**.
- [ ] Hey Bae tab: ask "What are my best matches?" → reply lists your real top matches (mock reply). Matches/day is now "all", sponsor predictions and the forecast card appear.

## 6. Discover, profiles
- [ ] /discover: search "comedy"; category and vibe filters; pagination; demo/verified badges.
- [ ] "View profile →" opens /p/:userId; /profile/:userId works; /embed/:userId shows the compact card.
- [ ] /profile: edit name/headline/bio/goals/podcast tags → Save → changes show on the public profile.

## 7. Other pages
- [ ] /schedule: add a session, reload (persists in DB), remove it.
- [ ] /analytics, /partners (sponsors list), /listen and /listener-recommendations show data.
- [ ] /enterprise → /partnership-signup submit; appears later in Admin → Partnership invites.

## 8. Advertiser (brand@podbae.local)
- [ ] /dashboard/campaign-builder: create a campaign (budget < $150 is rejected/disabled); it appears in the list.

## 8b. Layer 1: Podcast Intelligence (needs `npm run dev`; run `npm run intel:connect-demo` first for a real feed)
- [ ] Nav shows **Intelligence**. /intelligence as podcaster: progress list (feed → directory → transcripts → enrich → embed), then the profile.
- [ ] Every field row has a tier badge (Verified green / Creator-provided blue / Estimated amber / AI-inferred purple); hovering shows source, method, fetched time, freshness, confidence.
- [ ] Completeness meter + "Improve your profile" list; audience fields are listed as **Unknown (never guessed)** until you upload data.
- [ ] Upload a CSV (e.g. `Country,Downloads,Percent` with 3 rows) → column-mapping step → import → the field turns **Creator-provided** and the improve item disappears.
      Try a percent of 150 → warning shown, field flagged low-confidence (not silently accepted).
- [ ] "Add goals" saves creator-provided goals; "Refresh from RSS" starts a job and the page updates.
- [ ] Submit flow: on /submit enter a real RSS URL → /success shows live ingestion progress.
- [ ] Stop the AI service (Ctrl+C the `ai` process) and reload /intelligence → "may be outdated" banner with the last saved profile.
- [ ] /discover: a "Real shows from RSS" section below the demo rows; "View intelligence →" opens the public profile (no audience/creator fields).
- [ ] /admin → **Ingestion jobs** (service status, ingest a feed, discover, job list), **Coverage** (per-field % per connector), **Costs** (totals, budgets, by operation).

## 8c. Phase 1 (rules + local model, no LLM)
- [ ] `npm run ui:smoke` (with `npm run dev` running) prints "0 with problems"; screenshots land in `screenshots/`.
- [ ] /intelligence: topics show taxonomy names; hover a topic to see its basis (lexicon / model / declared) and supporting episodes.
- [ ] Conversational style shows "Unknown: no rule was confident" for shows where no rule fires (never a guess).
- [ ] Guests present shows "x of y recent episodes"; the Evidence list shows the example episode titles and the rule that fired.
- [ ] /admin → **Coverage**: "Feed fetch outcomes" table with failure reasons (http_4xx, timeout, invalid_xml, ...).
- [ ] /admin → **Ingestion jobs** → "Recalibrate corpus" returns counts (vibe stats n, style vectors).
- [ ] /admin → **Labels** → "Open the labelling page" → /admin/labels: enter your name, label a show (1-5 topics, exactly 3 vibes,
      style, guest-friendly) → "Save & next"; the number turns green; progress counter increases.
- [ ] Label the same shows under a second name → the agreement table shows kappa / Jaccard for the pair.
- [ ] Stop the AI service, or set a wrong `INTEL_SERVICE_TOKEN` for the API only → intelligence pages degrade (cached profile / "ai down"), the app does not crash.

## 9. Admin (admin@podbae.local / admin123)
- [ ] /admin: stats; Podcasts tab → Verify/Unverify toggles; Users tab lists accounts.
- [ ] "Generate opportunities", "Run enhanced matching", "Seed test podcasts" show a toast result.
- [ ] Vibe-logic metrics tab: weights, matches by type, recommendations.
- [ ] Showcase tab: search and Feature/Unfeature a show; Discover/landing featured data updates (`/api/public/featured-shows`).
- [ ] Partnership invites tab lists submissions.
- [ ] Log in as a non-admin and open /admin → "Admins only"; `/api/admin/users` returns 403.
- [ ] /admin/setup says an admin already exists (on a fresh DB with no admin it creates the first one).
