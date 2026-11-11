// Layer 1 wiring. Responses here are passed through RAW (snake_case, same as the AI service contract in
// packages/contracts/src/intelligence.ts) so the global camelCase wrapper does not rename profile field keys.
import { CreatorProfileSchema } from '@podbae/contracts';
import { Router, type Response } from 'express';
import { z } from 'zod';
import { q, q1 } from '../db/client.js';
import { HttpError, h, parse } from '../lib.js';
import { requireAdmin, requireAuth } from '../middleware/auth.js';
import { IntelDown, intel, publicProfile } from '../services/intel.js';

export const intelRouter = Router();

const raw = (res: Response, status: number, body: unknown) => res.status(status).type('json').send(JSON.stringify(body));

/** Start (or re-use) ingestion for a member's podcast and remember the link. Never throws if the AI service is down. */
export async function kickIntelIngest(podcastId: number, userId: number, rssUrl: string) {
  await q(`INSERT INTO intel_links (podcast_id, rss_url) VALUES ($1,$2)
           ON CONFLICT (podcast_id) DO UPDATE SET rss_url = EXCLUDED.rss_url, updated_at = now()`, [podcastId, rssUrl]);
  try {
    const r = await intel('/ingest/rss', { json: { rss_url: rssUrl, user_id: String(userId) } });
    if (r.status === 202) {
      await q('UPDATE intel_links SET last_job_id=$1, intel_show_id=COALESCE($2, intel_show_id), updated_at=now() WHERE podcast_id=$3',
        [r.body.job_id, r.body.show_id ?? null, podcastId]);
      return { ok: true as const, jobId: r.body.job_id as string, status: 202 };
    }
    return { ok: false as const, status: r.status, error: r.body?.detail ?? 'AI service rejected the feed' };
  } catch (e) {
    if (e instanceof IntelDown) {
      await q(`INSERT INTO ingestion_jobs (source, params, status, error) VALUES ('rss',$1,'pending','AI service down at submit')`,
        [JSON.stringify({ podcastId, rssUrl })]);
      return { ok: false as const, status: 503, error: 'AI service unavailable; your feed is saved and will be ingested when it is back.' };
    }
    throw e;
  }
}

async function myLink(userId: number) {
  const p = await q1('SELECT id, name, rss_url FROM podcasts WHERE owner_user_id = $1 ORDER BY id LIMIT 1', [userId]);
  if (!p) throw new HttpError(404, 'Create your podcast first');
  const link = await q1('SELECT * FROM intel_links WHERE podcast_id = $1', [p.id]);
  return { podcast: p, link };
}

/** Resolve the intel show id for a member, via the job result when the link is not yet filled in. */
async function resolveShowId(link: any): Promise<string | null> {
  if (!link) return null;
  if (link.intel_show_id) return link.intel_show_id;
  if (link.last_job_id) {
    try {
      const j = await intel(`/jobs/${link.last_job_id}`);
      const sid = j.body?.show_id;
      if (sid) { await q('UPDATE intel_links SET intel_show_id=$1, updated_at=now() WHERE id=$2', [sid, link.id]); return sid; }
    } catch { /* service down */ }
  }
  if (link.rss_url) {
    try {
      const r = await intel(`/shows/by-feed?url=${encodeURIComponent(link.rss_url)}`);
      if (r.status === 200) { await q('UPDATE intel_links SET intel_show_id=$1, updated_at=now() WHERE id=$2', [r.body.show_id, link.id]); return r.body.show_id; }
    } catch { /* service down */ }
  }
  return null;
}

// ---- legacy route from the MVP, now real ----
intelRouter.post('/api/agent/ingest-rss', requireAuth, h(async (req, res) => {
  const { rssUrl } = parse(z.object({ rssUrl: z.string().url() }), req.body);
  const { podcast } = await myLink(req.user!.id);
  const taken = await q1('SELECT id FROM podcasts WHERE rss_url = $1 AND id <> $2', [rssUrl, podcast.id]);
  if (taken) throw new HttpError(409, 'That RSS feed is already linked to another podcast');
  await q('UPDATE podcasts SET rss_url = $1, updated_at = now() WHERE id = $2', [rssUrl, podcast.id]);
  const r = await kickIntelIngest(podcast.id, req.user!.id, rssUrl);
  if (!r.ok && r.status === 422) throw new HttpError(422, String(r.error));
  raw(res, 202, { status: r.ok ? 'queued' : 'queued_locally', job_id: r.ok ? r.jobId : null, podcast_id: podcast.id, ai_available: r.ok, note: r.ok ? undefined : r.error });
}));

