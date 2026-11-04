import { SwipeSchema, TIER_CONFIG } from '@podbae/contracts';
import { Router } from 'express';
import { z } from 'zod';
import { q, q1 } from '../db/client.js';
import { config } from '../config.js';
import { HttpError, h, parse } from '../lib.js';
import { requireAuth } from '../middleware/auth.js';
import { generatePredictions, runMatching } from '../services/matching.js';
import { getPaymentProvider } from '../services/payments.js';
// (tier/quota helpers below)
import { applyMatchLimit, quota, tierConfig } from '../services/tiers.js';

export const memberRouter = Router();
const A = requireAuth;

// ---------- membership / tier / billing ----------
memberRouter.get('/api/membership', A, h(async (req, res) => {
  res.json({ tier: req.user!.tier, price: TIER_CONFIG[req.user!.tier as keyof typeof TIER_CONFIG]?.price ?? null,
    features: tierConfig(req.user!.tier), plans: TIER_CONFIG });
}));
memberRouter.get('/api/tier/config', A, h(async (req, res) => {
  const { tier, quotaUsed, quotaLimit, matchesPerDay, features } = await quota(req.user!.id, req.user!.tier);
  res.json({ tier, quotaUsed, quotaLimit, matchesPerDay, features });
}));
memberRouter.get('/api/tier/can-swipe', A, h(async (req, res) => {
  const { canSwipe, quotaUsed, quotaLimit } = await quota(req.user!.id, req.user!.tier);
  res.json({ canSwipe, quotaUsed, quotaLimit });
}));
const TierBody = z.object({ tier: z.enum(['date', 'commit']) });
// Step 1: open a (mock) checkout session -> client navigates to checkoutUrl (/mock-checkout)
memberRouter.post('/api/create-checkout', A, h(async (req, res) => {
  const { tier } = parse(TierBody, req.body);
  res.json(await getPaymentProvider().createCheckout({ userId: req.user!.id, email: req.user!.email, tier }));
}));
// Step 2: the mock checkout page "pays" -> upgrades the tier locally
memberRouter.post('/api/mock-checkout/complete', A, h(async (req, res) => {
  const { tier } = parse(TierBody, req.body);
  if (!(await getPaymentProvider().verifyPayment(req.user!.id, tier)))
    throw new HttpError(400, 'No open checkout for this plan. Start again from the dashboard.');
  await q('UPDATE users SET tier = $1 WHERE id = $2', [tier, req.user!.id]);
  await q(`INSERT INTO notifications (user_id, type, title, body) VALUES ($1,'billing',$2,'Mock checkout complete.')`,
    [req.user!.id, `Upgraded to ${tier}`]);
  res.json({ ok: true, tier });
}));

// ---------- profile / goals / public profile ----------
memberRouter.get('/api/member/profile', A, h(async (req, res) => {
  res.json({ user: req.user,
    podcast: await q1('SELECT * FROM podcasts WHERE owner_user_id = $1 ORDER BY id LIMIT 1', [req.user!.id]) ?? null });
}));
const ProfileUpdate = z.object({
  name: z.string().min(1).optional(),
  podcast: z.object({
    name: z.string().min(1).optional(), description: z.string().optional(),
    categories: z.array(z.string()).optional(), location: z.string().optional(),
    vibeTags: z.array(z.string()).optional(), toneTags: z.array(z.string()).optional(),
    collaborationTypes: z.array(z.string()).optional(), audienceSummary: z.string().optional(),
    rssUrl: z.string().url().optional(),
  }).optional(),
});
memberRouter.put('/api/member/profile', A, h(async (req, res) => {
  const b = parse(ProfileUpdate, req.body);
  if (b.name) await q('UPDATE users SET name = $1 WHERE id = $2', [b.name, req.user!.id]);
  if (b.podcast) {
    const p = b.podcast;
    await q(
      `UPDATE podcasts SET name=COALESCE($1,name), description=COALESCE($2,description),
         categories=COALESCE($3,categories), location=COALESCE($4,location), vibe_tags=COALESCE($5,vibe_tags),
         tone_tags=COALESCE($6,tone_tags), collaboration_types=COALESCE($7,collaboration_types),
         audience_summary=COALESCE($8,audience_summary), rss_url=COALESCE($9,rss_url), updated_at=now()
       WHERE owner_user_id=$10`,
      [p.name ?? null, p.description ?? null, p.categories ?? null, p.location ?? null, p.vibeTags ?? null,
       p.toneTags ?? null, p.collaborationTypes ?? null, p.audienceSummary ?? null, p.rssUrl ?? null, req.user!.id]);
  }
  res.json({ ok: true });
}));

