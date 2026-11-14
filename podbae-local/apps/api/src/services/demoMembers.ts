// Phase 2 demo setup (local only, all rows demo=true): connect the demo podcaster to a seeded show and make ~20 seeded
// shows PodBae members with varied collaboration openness, so every readiness level and the no-match state can be seen.
// Idempotent: re-running reuses the same users / podcasts / links / claims.
import bcrypt from 'bcryptjs';
import { q, q1 } from '../db/client.js';
import { HttpError } from '../lib.js';
import { intel } from './intel.js';
import { syncAdvertisers } from './opportunities.js';

/** Phase 4: three DEMO advertisers (demo=true, fake orgs) carry the website of a brand seen in the store, so the Verified
 *  sponsor path (registered advertiser matched by registrable domain) can be demonstrated. Real advertisers are never touched. */
export const DEMO_ADVERTISER_WEBSITES: Record<string, string> = {
  'fit@demo.podbae.local': 'drinkag1.com', 'edu@demo.podbae.local': 'shopify.com', 'ngo@demo.podbae.local': 'betterhelp.com',
};

export async function ensureDemoAdvertiserWebsites() {
  for (const [email, site] of Object.entries(DEMO_ADVERTISER_WEBSITES))
    await q('UPDATE advertisers SET website = $1 WHERE demo = true AND contact_email = $2 AND website IS NULL', [site, email]);
  return syncAdvertisers();
}

type Openness = 'open' | 'selective' | 'closed' | null;
// cycle over the shows most similar to the demo show: Verified (open/selective), Potential lead (no openness), gated (closed)
const PATTERN: { openness: Openness; goals: string[] }[] = [
  { openness: 'open', goals: ['cross_promo'] }, { openness: 'selective', goals: [] }, { openness: null, goals: [] },
  { openness: 'open', goals: ['guest_swap'] }, { openness: null, goals: ['grow_audience'] }, { openness: 'selective', goals: ['feed_swap'] },
  { openness: 'closed', goals: [] },
];
const RARE_LANGS = ['so', 'sk', 'el', 'tr', 'fil', 'sv', 'no', 'pt', 'fr', 'es'];

async function ok<T = any>(path: string, init?: Parameters<typeof intel>[1]): Promise<T> {
  const r = await intel<T>(path, init);
  if (r.status >= 300) throw new HttpError(502, `AI service ${path}: ${r.status} ${JSON.stringify(r.body).slice(0, 200)}`);
  return r.body;
}

async function upsertUser(email: string, name: string) {
  const ex = await q1('SELECT id FROM users WHERE email = $1', [email]);
  if (ex) return ex.id as number;
  const hash = await bcrypt.hash('demo123', process.env.NODE_ENV === 'test' ? 4 : 10);
  const u = await q1(`INSERT INTO users (email, password_hash, name, role, tier, onboarded, demo) VALUES ($1,$2,$3,'podcaster','flirt',true,true)
                      RETURNING id`, [email, hash, name]);
  return u.id as number;
}

/** Demo join dates spread over the past ~6 months (deterministic), so 'recently joined PodBae' fires only for the few recent ones. */
export const demoJoinDaysAgo = (i: number) => 3 + ((i * 41) % 178);

async function linkPodcast(userId: number, show: { show_id: string; title: string; feed_url: string; categories: string[] }, joinedDaysAgo = 120) {
  let pod = await q1('SELECT id FROM podcasts WHERE owner_user_id = $1 ORDER BY id LIMIT 1', [userId]);
  const taken = await q1('SELECT id FROM podcasts WHERE rss_url = $1', [show.feed_url]);
  const rss = taken && (!pod || taken.id !== pod.id) ? null : show.feed_url;
  if (!pod) {
    pod = await q1(`INSERT INTO podcasts (owner_user_id, source, rss_url, name, description, categories, collaboration_types, demo)
                    VALUES ($1,'rss',$2,$3,'Demo member: a real public show from the intelligence store, linked for the Phase 2 demo.',$4,
                            '{"Promo Swap/Feed Swap","Guest Swap"}',true) RETURNING id`,
      [userId, rss, show.title, (show.categories ?? []).slice(0, 4)]);
  } else if (rss) {
    await q('UPDATE podcasts SET rss_url = $1, updated_at = now() WHERE id = $2', [rss, pod.id]);
  }
  await q(`INSERT INTO intel_links (podcast_id, rss_url, intel_show_id) VALUES ($1,$2,$3)
           ON CONFLICT (podcast_id) DO UPDATE SET rss_url = EXCLUDED.rss_url, intel_show_id = EXCLUDED.intel_show_id, profile = NULL, updated_at = now()`,
    [pod.id, show.feed_url, show.show_id]);
  await ok(`/shows/${encodeURIComponent(show.show_id)}/claim?user_id=${userId}&demo=true&joined_days_ago=${joinedDaysAgo}`, { method: 'POST' });
  return pod.id as number;
}