// ---- member: my intelligence ----
intelRouter.get('/api/intel/my/status', requireAuth, h(async (req, res) => {
  const { podcast, link } = await myLink(req.user!.id);
  let job = null; let aiUp = true;
  if (link?.last_job_id) {
    try { const j = await intel(`/jobs/${link.last_job_id}`); job = j.status === 200 ? j.body : null; } catch { aiUp = false; }
  }
  raw(res, 200, { podcast_id: podcast.id, rss_url: link?.rss_url ?? podcast.rss_url ?? null, linked: !!link, show_id: link?.intel_show_id ?? job?.show_id ?? null, job, ai_up: aiUp });
}));

intelRouter.get('/api/intel/my/profile', requireAuth, h(async (req, res) => {
  const { link } = await myLink(req.user!.id);
  if (!link) return raw(res, 404, { error: 'not_connected', message: 'Connect your RSS feed to build your intelligence profile.' });
  const sid = await resolveShowId(link);
  try {
    if (!sid) {
      // distinguishes "still processing" from "service down" (the latter falls through to the cached/503 handling below)
      const j = link.last_job_id ? await intel(`/jobs/${link.last_job_id}`) : (await intel('/health', { timeoutMs: 3000 }), null);
      return raw(res, 202, { error: 'processing', message: 'Your feed is still being processed.', job: j?.body ?? null });
    }
    const r = await intel(`/shows/${sid}/profile`);
    if (r.status !== 200) return raw(res, r.status, r.body);
    await q('UPDATE intel_links SET profile = $1, profile_cached_at = now(), updated_at = now() WHERE id = $2', [JSON.stringify(r.body), link.id]);
    return raw(res, 200, { profile: r.body, outdated: false, cached_at: null });
  } catch (e) {
    if (!(e instanceof IntelDown)) throw e;
    if (link.profile) return raw(res, 200, { profile: link.profile, outdated: true, cached_at: link.profile_cached_at, message: 'The intelligence service is unreachable. Showing your last saved profile; it may be outdated.' });
    return raw(res, 503, { error: 'ai_unavailable', message: 'The intelligence service is unreachable and no saved profile exists yet.' });
  }
}));

intelRouter.post('/api/intel/my/refresh', requireAuth, h(async (req, res) => {
  const { link } = await myLink(req.user!.id);
  const sid = await resolveShowId(link);
  if (!sid) throw new HttpError(404, 'No ingested show yet');
  try {
    const r = await intel(`/shows/${sid}/refresh?force=true&user_id=${req.user!.id}`, { method: 'POST' });
    if (r.status === 202) await q('UPDATE intel_links SET last_job_id=$1, updated_at=now() WHERE id=$2', [r.body.job_id, link.id]);
    raw(res, r.status, r.body);
  } catch (e) { if (e instanceof IntelDown) throw new HttpError(503, 'AI service unavailable'); throw e; }
}));

intelRouter.put('/api/intel/my/creator-profile', requireAuth, h(async (req, res) => {
  const body = parse(CreatorProfileSchema, req.body ?? {});
  const { link } = await myLink(req.user!.id);
  const sid = await resolveShowId(link);
  if (!sid) throw new HttpError(404, 'Connect your RSS feed first');
  try {
    const r = await intel(`/shows/${sid}/creator-profile`, { method: 'PUT', json: { ...body, user_id: String(req.user!.id) } });
    raw(res, r.status, r.body);
  } catch (e) { if (e instanceof IntelDown) throw new HttpError(503, 'AI service unavailable'); throw e; }
}));

