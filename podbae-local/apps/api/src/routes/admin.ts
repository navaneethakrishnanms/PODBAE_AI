import { CATEGORIES } from '@podbae/contracts';
import { Router } from 'express';
import { z } from 'zod';
import { q, q1 } from '../db/client.js';
import { HttpError, h, parse } from '../lib.js';
import { requireAdmin } from '../middleware/auth.js';
import { generatePredictions, runMatching } from '../services/matching.js';
import { load as loadWeights } from '../services/weights.js';

export const adminRouter = Router();
adminRouter.use('/api/admin', (req, res, next) => {
  // setup-needed / setup-first-admin are public and handled in auth router before this mounts
  requireAdmin(req, res, next);
});

adminRouter.get('/api/admin/users', h(async (_req, res) => {
  res.json({ users: await q('SELECT id, email, name, role, tier, onboarded, demo, created_at FROM users ORDER BY id') });
}));
adminRouter.get('/api/admin/podcasts', h(async (_req, res) => {
  res.json({ podcasts: await q('SELECT id, name, owner_user_id, source, verified, featured, demo, categories FROM podcasts ORDER BY id') });
}));
adminRouter.post('/api/admin/podcasts/:id/verify', h(async (req, res) => {
  const { verified } = parse(z.object({ verified: z.boolean().default(true) }), req.body ?? {});
  const p = await q1('UPDATE podcasts SET verified = $1 WHERE id = $2 RETURNING id, name, verified', [verified, req.params.id]);
  if (!p) throw new HttpError(404, 'Podcast not found');
  res.json({ podcast: p });
}));
adminRouter.get('/api/admin/directory-status', h(async (_req, res) => {
  const r = await q1(`SELECT count(*)::int AS total, count(*) FILTER (WHERE verified)::int AS verified,
      count(*) FILTER (WHERE demo)::int AS demo, count(*) FILTER (WHERE featured)::int AS featured,
      count(*) FILTER (WHERE enriched_at IS NOT NULL)::int AS enriched FROM podcasts`);
  const bySource = await q('SELECT source, count(*)::int AS n FROM podcasts GROUP BY source');
  res.json({ ...r, bySource });
}));

async function generateFor(userId: number) {
  const m = await runMatching(userId);
  const p = await generatePredictions(userId);
  return { userId, matches: m.count, predictionsCreated: p };
}
adminRouter.post('/api/admin/generate-opportunities', h(async (_req, res) => {
  const users = await q(`SELECT DISTINCT owner_user_id AS id FROM podcasts WHERE owner_user_id IS NOT NULL`);
  const results = [];
  for (const u of users) results.push(await generateFor(u.id));
  res.json({ results });
}));
adminRouter.post('/api/admin/generate-opportunities/:userId', h(async (req, res) => {
  res.json(await generateFor(Number(req.params.userId)));
}));

adminRouter.get('/api/admin/vibe-logic-metrics', h(async (_req, res) => {
  const byType = await q(`SELECT target_type, count(*)::int AS n, round(avg(total_score)::numeric,1)::float AS avg_score,
      round(max(total_score)::numeric,1)::float AS max_score FROM matches GROUP BY target_type ORDER BY target_type`);
  const dist = await q(`SELECT width_bucket(total_score, 0, 100, 5) AS bucket, count(*)::int AS n FROM matches GROUP BY 1 ORDER BY 1`);
  const act = await q(`SELECT status, count(*)::int AS n FROM matches GROUP BY status`);
  const preds = await q(`SELECT status, count(*)::int AS n FROM predictions GROUP BY status`);
  res.json({ engine: 'placeholder-weighted-jaccard', weights: loadWeights().weights, byType, scoreDistribution: dist, matchStatus: act, predictionStatus: preds });
}));
adminRouter.get('/api/admin/vibe-logic-recommendations', h(async (_req, res) => {
  const lowData = await q(`SELECT id, name FROM podcasts WHERE cardinality(vibe_tags) = 0 OR cardinality(categories) = 0 LIMIT 20`);
  const tips = [];
  if (lowData.length) tips.push({ kind: 'data_quality', message: `${lowData.length} podcast(s) lack vibe tags or categories; matching quality suffers.`, podcasts: lowData });
  tips.push({ kind: 'weights', message: 'listenScore weight is 0 until listener data exists (Phase 2+).' });
  res.json({ recommendations: tips });
}));