memberRouter.get('/api/member/goals', A, h(async (req, res) => {
  const u = await q1('SELECT goals FROM users WHERE id = $1', [req.user!.id]);
  res.json({ goals: u?.goals ?? [] });
}));
memberRouter.put('/api/member/goals', A, h(async (req, res) => {
  const { goals } = parse(z.object({ goals: z.array(z.string()) }), req.body);
  await q('UPDATE users SET goals = $1 WHERE id = $2', [goals, req.user!.id]);
  res.json({ goals });
}));

memberRouter.get('/api/member/public-profile', A, h(async (req, res) => {
  const u = await q1('SELECT public_profile FROM users WHERE id = $1', [req.user!.id]);
  res.json({ profile: u?.public_profile ?? {} });
}));
memberRouter.put('/api/member/public-profile', A, h(async (req, res) => {
  const b = parse(z.object({ enabled: z.boolean().optional(), headline: z.string().optional(), bio: z.string().optional() }), req.body);
  const u = await q1('UPDATE users SET public_profile = public_profile || $1::jsonb WHERE id = $2 RETURNING public_profile',
    [JSON.stringify(b), req.user!.id]);
  res.json({ profile: u.public_profile });
}));
memberRouter.get('/api/member/public-profile/:id', h(async (req, res) => {
  const u = await q1('SELECT id, name, role, public_profile FROM users WHERE id = $1', [req.params.id]);
  if (!u || u.public_profile?.enabled === false) throw new HttpError(404, 'Profile not found');
  const podcast = await q1(
    `SELECT id, name, description, artwork_url, categories, location, vibe_tags, tone_tags, episode_count, verified, demo
     FROM podcasts WHERE owner_user_id = $1 ORDER BY id LIMIT 1`, [u.id]);
  const eps = podcast ? await q(
    `SELECT id, title, published_at, duration_sec FROM episodes WHERE podcast_id = $1 ORDER BY published_at DESC NULLS LAST LIMIT 5`,
    [podcast.id]) : [];
  res.json({ user: { id: u.id, name: u.name, role: u.role }, profile: u.public_profile, podcast: podcast ?? null, episodes: eps });
}));

// ---------- matches ----------
async function rankedMatches(userId: number, tier: string, opts: { type?: string; unswiped?: boolean } = {}) {
  let all = await q(
    `SELECT m.*, EXISTS(SELECT 1 FROM saved_matches s WHERE s.match_id = m.id AND s.user_id = m.user_id) AS saved
     FROM matches m WHERE m.user_id = $1 ORDER BY m.total_score DESC, m.id`, [userId]);
  if (!all.length) {
    await runMatching(userId);
    all = await q(
      `SELECT m.*, false AS saved FROM matches m WHERE m.user_id = $1 ORDER BY m.total_score DESC, m.id`, [userId]);
  }
  const total = all.length;
  let list = applyMatchLimit(all, tier); // tier-enforced daily allowance (flirt = top 3)
  list = list.filter((m) => m.status !== 'dismissed');
  if (opts.type) list = list.filter((m) => m.target_type === opts.type);
  if (opts.unswiped) {
    const sw = new Set((await q('SELECT target_user_id FROM swipes WHERE user_id = $1', [userId])).map((r) => r.target_user_id));
    list = list.filter((m) => m.target_user_id && !sw.has(m.target_user_id));
  }
  return { matches: list, total, limited: list.length < total };
}

memberRouter.get('/api/member/matches', A, h(async (req, res) => {
  const r = await rankedMatches(req.user!.id, req.user!.tier,
    { type: req.query.type as string | undefined, unswiped: req.query.unswiped === '1' });
  res.json({ ...r, tier: req.user!.tier, matchesPerDay: tierConfig(req.user!.tier).matchesPerDay });
}));
memberRouter.get('/api/matches', A, h(async (req, res) => {
  const r = await rankedMatches(req.user!.id, req.user!.tier, { type: req.query.type as string | undefined });
  res.json(r);
}));
memberRouter.get('/api/matches/relationships', A, h(async (req, res) => {
  res.json({ relationships: await q(
    `SELECT c.id AS conversation_id, u.id AS user_id, u.name, u.role, c.created_at
     FROM conversations c JOIN users u ON u.id = CASE WHEN c.user_a = $1 THEN c.user_b ELSE c.user_a END
     WHERE c.user_a = $1 OR c.user_b = $1 ORDER BY c.created_at DESC`, [req.user!.id]) });
}));
memberRouter.get('/api/matches/:id', A, h(async (req, res) => {
  const m = await q1('SELECT * FROM matches WHERE id = $1 AND user_id = $2', [req.params.id, req.user!.id]);
  if (!m) throw new HttpError(404, 'Match not found');
  res.json({ match: m });
}));
memberRouter.post('/api/matches/action', A, h(async (req, res) => {
  const b = parse(z.object({ matchId: z.number().int(), action: z.enum(['save', 'unsave', 'dismiss', 'view']) }), req.body);
  const m = await q1('SELECT id FROM matches WHERE id = $1 AND user_id = $2', [b.matchId, req.user!.id]);
  if (!m) throw new HttpError(404, 'Match not found');
  if (b.action === 'save') await q('INSERT INTO saved_matches (user_id, match_id) VALUES ($1,$2) ON CONFLICT DO NOTHING', [req.user!.id, b.matchId]);
  else if (b.action === 'unsave') await q('DELETE FROM saved_matches WHERE user_id=$1 AND match_id=$2', [req.user!.id, b.matchId]);
  else await q('UPDATE matches SET status = $1 WHERE id = $2', [b.action === 'dismiss' ? 'dismissed' : 'viewed', b.matchId]);
  res.json({ ok: true });
}));
memberRouter.post('/api/run-enhanced-matching', A, h(async (req, res) => {
  const bodyUser = Number(req.body?.userId);
  const uid = req.user!.role === 'admin' && bodyUser ? bodyUser : req.user!.id; // admins may target a user
  const r = await runMatching(uid);
  const predictions = await generatePredictions(uid);
  res.json({ ...r, userId: uid, predictionsCreated: predictions });
}));

