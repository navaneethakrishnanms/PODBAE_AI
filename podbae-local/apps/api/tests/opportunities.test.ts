import request from 'supertest';
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { createApp } from '../src/app.js';
import { config } from '../src/config.js';
import { initDb, q, q1 } from '../src/db/client.js';
import { seedDatabase } from '../src/db/seed.js';
import { applyDailyOpportunityLimit } from '../src/services/opportunities.js';

const app = createApp();
const login = async (email: string, password: string) => {
  const agent = request.agent(app);
  expect((await agent.post('/api/auth/login').send({ email, password })).status).toBe(200);
  return agent;
};
const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });
const EMAIL = /[\w.+-]+@[\w-]+(?:\.[\w-]+)+/;

const item = (n: number, extra: Record<string, unknown> = {}) => ({
  id: `opp_${n}`, member_show_id: 'shw_me', type: 'cross_promo', type_label: 'cross-promo', rank: n,
  target: { show_id: `shw_t${n}`, title: `Target ${n}`, is_member: n === 1, member_user_id: null, website: n === 2 ? 'https://t2.example' : null },
  fit: { value: 80 - n, note: 'Vibe Logic draft — pending founder approval', scoring_version: 'fit-draft-v1' },
  confidence: { value: 0.6, level: 'Medium' }, readiness: { level: n === 1 ? 'verified' : 'potential_lead', label: 'x' },
  conversion: { status: 'not_enough_data', label: 'Not enough data yet' }, why_now: [], evidence: { shared_topics: ['Comedy'] },
  explanation: { text: `Target ${n} could be a good cross-promo partner.` }, breakdown: { factors: [], used: [], missing: [], disabled: [] },
  ...extra,
});
const list = (items: any[], shownToday: string[] = []) => ({
  member_show_id: 'shw_me', state: items.length >= 3 ? 'ok' : items.length ? 'few' : 'no_match', items, shown_today_target_ids: shownToday,
  scoring_version: 'fit-draft-v1', status: 'draft-unapproved-by-founder', total_qualified: items.length, stale: false, job: null,
});

/** fake AI service: records every call; `opps` controls the list response */
function fakeAi(opps: () => any, extra: (url: string, init?: RequestInit) => Response | undefined = () => undefined) {
  const calls: { url: string; method: string; body: any }[] = [];
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    calls.push({ url, method: init?.method ?? 'GET', body: init?.body ? JSON.parse(String(init.body)) : null });
    const x = extra(url, init);
    if (x) return x;
    if (url.includes('/claim')) return json(200, { show_id: 'shw_me' });
    if (url.includes('/v1/opportunities?')) return json(200, opps());
    if (url.includes('/v1/events')) return json(200, { recorded: [] });
    if (/\/v1\/opportunities\/opp_1$/.test(url)) return json(200, item(1, { target: { show_id: 'shw_t1', title: 'Target 1', is_member: true, member_user_id: String(memberUserId) } }));
    if (/\/v1\/opportunities\/opp_2$/.test(url)) return json(200, item(2));
    return json(404, {});
  }));
  return calls;
}
let memberUserId = 0;

beforeAll(async () => {
  await initDb();
  await seedDatabase();
  const pod = await q1(`SELECT p.id FROM podcasts p JOIN users u ON u.id = p.owner_user_id WHERE u.email = 'podcaster@podbae.local'`);
  await q(`INSERT INTO intel_links (podcast_id, intel_show_id, rss_url) VALUES ($1,'shw_me','https://me.test/feed.xml')
           ON CONFLICT (podcast_id) DO UPDATE SET intel_show_id = 'shw_me'`, [pod.id]);
  memberUserId = (await q1(`SELECT id FROM users WHERE email = 'founder@demo.podbae.local'`)).id;
});
afterEach(() => { vi.unstubAllGlobals(); config.engine = 'engine'; });

describe('daily allowance (pure)', () => {
  const its = [1, 2, 3, 4, 5].map((n) => ({ target: { show_id: `s${n}` } }));
  it('flirt: at most 3 per day, never padded', () => {
    expect(applyDailyOpportunityLimit(its, [], 3).items.map((i) => i.target.show_id)).toEqual(['s1', 's2', 's3']);
    expect(applyDailyOpportunityLimit(its.slice(0, 2), [], 3).items).toHaveLength(2);       // fewer qualify -> fewer shown
    expect(applyDailyOpportunityLimit([], [], 3).items).toHaveLength(0);
  });
  it('keeps today\'s items stable and does not refill slots used today (e.g. after a dismiss)', () => {
    const r = applyDailyOpportunityLimit(its.filter((i) => i.target.show_id !== 's1'), ['s1', 's2', 's3'], 3);
    expect(r.items.map((i) => i.target.show_id)).toEqual(['s2', 's3']);
    expect(applyDailyOpportunityLimit(its, ['s4'], 3).items.map((i) => i.target.show_id)).toEqual(['s1', 's2', 's4']);
  });
  it('commit: everything', () => expect(applyDailyOpportunityLimit(its, [], -1).items).toHaveLength(5));
});

