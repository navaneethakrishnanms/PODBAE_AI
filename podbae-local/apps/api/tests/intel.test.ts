import request from 'supertest';
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { createApp } from '../src/app.js';
import { initDb, q1 } from '../src/db/client.js';
import { seedDatabase } from '../src/db/seed.js';

const app = createApp();
const login = async (email: string, password: string) => {
  const agent = request.agent(app);
  expect((await agent.post('/api/auth/login').send({ email, password })).status).toBe(200);
  return agent;
};
const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });

const PROFILE = {
  show_id: 'shw_1', title: 'Real Show', feed_url: 'https://x.test/feed.xml', status: 'partial',
  completeness: { score: 55, by_group: {}, max: 100 }, missing: [], improve: [{ code: 'upload_audience' }], warnings: [], refresh_job: null,
  feed: { last_fetch_at: null, last_fetch_ok: true, last_error: null }, generated_at: 'now', trust_note: '',
  fields: {
    avg_episode_minutes: { value: 31, data_tier: 'verified', source: { name: 'rss', kind: 'rss' }, fetched_at: 'now' },
    'audience.top_countries': { value: { data: [] }, data_tier: 'creator_provided', source: { name: 'creator_upload', kind: 'creator' }, fetched_at: 'now' },
    'creator.goals': { value: ['x'], data_tier: 'creator_provided', source: { name: 'creator_declared', kind: 'creator' }, fetched_at: 'now' },
  },
};

beforeAll(async () => {
  await initDb();
  await seedDatabase();
});
afterEach(() => vi.unstubAllGlobals());

describe('Layer 1 wiring (AI service mocked at the HTTP boundary)', () => {
  it('ingest-rss requires login and hits /v1/ingest/rss, then profile is cached', async () => {
    expect((await request(app).post('/api/agent/ingest-rss').send({ rssUrl: 'https://x.test/feed.xml' })).status).toBe(401);
    const agent = await login('podcaster@podbae.local', 'demo123');
    const calls: string[] = [];
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      calls.push(`${init?.method ?? 'GET'} ${url}`);
      if (url.endsWith('/v1/ingest/rss')) return json(202, { job_id: 'job_abc', status: 'queued', show_id: null });
      if (url.includes('/v1/jobs/job_abc')) return json(200, { id: 'job_abc', status: 'succeeded', percent: 100, show_id: 'shw_1', stages_done: [] });
      if (url.includes('/v1/shows/shw_1/profile')) return json(200, PROFILE);
      return json(404, {});
    }));
    const r = await agent.post('/api/agent/ingest-rss').send({ rssUrl: 'https://x.test/feed.xml' });
    expect(r.status).toBe(202);
    expect(r.body).toMatchObject({ status: 'queued', job_id: 'job_abc', ai_available: true });
    expect(calls[0]).toMatch(/^POST http:\/\/[^/]+\/v1\/ingest\/rss$/);

    const st = await agent.get('/api/intel/my/status');
    expect(st.body).toMatchObject({ linked: true, show_id: 'shw_1' });
    expect(st.body.job.percent).toBe(100);

    const p = await agent.get('/api/intel/my/profile');
    expect(p.status).toBe(200);
    expect(p.body.outdated).toBe(false);
    expect(p.body.profile.fields.avg_episode_minutes.value).toBe(31); // keys stay snake_case (not camelised)
  });

  it('serves the last cached profile with an "outdated" flag when the AI service is down', async () => {
    const agent = await login('podcaster@podbae.local', 'demo123');
    vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('connect ECONNREFUSED'); }));
    const p = await agent.get('/api/intel/my/profile');
    expect(p.status).toBe(200);
    expect(p.body.outdated).toBe(true);
    expect(p.body.cached_at).toBeTruthy();
    expect(p.body.profile.title).toBe('Real Show');
    expect(p.body.message).toMatch(/may be outdated/);
  });

  it('ingest-rss degrades gracefully when the AI service is down (URL saved, job queued locally)', async () => {
    const agent = await login('brand@podbae.local', 'demo123').catch(() => null);
    expect(agent).toBeTruthy();
    const pod = request.agent(app);
    const reg = await pod.post('/api/auth/register').send({ email: 'rss@test.local', password: 'secret123', name: 'Rss', role: 'podcaster' });
    expect(reg.status).toBe(201);
    await pod.post('/api/submissions').send({ showName: 'RSS Show', categories: ['Comedy'], vibeTags: ['Casual'], toneTags: ['Warm'], collaborationTypes: ['Guest Swap'] });
    vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('ECONNREFUSED'); }));
    const r = await pod.post('/api/agent/ingest-rss').send({ rssUrl: 'https://offline.test/feed.xml' });
    expect(r.status).toBe(202);
    expect(r.body).toMatchObject({ status: 'queued_locally', ai_available: false });
    const noProfile = await pod.get('/api/intel/my/profile');
    expect(noProfile.status).toBe(503);
    expect((await q1('SELECT rss_url FROM podcasts WHERE name = $1', ['RSS Show'])).rss_url).toBe('https://offline.test/feed.xml');
  });

  it('public profile never exposes creator audience data or creator-declared fields', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => json(200, PROFILE)));
    const r = await request(app).get('/api/intel/shows/shw_1/profile');
    expect(r.status).toBe(200);
    expect(Object.keys(r.body.fields)).toEqual(['avg_episode_minutes']);
    expect(r.body.improve).toEqual([]);
  });

  it('forwards the public show directory and reports ai_down instead of failing', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => json(200, { total: 1, shows: [{ id: 'shw_1', title: 'Real Show' }] })));
    expect((await request(app).get('/api/intel/shows?q=real')).body.total).toBe(1);
    vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('down'); }));
    const down = await request(app).get('/api/intel/shows');
    expect(down.status).toBe(200);
    expect(down.body).toMatchObject({ total: 0, ai_down: true });
  });

  it('admin intel dashboards are admin-only', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => json(200, { connectors: {} })));
    const user = await login('podcaster@podbae.local', 'demo123');
    expect((await user.get('/api/admin/intel/coverage')).status).toBe(403);
    expect((await request(app).get('/api/admin/intel/costs')).status).toBe(401);
    const admin = await login('admin@podbae.local', 'admin123');
    expect((await admin.get('/api/admin/intel/coverage')).status).toBe(200);
  });

  it('audience upload forwards the CSV as multipart and surfaces validation errors', async () => {
    const agent = await login('podcaster@podbae.local', 'demo123');
    let sawForm = false;
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      if (url.includes('/audience-upload')) { sawForm = init?.body instanceof FormData; return json(422, { detail: 'the file has a header but no data rows' }); }
      return json(200, { show_id: 'shw_1' });
    }));
    const r = await agent.post('/api/intel/my/audience-upload').send({ filename: 'a.csv', csv: 'Country,Percent\n' });
    expect(r.status).toBe(422);
    expect(r.body.error).toMatch(/no data rows/);
    expect(sawForm).toBe(true);
  });
});