// ---------- saved ----------
memberRouter.get('/api/member/saved-matches', A, h(async (req, res) => {
  res.json({ matches: await q(
    `SELECT m.*, true AS saved FROM saved_matches s JOIN matches m ON m.id = s.match_id
     WHERE s.user_id = $1 ORDER BY s.created_at DESC`, [req.user!.id]) });
}));
const MatchIdBody = z.object({ matchId: z.number().int() });
memberRouter.post('/api/member/save-match', A, h(async (req, res) => {
  const { matchId } = parse(MatchIdBody, req.body);
  const m = await q1('SELECT id FROM matches WHERE id=$1 AND user_id=$2', [matchId, req.user!.id]);
  if (!m) throw new HttpError(404, 'Match not found');
  await q('INSERT INTO saved_matches (user_id, match_id) VALUES ($1,$2) ON CONFLICT DO NOTHING', [req.user!.id, matchId]);
  res.json({ ok: true });
}));
memberRouter.post('/api/member/unsave-match', A, h(async (req, res) => {
  const { matchId } = parse(MatchIdBody, req.body);
  await q('DELETE FROM saved_matches WHERE user_id=$1 AND match_id=$2', [req.user!.id, matchId]);
  res.json({ ok: true });
}));

// ---------- swipe ----------
memberRouter.post('/api/member/swipe', A, h(async (req, res) => {
  const b = parse(SwipeSchema, req.body);
  const uid = req.user!.id;
  if (b.targetUserId === uid) throw new HttpError(400, 'Cannot swipe on yourself');
  const target = await q1('SELECT id, name, demo FROM users WHERE id = $1', [b.targetUserId]);
  if (!target) throw new HttpError(404, 'Target user not found');
  const qt = await quota(uid, req.user!.tier);
  if (!qt.canSwipe) throw new HttpError(403, 'Daily swipe limit reached', { code: 'quota_exceeded', ...qt });

  await q(`INSERT INTO swipes (user_id, target_user_id, direction) VALUES ($1,$2,$3)
           ON CONFLICT (user_id, target_user_id) DO UPDATE SET direction = EXCLUDED.direction, created_at = now()`,
    [uid, b.targetUserId, b.direction]);
  await q(`UPDATE matches SET status = $1 WHERE user_id = $2 AND target_user_id = $3`,
    [b.direction === 'right' ? 'liked' : 'passed', uid, b.targetUserId]);

  let mutualMatch = false;
  let conversationId: number | null = null;
  if (b.direction === 'right') {
    const back = await q1(`SELECT 1 FROM swipes WHERE user_id = $1 AND target_user_id = $2 AND direction = 'right'`, [b.targetUserId, uid]);
    // LOCAL MOCK: seeded/demo accounts "like back" automatically so mutual matches are demoable.
    mutualMatch = !!back || (config.demoAutoLike && target.demo === true);
    if (mutualMatch) {
      const [a, c] = uid < b.targetUserId ? [uid, b.targetUserId] : [b.targetUserId, uid];
      const conv = await q1(
        `INSERT INTO conversations (user_a, user_b) VALUES ($1,$2)
         ON CONFLICT (user_a, user_b) DO UPDATE SET user_a = EXCLUDED.user_a RETURNING id`, [a, c]);
      conversationId = conv.id;
      await q(`INSERT INTO notifications (user_id, type, title, body) VALUES
               ($1,'match',$2,'Say hello in Messages.'), ($3,'match',$4,'Say hello in Messages.')`,
        [uid, `It's a Match with ${target.name}!`, b.targetUserId, `It's a Match with ${req.user!.name ?? 'a new partner'}!`]);
    }
  }
  res.json({ mutualMatch, conversationId });
}));