describe('Layer 4 opportunities in the app (AI service mocked at the HTTP boundary)', () => {
  it('matches + predictions use the engine for podcast partners, apply the flirt limit and log impressions with positions', async () => {
    const agent = await login('podcaster@podbae.local', 'demo123');
    const calls = fakeAi(() => list([1, 2, 3, 4, 5].map((n) => item(n))));
    const r = await agent.get('/api/member/matches');
    expect(r.status).toBe(200);
    expect(r.body.engine).toBe('opportunity-engine');
    expect(r.body.opportunities.items).toHaveLength(3);                      // flirt tier
    expect(r.body.opportunities.limited).toBe(true);
    expect(r.body.matches.every((m: any) => m.targetType !== 'podcast')).toBe(true);   // legacy podcast rows replaced
    const ev = calls.filter((c) => c.url.endsWith('/v1/events')).at(-1)!;
    expect(ev.body.events.map((e: any) => [e.type, e.position])).toEqual([['impression', 1], ['impression', 2], ['impression', 3]]);
    expect(ev.body.events[0].idempotency_key).toMatch(/^imp:opp_1:\d+:\d{4}-\d{2}-\d{2}$/);
    const p = await agent.get('/api/predictions');
    expect(p.body.partnerOpportunities.items).toHaveLength(3);
    expect(p.body.predictions.every((x: any) => x.type !== 'podcast_swap')).toBe(true);
    expect(EMAIL.test(JSON.stringify(r.body.opportunities))).toBe(false);
  });

  it('fewer than 3 qualifying -> only those; none -> no-match state (never padded)', async () => {
    const agent = await login('podcaster@podbae.local', 'demo123');
    fakeAi(() => list([item(1)]));
    const few = await agent.get('/api/opportunities');
    expect(few.body.items).toHaveLength(1);
    expect(few.body.state).toBe('few');
    fakeAi(() => ({ ...list([]), message: 'No good match yet.', suggestions: [{ code: 'add_goals' }] }));
    const none = await agent.get('/api/opportunities');
    expect(none.body.items).toHaveLength(0);
    expect(none.body.state).toBe('no_match');
    expect(none.body.suggestions[0].code).toBe('add_goals');
  });

  it('AI service down -> the stored opportunities are still served with the "may be outdated" banner', async () => {
    const agent = await login('podcaster@podbae.local', 'demo123');
    fakeAi(() => list([1, 2].map((n) => item(n))));
    expect((await agent.get('/api/opportunities')).body.items).toHaveLength(2);
    vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('connect ECONNREFUSED'); }));
    const down = await agent.get('/api/opportunities');
    expect(down.status).toBe(200);
    expect(down.body.outdated).toBe(true);
    expect(down.body.items.map((i: any) => i.id)).toEqual(['opp_1', 'opp_2']);
    expect(down.body.message).toMatch(/may be outdated/);
    expect(down.body.cachedAt).toBeTruthy();
    const m = await agent.get('/api/member/matches');                         // the dashboard path degrades the same way
    expect(m.status).toBe(200);
    expect(m.body.opportunities.outdated).toBe(true);
  });

  it('dismiss requires a reason and forwards it; message opens a conversation with a member; invite records without e-mail', async () => {
    const agent = await login('podcaster@podbae.local', 'demo123');
    const calls = fakeAi(() => list([item(1)]));
    expect((await agent.post('/api/opportunities/opp_2/action').send({ action: 'dismiss' })).status).toBe(400);
    expect((await agent.post('/api/opportunities/opp_2/action').send({ action: 'dismiss', reason: 'too_big' })).status).toBe(200);
    const d = calls.filter((c) => c.url.endsWith('/v1/events')).at(-1)!;
    expect(d.body.events[0]).toMatchObject({ opportunity_id: 'opp_2', type: 'dismiss', reason: 'too_big' });

    const msg = await agent.post('/api/opportunities/opp_1/action').send({ action: 'message' });
    expect(msg.status).toBe(200);
    expect(msg.body.conversationId).toBeTruthy();
    expect(calls.filter((c) => c.url.endsWith('/v1/events')).at(-1)!.body.events[0].type).toBe('contact');
    expect((await agent.post('/api/opportunities/opp_2/action').send({ action: 'message' })).status).toBe(400);   // not a member

    const inv = await agent.post('/api/opportunities/opp_2/action').send({ action: 'invite' });
    expect(inv.status).toBe(200);
    const row = await q1('SELECT * FROM partnership_invites WHERE id = $1', [inv.body.inviteId]);
    expect(row).toMatchObject({ email: null, kind: 'podbae_invite', target_show_id: 'shw_t2', status: 'recorded' });
    expect((await agent.post('/api/opportunities/opp_1/action').send({ action: 'invite' })).status).toBe(400);    // already a member
  });

  it('an opportunity of another member cannot be acted on', async () => {
    const agent = await login('podcaster@podbae.local', 'demo123');
    fakeAi(() => list([]), (url) => (url.includes('/v1/opportunities/opp_x') ? json(200, { ...item(9), member_show_id: 'shw_other' }) : undefined));
    expect((await agent.post('/api/opportunities/opp_x/action').send({ action: 'save' })).status).toBe(404);
  });

  it('ENGINE=legacy keeps the old tag-overlap scorer and never calls the engine', async () => {
    config.engine = 'legacy';
    const agent = await login('podcaster@podbae.local', 'demo123');
    const calls = fakeAi(() => list([item(1)]));
    const r = await agent.get('/api/member/matches');
    expect(r.body.engine).toBe('legacy');
    expect(r.body.opportunities).toBeUndefined();
    expect(calls.some((c) => c.url.includes('/v1/opportunities'))).toBe(false);
  });

  it('engine admin routes are admin-only', async () => {
    fakeAi(() => list([]), (url) => (url.includes('/admin/engine/metrics') ? json(200, { scoring_version: 'fit-draft-v1' }) : undefined));
    const user = await login('podcaster@podbae.local', 'demo123');
    expect((await user.get('/api/admin/engine/metrics')).status).toBe(403);
    expect((await request(app).post('/api/admin/engine/regenerate').send({ showId: 'shw_me' })).status).toBe(401);
    const admin = await login('admin@podbae.local', 'admin123');
    expect((await admin.get('/api/admin/engine/metrics')).body.scoringVersion).toBe('fit-draft-v1');
  });
});