async function card(showId: string) {
  const p = await ok(`/shows/${encodeURIComponent(showId)}/profile?refresh=false`);
  return { show_id: p.show_id, title: p.title, feed_url: p.feed_url, categories: p.fields?.categories?.value ?? [], language: p.fields?.language?.value };
}

export async function demoSetup(opts: { showId?: string } = {}) {
  const demoUser = await q1(`SELECT id FROM users WHERE email = 'podcaster@podbae.local'`);
  if (!demoUser) throw new HttpError(404, 'Demo podcaster not seeded (npm run seed)');
  // 1. the demo podcaster's show: keep a valid existing link, else the first English Comedy show in the store
  const pod = await q1('SELECT id FROM podcasts WHERE owner_user_id = $1 ORDER BY id LIMIT 1', [demoUser.id]);
  const link = pod ? await q1('SELECT intel_show_id FROM intel_links WHERE podcast_id = $1', [pod.id]) : null;
  let demoShow = opts.showId ?? null;
  if (!demoShow && link?.intel_show_id && (await intel(`/shows/${link.intel_show_id}/profile?refresh=false`)).status === 200) demoShow = link.intel_show_id;
  if (!demoShow) {
    const list = await ok('/shows?category=Comedy&language=en&limit=100');
    demoShow = list.shows?.[0]?.id;
    if (!demoShow) throw new HttpError(409, 'No English comedy show in the intelligence store; run npm run intel:seed first');
  }
  const demo = await card(demoShow!);
  await linkPodcast(demoUser.id, demo, 150);
  await ok(`/shows/${encodeURIComponent(demo.show_id)}/creator-profile`, { method: 'PUT',
    json: { user_id: String(demoUser.id), goals: ['cross_promo', 'guest_swap'], collaboration_openness: 'open' } });

  // 2. members: the 14 shows most similar to the demo show (so they appear in its opportunities) + 5 spread across the store
  const sim = await ok(`/shows/${encodeURIComponent(demo.show_id)}/similar?space=content&limit=20`);
  const near: string[] = (sim.neighbours ?? []).map((n: any) => n.show_id).filter((id: string) => id !== demo.show_id).slice(0, 14);
  const all = await ok('/shows?limit=100&offset=0');
  const spread: string[] = (all.shows ?? []).map((s: any) => s.id).filter((id: string) => id !== demo.show_id && !near.includes(id))
    .filter((_: string, i: number) => i % 19 === 7).slice(0, 5);
  const members: any[] = [];
  const ids = [...near, ...spread];
  for (const [i, sid] of ids.entries()) {
    const c = await card(sid);
    const pat = i < near.length ? PATTERN[i % PATTERN.length] : PATTERN[(i % 2) * 2];
    const n = String(i + 1).padStart(2, '0');
    const uid = await upsertUser(`member${n}@demo.podbae.local`, `Demo host ${n}`);
    await linkPodcast(uid, c, demoJoinDaysAgo(i));
    await ok(`/shows/${encodeURIComponent(sid)}/creator-profile`, { method: 'PUT', json: {
      user_id: String(uid), goals: pat.goals, ...(pat.openness ? { collaboration_openness: pat.openness } : {}) } });
    members.push({ email: `member${n}@demo.podbae.local`, show: c.title, show_id: sid, openness: pat.openness ?? 'not stated',
      similar_to_demo: i < near.length });
  }
  // 2b. Commit-tier showcase (mindful@demo.podbae.local sees ALL opportunities): a show whose qualified list contains every
  //     readiness level. Its closest neighbours become members too (open / not stated), so Verified appears next to the leads.
  let showcase: any = null;
  const commitUser = await q1(`SELECT id FROM users WHERE email = 'mindful@demo.podbae.local'`);
  const sc = commitUser ? (await ok(`/admin/engine/showcase?exclude=${encodeURIComponent([demo.show_id, ...ids].join(","))}`, { timeoutMs: 900_000 })).showcase : null;
  if (commitUser && sc) {
    const c = await card(sc.show_id);
    await linkPodcast(commitUser.id, c, 95);
    await ok(`/shows/${encodeURIComponent(sc.show_id)}/creator-profile`, { method: 'PUT',
      json: { user_id: String(commitUser.id), goals: ['cross_promo'], collaboration_openness: 'selective' } });
    const extra: string[] = (sc.member_suggestions ?? []).filter((x: string) => !ids.includes(x) && x !== demo.show_id).slice(0, 2);
    const base = ids.length;
    for (const [j, sid] of extra.entries()) {
      const c2 = await card(sid);
      const n = String(base + j + 1).padStart(2, '0');
      const uid = await upsertUser(`member${n}@demo.podbae.local`, `Demo host ${n}`);
      await linkPodcast(uid, c2, demoJoinDaysAgo(base + j));
      if (j === 0) await ok(`/shows/${encodeURIComponent(sid)}/creator-profile`, { method: 'PUT', json: { user_id: String(uid), collaboration_openness: 'open' } });
      members.push({ email: `member${n}@demo.podbae.local`, show: c2.title, show_id: sid, openness: j === 0 ? 'open' : 'not stated', similar_to_demo: false });
      ids.push(sid);
    }
    showcase = { email: 'mindful@demo.podbae.local', tier: 'commit', show: c.title, show_id: c.show_id };
  }
  // 2c. retire demo members from earlier runs that are no longer part of the set (unlink + unclaim)
  const keep = new Set(members.map((m) => m.email));
  for (const u of await q(`SELECT id, email FROM users WHERE email LIKE 'member%@demo.podbae.local' AND demo = true`)) {
    if (keep.has(u.email)) continue;
    for (const l of await q(`SELECT l.intel_show_id FROM intel_links l JOIN podcasts p ON p.id = l.podcast_id WHERE p.owner_user_id = $1`, [u.id])) {
      if (l.intel_show_id) await intel(`/shows/${encodeURIComponent(l.intel_show_id)}/claim?user_id=${u.id}`, { method: 'DELETE' });
    }
    await q('DELETE FROM podcasts WHERE owner_user_id = $1', [u.id]);
    await q('DELETE FROM users WHERE id = $1', [u.id]);
  }
  // 3. a member whose language almost nobody shares -> the honest "no good match yet" state
  let noMatch: any = null;
  for (const lang of RARE_LANGS) {
    const r = await ok(`/shows?language=${lang}&limit=5`);
    if ((r.total ?? 0) === 1) {
      const c = await card(r.shows[0].id);
      const uid = await upsertUser('nomatch@demo.podbae.local', 'Demo no-match host');
      await linkPodcast(uid, c, 60);
      noMatch = { email: 'nomatch@demo.podbae.local', show: c.title, show_id: c.show_id, language: lang };
      break;
    }
  }
  // 4. demo advertisers' websites -> brand registrations (domain only), BEFORE sponsor generation so Verified can appear
  let advertisers: any = null;
  try { advertisers = await ensureDemoAdvertiserWebsites(); } catch { advertisers = { error: 'sync failed' }; }
  // 5. (re)generate for everyone involved
  const targets = [demo.show_id, ...ids, ...(showcase ? [showcase.show_id] : []), ...(noMatch ? [noMatch.show_id] : [])];
  for (const sid of targets) {
    await ok('/opportunities/generate', { json: { member_show_id: sid, force: true } });
    await ok('/sponsor-opportunities/generate', { json: { member_show_id: sid, force: true } });   // Layer 2 sponsor cards
  }
  await q('DELETE FROM opportunity_cache');
  return { demo_podcaster: { email: 'podcaster@podbae.local', show: demo.title, show_id: demo.show_id }, members, commit_showcase: showcase, no_match: noMatch,
    generated_for: targets.length, advertisers, password: 'demo123 (all demo accounts)' };
}
