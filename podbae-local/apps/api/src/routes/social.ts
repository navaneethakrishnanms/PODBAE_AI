import { CampaignCreateSchema, ScheduleCreateSchema, websiteDomain } from '@podbae/contracts';
import { Router } from 'express';
import { z } from 'zod';
import { q, q1 } from '../db/client.js';
import { HttpError, h, parse } from '../lib.js';
import { requireAuth, requireRole } from '../middleware/auth.js';
import { aiHeyBae } from '../services/ai.js';
import { runMatching } from '../services/matching.js';
import { tierConfig } from '../services/tiers.js';

export const socialRouter = Router();
const A = requireAuth;

// ---------- chat ----------
async function convoFor(userId: number, id: unknown) {
  const c = await q1('SELECT * FROM conversations WHERE id = $1 AND (user_a = $2 OR user_b = $2)', [id, userId]);
  if (!c) throw new HttpError(404, 'Conversation not found');
  return c;
}

socialRouter.get('/api/chat/conversations', A, h(async (req, res) => {
  const uid = req.user!.id;
  res.json({ conversations: await q(
    `SELECT c.id, u.id AS other_user_id, u.name AS other_name, u.role AS other_role,
       (SELECT body FROM messages m WHERE m.conversation_id = c.id ORDER BY m.created_at DESC, m.id DESC LIMIT 1) AS last_message,
       (SELECT max(created_at) FROM messages m WHERE m.conversation_id = c.id) AS last_message_at,
       (SELECT count(*)::int FROM messages m WHERE m.conversation_id = c.id AND m.sender_id <> $1 AND m.read_at IS NULL) AS unread
     FROM conversations c JOIN users u ON u.id = CASE WHEN c.user_a = $1 THEN c.user_b ELSE c.user_a END
     WHERE c.user_a = $1 OR c.user_b = $1 ORDER BY last_message_at DESC NULLS LAST, c.id DESC`, [uid]) });
}));
socialRouter.get('/api/chat/conversations/:id/messages', A, h(async (req, res) => {
  await convoFor(req.user!.id, req.params.id);
  res.json({ messages: await q('SELECT * FROM messages WHERE conversation_id = $1 ORDER BY created_at, id', [req.params.id]) });
}));
socialRouter.post('/api/chat/conversations/:id/messages', A, h(async (req, res) => {
  const c = await convoFor(req.user!.id, req.params.id);
  const { body } = parse(z.object({ body: z.string().min(1).max(4000) }), req.body);
  const m = await q1('INSERT INTO messages (conversation_id, sender_id, body) VALUES ($1,$2,$3) RETURNING *', [c.id, req.user!.id, body]);
  const other = c.user_a === req.user!.id ? c.user_b : c.user_a;
  await q(`INSERT INTO notifications (user_id, type, title, body) VALUES ($1,'message',$2,$3)`,
    [other, `New message from ${req.user!.name ?? 'a match'}`, body.slice(0, 120)]);
  res.status(201).json({ message: m });
}));
socialRouter.post('/api/chat/conversations/:id/read', A, h(async (req, res) => {
  await convoFor(req.user!.id, req.params.id);
  await q('UPDATE messages SET read_at = now() WHERE conversation_id = $1 AND sender_id <> $2 AND read_at IS NULL', [req.params.id, req.user!.id]);
  res.json({ ok: true });
}));
socialRouter.get('/api/chat/unread-count', A, h(async (req, res) => {
  const r = await q1<{ n: number }>(
    `SELECT count(*)::int AS n FROM messages m JOIN conversations c ON c.id = m.conversation_id
     WHERE (c.user_a = $1 OR c.user_b = $1) AND m.sender_id <> $1 AND m.read_at IS NULL`, [req.user!.id]);
  res.json({ count: r?.n ?? 0 });
}));

// ---------- Hey Bae (commit+ only) ----------
socialRouter.get('/api/hey-bae/messages', A, h(async (req, res) => {
  res.json({ messages: await q('SELECT * FROM hey_bae_messages WHERE user_id = $1 ORDER BY id', [req.user!.id]) });
}));
socialRouter.post('/api/hey-bae/chat', A, h(async (req, res) => {
  const uid = req.user!.id;
  if (!tierConfig(req.user!.tier).heyBae)
    throw new HttpError(403, 'Hey Bae is available on the Commit plan', { code: 'upgrade_required', requiredTier: 'commit' });
  const { message } = parse(z.object({ message: z.string().min(1).max(2000) }), req.body);

  const podcast = await q1('SELECT id, name, description, categories, location, vibe_tags, tone_tags, episode_count FROM podcasts WHERE owner_user_id = $1 LIMIT 1', [uid]);
  const episodes = podcast ? await q('SELECT title, published_at FROM episodes WHERE podcast_id = $1 ORDER BY published_at DESC NULLS LAST LIMIT 5', [podcast.id]) : [];
  let matches = await q(`SELECT target_type, target_id, total_score, target_snapshot->>'name' AS name, explanation
                         FROM matches WHERE user_id = $1 ORDER BY total_score DESC LIMIT 5`, [uid]);
  if (!matches.length && podcast) {
    await runMatching(uid);
    matches = await q(`SELECT target_type, target_id, total_score, target_snapshot->>'name' AS name, explanation
                       FROM matches WHERE user_id = $1 ORDER BY total_score DESC LIMIT 5`, [uid]);
  }
  const history = (await q('SELECT role, content FROM hey_bae_messages WHERE user_id = $1 ORDER BY id DESC LIMIT 10', [uid])).reverse();

  const camel = (m: any) => ({ name: m.name, targetType: m.target_type, targetId: m.target_id, totalScore: m.total_score, explanation: m.explanation });
  const ai = await aiHeyBae({
    message,
    context: { podcast, episodes, matches: matches.map(camel) },
    history,
  });
  await q(`INSERT INTO hey_bae_messages (user_id, role, content) VALUES ($1,'user',$2), ($1,'assistant',$3)`, [uid, message, ai.reply]);
  res.json({ reply: ai.reply, provider: ai.provider });
}));