const C = CATEGORIES;
const TEST_SHOWS: [string, string[], string][] = [
  ['Test Pod: Late Night Chats', [C[1]], 'Chicago, IL'], ['Test Pod: Garden Hour', [C[0]], 'Portland, OR'],
  ['Test Pod: Code & Coffee', [C[3]], 'Austin, TX'], ['Test Pod: History Bites', [C[0]], 'Boston, MA'],
  ['Test Pod: Cold Case Club', [C[2]], 'Nashville, TN'],
];
adminRouter.post('/api/admin/seed-test-podcasts', h(async (_req, res) => {
  let created = 0;
  for (const [name, cats, loc] of TEST_SHOWS) {
    const ex = await q1('SELECT id FROM podcasts WHERE name = $1', [name]);
    if (ex) continue;
    const p = await q1(
      `INSERT INTO podcasts (name, categories, location, vibe_tags, tone_tags, source, demo, description)
       VALUES ($1,$2,$3,'{Casual}','{Warm}','manual',true,'Demo test show (fake).') RETURNING id`, [name, cats, loc]);
    await q(`INSERT INTO data_sources (entity_type, entity_id, source, ref) VALUES ('podcast',$1,'manual','admin:seed-test-podcasts')`, [p.id]);
    created++;
  }
  res.json({ created });
}));

// ----- showcase -----
adminRouter.get('/api/admin/showcase', h(async (_req, res) => {
  res.json({ podcasts: await q('SELECT id, name, featured, featured_order, verified, demo FROM podcasts WHERE featured ORDER BY featured_order, id') });
}));
adminRouter.get('/api/admin/showcase/directory-search', h(async (req, res) => {
  res.json({ podcasts: await q('SELECT id, name, featured, verified FROM podcasts WHERE name ILIKE $1 ORDER BY name LIMIT 25', [`%${req.query.q ?? ''}%`]) });
}));
adminRouter.post('/api/admin/showcase/order', h(async (req, res) => {
  const { ids } = parse(z.object({ ids: z.array(z.number().int()) }), req.body);
  for (const [i, id] of ids.entries()) await q('UPDATE podcasts SET featured_order = $1 WHERE id = $2', [i + 1, id]);
  res.json({ ok: true });
}));
adminRouter.post('/api/admin/showcase/:id/feature', h(async (req, res) => {
  const { featured } = parse(z.object({ featured: z.boolean() }), req.body);
  const p = await q1(
    `UPDATE podcasts SET featured = $1, featured_order = CASE WHEN $1 THEN (SELECT COALESCE(max(featured_order),0)+1 FROM podcasts) ELSE 0 END
     WHERE id = $2 RETURNING id, name, featured, featured_order`, [featured, req.params.id]);
  if (!p) throw new HttpError(404, 'Podcast not found');
  res.json({ podcast: p });
}));

adminRouter.get('/api/admin/partnership-invites', h(async (_req, res) => {
  res.json({ invites: await q('SELECT * FROM partnership_invites ORDER BY created_at DESC') });
}));

// Taddy/directory controls now map to AI-service jobs: see routes/intel.ts (/api/admin/intel/*).
adminRouter.get('/api/admin/ingestion-jobs', h(async (_req, res) => {
  res.json({ jobs: await q('SELECT * FROM ingestion_jobs ORDER BY id DESC LIMIT 50'), note: 'Legacy app-side queue. Live ingestion jobs, coverage and costs: /api/admin/intel/jobs|coverage|costs.' });
}));
