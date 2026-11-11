import { CATEGORIES } from '@podbae/contracts';
import { Router } from 'express';
import { z } from 'zod';
import { q, q1 } from '../db/client.js';
import { HttpError, h, parse } from '../lib.js';
import { requireAuth } from '../middleware/auth.js';

export const podcastsRouter = Router();

podcastsRouter.get('/api/podcasts', requireAuth, h(async (req, res) => {
  const all = req.user!.role === 'admin' && req.query.all === '1';
  res.json({ podcasts: await q(
    `SELECT * FROM podcasts ${all ? '' : 'WHERE owner_user_id = $1'} ORDER BY id DESC LIMIT 200`,
    all ? [] : [req.user!.id]) });
}));

const PodcastCreate = z.object({
  name: z.string().min(1), description: z.string().optional(), rssUrl: z.string().url().optional(),
  categories: z.array(z.string()).default([]), location: z.string().optional(),
  vibeTags: z.array(z.string()).default([]), toneTags: z.array(z.string()).default([]),
});
podcastsRouter.post('/api/podcasts', requireAuth, h(async (req, res) => {
  const b = parse(PodcastCreate, req.body);
  const p = await q1(
    `INSERT INTO podcasts (owner_user_id, name, description, rss_url, categories, location, vibe_tags, tone_tags, source)
     VALUES ($1,$2,$3,$4,$5,$6,$7,$8,'manual') RETURNING *`,
    [req.user!.id, b.name, b.description ?? null, b.rssUrl ?? null, b.categories, b.location ?? null, b.vibeTags, b.toneTags]);
  await q(`INSERT INTO data_sources (entity_type, entity_id, source, ref) VALUES ('podcast',$1,'manual','user-submitted')`, [p.id]);
  res.status(201).json({ podcast: p });
}));

podcastsRouter.get('/api/member/podcast-episodes', requireAuth, h(async (req, res) => {
  res.json({ episodes: await q(
    `SELECT e.* FROM episodes e JOIN podcasts p ON p.id = e.podcast_id
     WHERE p.owner_user_id = $1 ORDER BY e.published_at DESC NULLS LAST LIMIT 100`, [req.user!.id]) });
}));

// POST /api/agent/ingest-rss lives in routes/intel.ts (Layer 1: real RSS ingestion via the AI service).

// ================= public + search =================
export const publicRouter = Router();

const PUB_COLS = `id, name, description, author, artwork_url, categories, location, episode_count,
  last_episode_at, vibe_tags, tone_tags, topics, audience_summary, verified, demo, source, owner_user_id`;

publicRouter.get('/api/public/directory', h(async (req, res) => {
  const page = Math.max(Number(req.query.page ?? 1), 1);
  const size = 12;
  const where: string[] = [];
  const params: unknown[] = [];
  if (req.query.q) { params.push(`%${req.query.q}%`); where.push(`(name ILIKE $${params.length} OR description ILIKE $${params.length} OR author ILIKE $${params.length})`); }
  if (req.query.category) { params.push(req.query.category); where.push(`$${params.length} = ANY(categories)`); }
  if (req.query.vibe) { params.push(req.query.vibe); where.push(`$${params.length} = ANY(vibe_tags)`); }
  const w = where.length ? `WHERE ${where.join(' AND ')}` : '';
  const total = await q1<{ n: number }>(`SELECT count(*)::int AS n FROM podcasts ${w}`, params);
  const rows = await q(
    `SELECT ${PUB_COLS} FROM podcasts ${w} ORDER BY verified DESC, last_episode_at DESC NULLS LAST, id
     LIMIT ${size} OFFSET ${(page - 1) * size}`, params);
  res.json({ podcasts: rows, page, pageSize: size, total: total?.n ?? 0 });
}));

publicRouter.get('/api/public/directory/filters', h(async (_req, res) => {
  const cats = await q('SELECT DISTINCT unnest(categories) AS v FROM podcasts ORDER BY v');
  const vibes = await q('SELECT DISTINCT unnest(vibe_tags) AS v FROM podcasts ORDER BY v');
  res.json({ categories: cats.map((r) => r.v), vibes: vibes.map((r) => r.v) });
}));

const episodes = (id: unknown) =>
  q(`SELECT id, podcast_id, guid, title, description, published_at, duration_sec, audio_url
     FROM episodes WHERE podcast_id = $1 ORDER BY published_at DESC NULLS LAST LIMIT 50`, [id]);

publicRouter.get('/api/public/directory/:id/episodes', h(async (req, res) => res.json({ episodes: await episodes(req.params.id) })));
publicRouter.get('/api/public/podcast/:id/episodes', h(async (req, res) => res.json({ episodes: await episodes(req.params.id) })));
publicRouter.get('/api/public/podcast/:id', h(async (req, res) => {
  const p = await q1(`SELECT ${PUB_COLS} FROM podcasts WHERE id = $1`, [req.params.id]);
  if (!p) throw new HttpError(404, 'Podcast not found');
  res.json({ podcast: p });
}));
publicRouter.get('/api/public/featured-shows', h(async (_req, res) => {
  res.json({ podcasts: await q(`SELECT ${PUB_COLS} FROM podcasts WHERE featured ORDER BY featured_order, id`) });
}));

// ----- search -----
publicRouter.get('/api/search/genres', h(async (_req, res) => {
  const rows = await q('SELECT DISTINCT unnest(categories) AS v FROM podcasts');
  res.json({ genres: [...new Set<string>([...CATEGORIES, ...rows.map((r) => r.v as string)])].sort() });
}));
publicRouter.get('/api/search/industries', h(async (_req, res) => {
  const rows = await q('SELECT DISTINCT unnest(categories) AS v FROM advertisers');
  res.json({ industries: [...new Set<string>([...CATEGORIES, ...rows.map((r) => r.v as string)])].sort() });
}));
publicRouter.get('/api/search/users', requireAuth, h(async (req, res) => {
  const term = `%${String(req.query.q ?? '')}%`;
  res.json({ users: await q(
    `SELECT id, name, role FROM users WHERE role <> 'admin' AND id <> $1 AND name ILIKE $2 ORDER BY name LIMIT 20`,
    [req.user!.id, term]) });
}));