const UploadBody = z.object({ filename: z.string().min(1).max(200), csv: z.string().min(1), mapping: z.record(z.any()).optional() });
intelRouter.post('/api/intel/my/audience-upload', requireAuth, h(async (req, res) => {
  const b = parse(UploadBody, req.body);
  const { link } = await myLink(req.user!.id);
  const sid = await resolveShowId(link);
  if (!sid) throw new HttpError(404, 'Connect your RSS feed first');
  const form = new FormData();
  form.append('file', new Blob([b.csv], { type: 'text/csv' }), b.filename);
  form.append('user_id', String(req.user!.id));
  if (b.mapping) form.append('mapping', JSON.stringify(b.mapping));
  try {
    const r = await intel(`/shows/${sid}/audience-upload`, { form });
    raw(res, r.status === 422 ? 422 : r.status, r.status === 422 ? { error: r.body?.detail ?? 'Invalid file' } : r.body);
  } catch (e) { if (e instanceof IntelDown) throw new HttpError(503, 'AI service unavailable'); throw e; }
}));

// ---- generic job poll (any logged-in user; job ids are unguessable and carry no personal data) ----
intelRouter.get('/api/intel/jobs/:id', requireAuth, h(async (req, res) => {
  try { const r = await intel(`/jobs/${encodeURIComponent(req.params.id)}`); raw(res, r.status, r.body); }
  catch (e) { if (e instanceof IntelDown) return raw(res, 503, { error: 'ai_unavailable' }); throw e; }
}));

// ---- public: discover + public profile (no audience.* / creator.* fields) ----
intelRouter.get('/api/intel/shows', h(async (req, res) => {
  const qs = new URLSearchParams();
  for (const k of ['q', 'category', 'language', 'activity', 'limit', 'offset']) if (req.query[k]) qs.set(k, String(req.query[k]));
  try { const r = await intel(`/shows?${qs}`); raw(res, r.status, r.body); }
  catch (e) { if (e instanceof IntelDown) return raw(res, 200, { total: 0, shows: [], ai_down: true }); throw e; }
}));
intelRouter.get('/api/intel/shows/:id/profile', h(async (req, res) => {
  try {
    const r = await intel(`/shows/${encodeURIComponent(req.params.id)}/profile?refresh=false`);
    raw(res, r.status, r.status === 200 ? publicProfile(r.body) : r.body);
  } catch (e) { if (e instanceof IntelDown) return raw(res, 503, { error: 'ai_unavailable' }); throw e; }
}));
intelRouter.get('/api/intel/shows/:id/similar', h(async (req, res) => {
  const space = req.query.space === 'style' ? 'style' : 'content';
  try { const r = await intel(`/shows/${encodeURIComponent(req.params.id)}/similar?space=${space}&limit=5`); raw(res, r.status, r.body); }
  catch (e) { if (e instanceof IntelDown) return raw(res, 503, { error: 'ai_unavailable' }); throw e; }
}));
intelRouter.get('/api/intel/health', h(async (_req, res) => {
  try { const r = await intel('/health', { timeoutMs: 3000 }); raw(res, 200, { up: r.status === 200, ...r.body }); }
  catch { raw(res, 200, { up: false }); }
}));

// ---- admin dashboards + controls ----
const adminGet = (path: string, target: string) =>
  intelRouter.get(path, requireAdmin, h(async (req, res) => {
    const qs = new URLSearchParams(req.query as Record<string, string>).toString();
    try { const r = await intel(`${target}${qs ? `?${qs}` : ''}`); raw(res, r.status, r.body); }
    catch (e) { if (e instanceof IntelDown) return raw(res, 503, { error: 'ai_unavailable' }); throw e; }
  }));
adminGet('/api/admin/intel/coverage', '/admin/coverage');
adminGet('/api/admin/intel/costs', '/admin/costs');
adminGet('/api/admin/intel/jobs', '/admin/jobs');

intelRouter.post('/api/admin/intel/discover', requireAdmin, h(async (req, res) => {
  const b = parse(z.object({ query: z.string().min(1), limit: z.number().int().min(1).max(100).default(25) }), req.body);
  try { const r = await intel('/ingest/discover', { json: b }); raw(res, r.status, r.body); }
  catch (e) { if (e instanceof IntelDown) throw new HttpError(503, 'AI service unavailable'); throw e; }
}));
intelRouter.post('/api/admin/intel/ingest', requireAdmin, h(async (req, res) => {
  const b = parse(z.object({ rssUrl: z.string().url(), force: z.boolean().optional() }), req.body);
  try { const r = await intel('/ingest/rss', { json: { rss_url: b.rssUrl, force: b.force } }); raw(res, r.status, r.body); }
  catch (e) { if (e instanceof IntelDown) throw new HttpError(503, 'AI service unavailable'); throw e; }
}));
