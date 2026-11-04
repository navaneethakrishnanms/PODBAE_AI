import request from 'supertest';
import { beforeAll, describe, expect, it } from 'vitest';
import { createApp } from '../src/app.js';
import { initDb } from '../src/db/client.js';
import { seedDatabase } from '../src/db/seed.js';

const app = createApp();
const login = async (email: string, password: string) => {
  const agent = request.agent(app);
  const r = await agent.post('/api/auth/login').send({ email, password });
  expect(r.status).toBe(200);
  return agent;
};

beforeAll(async () => {
  await initDb();
  await seedDatabase();
});

describe('auth', () => {
  it('register -> me -> logout -> login', async () => {
    const agent = request.agent(app);
    const reg = await agent.post('/api/auth/register').send({ email: 'new@test.local', password: 'secret123', name: 'New Pod', role: 'podcaster' });
    expect(reg.status).toBe(201);
    expect(reg.body.user.passwordHash).toBeUndefined();
    expect((await agent.get('/api/auth/me')).body.user.email).toBe('new@test.local');
    await agent.post('/api/logout');
    expect((await agent.get('/api/auth/me')).status).toBe(401);
    const again = await agent.post('/api/auth/login').send({ email: 'new@test.local', password: 'secret123' });
    expect(again.status).toBe(200);
    expect((await request(app).post('/api/auth/login').send({ email: 'new@test.local', password: 'wrong-pass' })).status).toBe(401);
  });

  it('validates bodies with zod', async () => {
    const r = await request(app).post('/api/auth/register').send({ email: 'nope', password: 'x' });
    expect(r.status).toBe(400);
    expect(r.body.error).toBe('validation_error');
  });

  it('podcaster intake creates an account and matches', async () => {
    const agent = request.agent(app);
    const r = await agent.post('/api/submissions').send({
      account: { email: 'intake@test.local', password: 'secret123', name: 'Intake Host' },
      showName: 'Intake Show', categories: ['Podcaster- Entertainment/ Comedy/ Society & Culture'],
      vibeTags: ['Casual'], toneTags: ['Playful'], location: 'New York, NY',
    });
    expect(r.status).toBe(201);
    expect(r.body.matchesCreated).toBeGreaterThan(0);
    expect((await agent.get('/api/auth/me')).status).toBe(200);
  });
});

describe('tiers & matches', () => {
  it('flirt is limited to 3 matches/day with score breakdowns + explanations', async () => {
    const agent = await login('podcaster@podbae.local', 'demo123');
    const r = await agent.get('/api/member/matches');
    expect(r.status).toBe(200);
    expect(r.body.matches).toHaveLength(3);
    expect(r.body.limited).toBe(true);
    const m = r.body.matches[0];
    expect(m.scoreBreakdown.genreScore).toBeTypeOf('number');
    expect(m.explanation.reasons.length).toBeGreaterThan(0);
    expect((await agent.get('/api/tier/config')).body.tier).toBe('flirt');
  });
});

describe('swipe', () => {
  it('right swipe on a demo user yields a mutual match + conversation', async () => {
    const agent = await login('podcaster@podbae.local', 'demo123');
    const deck = (await agent.get('/api/member/matches?unswiped=1')).body.matches;
    expect(deck.length).toBeGreaterThan(0);
    const swipe = await agent.post('/api/member/swipe').send({ targetUserId: deck[0].targetUserId, direction: 'right' });
    expect(swipe.status).toBe(200);
    expect(swipe.body.mutualMatch).toBe(true);
    const convos = (await agent.get('/api/chat/conversations')).body.conversations;
    expect(convos.length).toBeGreaterThan(0);
    const send = await agent.post(`/api/chat/conversations/${convos[0].id}/messages`).send({ body: 'hello!' });
    expect(send.status).toBe(201);
  });

  it('enforces the flirt swipe quota', async () => {
    const agent = await login('learn@demo.podbae.local', 'demo123'); // flirt
    const users = (await agent.get('/api/search/users?q=Demo')).body.users as { id: number }[];
    let blocked = false;
    for (const u of users.slice(0, 12)) {
      const r = await agent.post('/api/member/swipe').send({ targetUserId: u.id, direction: 'left' });
      if (r.status === 403) { blocked = true; expect(r.body.code).toBe('quota_exceeded'); break; }
    }
    expect(blocked).toBe(true);
  });
});

describe('billing', () => {
  it('mock checkout upgrades flirt -> commit and unlocks Hey Bae', async () => {
    const agent = await login('gridiron@demo.podbae.local', 'demo123'); // flirt
    const locked = await agent.post('/api/hey-bae/chat').send({ message: 'hi' });
    expect(locked.status).toBe(403);
    expect(locked.body.code).toBe('upgrade_required');

    expect((await agent.post('/api/mock-checkout/complete').send({ tier: 'commit' })).status).toBe(400); // no open checkout
    const co = await agent.post('/api/create-checkout').send({ tier: 'commit' });
    expect(co.body.checkoutUrl).toContain('/mock-checkout');
    expect((await agent.post('/api/mock-checkout/complete').send({ tier: 'commit' })).body.tier).toBe('commit');

    expect((await agent.get('/api/tier/config')).body.tier).toBe('commit');
    const chat = await agent.post('/api/hey-bae/chat').send({ message: 'What are my best matches?' });
    expect(chat.status).toBe(200);
    expect(chat.body.reply).toContain('Gridiron Gab');
    expect((await agent.get('/api/hey-bae/messages')).body.messages).toHaveLength(2);
  });
});

describe('admin', () => {
  it('rejects anonymous (401) and non-admin (403); allows admin', async () => {
    expect((await request(app).get('/api/admin/users')).status).toBe(401);
    const pod = await login('podcaster@podbae.local', 'demo123');
    expect((await pod.get('/api/admin/users')).status).toBe(403);
    expect((await pod.post('/api/admin/generate-opportunities')).status).toBe(403);
    const admin = await login('admin@podbae.local', 'admin123');
    expect((await admin.get('/api/admin/users')).body.users.length).toBeGreaterThan(10);
    expect((await admin.post('/api/admin/podcasts/1/verify').send({ verified: true })).body.podcast.verified).toBe(true);
    expect((await admin.get('/api/admin/vibe-logic-metrics')).body.byType.length).toBeGreaterThan(0);
  });
});