// ---------- predictions ----------
memberRouter.get('/api/predictions', A, h(async (req, res) => {
  const uid = req.user!.id;
  const count = await q1<{ n: number }>('SELECT count(*)::int AS n FROM predictions WHERE user_id = $1', [uid]);
  if (!count?.n) {
    if (!(await q1('SELECT 1 FROM matches WHERE user_id = $1 LIMIT 1', [uid]))) await runMatching(uid);
    await generatePredictions(uid);
  }
  const status = req.query.status as string | undefined;
  let rows = await q(
    `SELECT * FROM predictions WHERE user_id = $1 ${status ? 'AND status = $2' : ''} ORDER BY score DESC, id`,
    status ? [uid, status] : [uid]);
  const cfg = tierConfig(req.user!.tier);
  // revenue (sponsor) recommendations: flirt none, date limited, commit+ all
  let lockedRevenue = 0;
  if (cfg.revenueRecs >= 0) {
    let seen = 0;
    rows = rows.filter((p) => {
      if (p.type !== 'sponsor_opportunity') return true;
      if (seen < cfg.revenueRecs) { seen++; return true; }
      lockedRevenue++;
      return false;
    });
  }
  if (cfg.predictionsLimit >= 0) rows = rows.slice(0, cfg.predictionsLimit);
  // opportunity forecasting: commit+ only
  let forecast: unknown = null;
  if (cfg.forecasting) {
    const f = await q1(
      `SELECT count(*)::int AS open_opportunities,
              COALESCE((SELECT sum(c.budget_min) FROM matches m JOIN campaigns c ON c.advertiser_id = m.target_id
                        WHERE m.user_id = $1 AND m.target_type = 'sponsor' AND m.total_score >= 40), 0)::int AS sponsor_budget_floor
       FROM predictions WHERE user_id = $1 AND status IN ('new','saved')`, [uid]);
    forecast = f;
  }
  res.json({ predictions: rows, lockedRevenue, forecast, forecastLocked: !cfg.forecasting });
}));
memberRouter.post('/api/predictions/:id/action', A, h(async (req, res) => {
  const { action } = parse(z.object({ action: z.enum(['save', 'dismiss', 'act']) }), req.body);
  const status = { save: 'saved', dismiss: 'dismissed', act: 'acted' }[action];
  const p = await q1('UPDATE predictions SET status = $1 WHERE id = $2 AND user_id = $3 RETURNING *', [status, req.params.id, req.user!.id]);
  if (!p) throw new HttpError(404, 'Prediction not found');
  res.json({ prediction: p });
}));

// ---------- insights / reach ----------
memberRouter.get('/api/member/insights', A, h(async (req, res) => {
  const uid = req.user!.id;
  const byType = await q(`SELECT target_type, count(*)::int AS n, round(avg(total_score)::numeric,1)::float AS avg_score
                          FROM matches WHERE user_id = $1 GROUP BY target_type ORDER BY target_type`, [uid]);
  const saved = await q1<{ n: number }>('SELECT count(*)::int AS n FROM saved_matches WHERE user_id = $1', [uid]);
  const mutual = await q1<{ n: number }>('SELECT count(*)::int AS n FROM conversations WHERE user_a = $1 OR user_b = $1', [uid]);
  const best = await q(`SELECT id, target_type, target_snapshot->>'name' AS name, total_score FROM matches
                        WHERE user_id = $1 ORDER BY total_score DESC LIMIT 3`, [uid]);
  res.json({ byType, savedCount: saved?.n ?? 0, mutualCount: mutual?.n ?? 0, topMatches: best });
}));
memberRouter.get('/api/member/reach-estimate', A, h(async (req, res) => {
  // Derived only from real rows: no invented audience numbers.
  const uid = req.user!.id;
  const r = await q1(
    `SELECT count(*) FILTER (WHERE target_type='podcast')::int AS partner_shows,
            count(*) FILTER (WHERE target_type='sponsor')::int AS sponsors,
            count(*) FILTER (WHERE target_type='guest')::int AS guests,
            count(*) FILTER (WHERE target_type='venue')::int AS venues
     FROM matches WHERE user_id = $1 AND total_score >= 40`, [uid]);
  const budget = await q1(
    `SELECT COALESCE(sum(c.budget_min),0)::int AS floor FROM matches m
     JOIN campaigns c ON c.advertiser_id = m.target_id WHERE m.user_id = $1 AND m.target_type='sponsor' AND m.total_score >= 40`, [uid]);
  const ep = await q1('SELECT episode_count FROM podcasts WHERE owner_user_id = $1 LIMIT 1', [uid]);
  res.json({ basis: 'matches with score >= 40', ...r, sponsorBudgetFloor: budget?.floor ?? 0, episodeCount: ep?.episode_count ?? 0 });
}));