// ---------- sponsors / campaigns ----------
socialRouter.get('/api/sponsors', h(async (_req, res) => {
  res.json({ sponsors: await q(
    `SELECT a.id, a.org_name, a.org_type, a.description, a.categories, a.vibe_tags, a.location, a.demo,
            (SELECT count(*)::int FROM campaigns c WHERE c.advertiser_id = a.id AND c.status = 'active') AS active_campaigns
     FROM advertisers a ORDER BY a.org_name`) });
}));
socialRouter.get('/api/campaigns', A, h(async (req, res) => {
  if (req.user!.role === 'advertiser') {
    return res.json({ campaigns: await q(
      `SELECT c.* FROM campaigns c JOIN advertisers a ON a.id = c.advertiser_id WHERE a.user_id = $1 ORDER BY c.id DESC`, [req.user!.id]) });
  }
  res.json({ campaigns: await q(
    `SELECT c.*, a.org_name FROM campaigns c JOIN advertisers a ON a.id = c.advertiser_id WHERE c.status='active' ORDER BY c.id DESC`) });
}));
socialRouter.post('/api/campaigns', requireRole('advertiser', 'admin'), h(async (req, res) => {
  const b = parse(CampaignCreateSchema, req.body);
  const adv = await q1('SELECT id FROM advertisers WHERE user_id = $1', [req.user!.id]);
  if (!adv) throw new HttpError(400, 'Complete the advertiser wizard first');
  const c = await q1(
    `INSERT INTO campaigns (advertiser_id, name, description, budget_min, budget_max, categories, vibe_tags, tone_tags, location)
     VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9) RETURNING *`,
    [adv.id, b.name, b.description ?? null, b.budgetMin, b.budgetMax ?? null, b.categories, b.vibeTags, b.toneTags, b.location ?? null]);
  const dom = websiteDomain(b.website);
  if (dom) await q('UPDATE advertisers SET website = $1 WHERE id = $2', [dom, adv.id]);   // company website lives on the advertiser
  res.status(201).json({ campaign: c });
}));

// ---------- schedule (manual sessions, stored in DB) ----------
socialRouter.get('/api/schedule', A, h(async (req, res) => {
  res.json({ sessions: await q('SELECT * FROM scheduled_sessions WHERE user_id = $1 ORDER BY starts_at', [req.user!.id]) });
}));
socialRouter.post('/api/schedule', A, h(async (req, res) => {
  const b = parse(ScheduleCreateSchema, req.body);
  const when = new Date(b.startsAt);
  if (Number.isNaN(when.getTime())) throw new HttpError(400, 'Invalid date');
  const s = await q1('INSERT INTO scheduled_sessions (user_id, title, starts_at, notes) VALUES ($1,$2,$3,$4) RETURNING *',
    [req.user!.id, b.title, when.toISOString(), b.notes ?? null]);
  res.status(201).json({ session: s });
}));
socialRouter.delete('/api/schedule/:id', A, h(async (req, res) => {
  await q('DELETE FROM scheduled_sessions WHERE id = $1 AND user_id = $2', [req.params.id, req.user!.id]);
  res.json({ ok: true });
}));

// ---------- misc ----------
socialRouter.get('/api/listener-recommendations', h(async (_req, res) => {
  res.json({ recommendations: await q(
    `SELECT p.id, p.name, p.description, p.artwork_url, p.categories, p.verified, p.demo,
            (SELECT title FROM episodes e WHERE e.podcast_id = p.id ORDER BY published_at DESC NULLS LAST LIMIT 1) AS latest_episode
     FROM podcasts p ORDER BY p.featured DESC, p.verified DESC, p.last_episode_at DESC NULLS LAST LIMIT 12`) });
}));

socialRouter.get('/api/notifications', A, h(async (req, res) => {
  res.json({ notifications: await q('SELECT * FROM notifications WHERE user_id = $1 ORDER BY id DESC LIMIT 50', [req.user!.id]) });
}));
socialRouter.post('/api/notifications/read-all', A, h(async (req, res) => {
  await q('UPDATE notifications SET read = true WHERE user_id = $1', [req.user!.id]);
  res.json({ ok: true });
}));
socialRouter.post('/api/notifications/:id/read', A, h(async (req, res) => {
  await q('UPDATE notifications SET read = true WHERE id = $1 AND user_id = $2', [req.params.id, req.user!.id]);
  res.json({ ok: true });
}));
