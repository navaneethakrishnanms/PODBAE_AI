// Layer 4 Opportunity Engine routes (podcast partners). Member actions + admin Engine tab + blind pair labels.
import { OpportunityActionSchema } from '@podbae/contracts';
import { Router } from 'express';
import { z } from 'zod';
import { HttpError, h, parse } from '../lib.js';
import { requireAdmin, requireAuth } from '../middleware/auth.js';
import { demoSetup } from '../services/demoMembers.js';
import { IntelDown, intel } from '../services/intel.js';
import { getOpportunities, memberShowId, opportunityAction, syncAdvertisers } from '../services/opportunities.js';

export const opportunitiesRouter = Router();

async function pass(path: string, init?: Parameters<typeof intel>[1]) {
  try {
    const r = await intel(path, init);
    if (r.status === 422) throw new HttpError(400, String(r.body?.detail ?? 'Invalid request'));
    if (r.status >= 400) throw new HttpError(r.status, String(r.body?.detail ?? 'AI service error'));
    return r.body;
  } catch (e) { if (e instanceof IntelDown) throw new HttpError(503, 'AI service unavailable'); throw e; }
}

// ---- member ----
opportunitiesRouter.get('/api/opportunities', requireAuth, h(async (req, res) => {
  res.json(await getOpportunities(req.user!, { kind: req.query.kind === 'sponsor' ? 'sponsor' : 'partner' }));
}));
opportunitiesRouter.get('/api/sponsor-opportunities', requireAuth, h(async (req, res) => {
  res.json(await getOpportunities(req.user!, { kind: 'sponsor' }));
}));
// public "Sponsors seen" for a show (declared / human-reviewed sponsorships only)
opportunitiesRouter.get('/api/intel/shows/:id/sponsors', h(async (req, res) => {
  try {
    const r = await intel(`/shows/${encodeURIComponent(req.params.id)}/sponsors`);
    res.status(r.status).json(r.body);
  } catch (e) { if (e instanceof IntelDown) return res.status(200).json({ sponsors: [], ai_down: true }); throw e; }
}));
opportunitiesRouter.get('/api/intel/my/sponsors', requireAuth, h(async (req, res) => {
  const sid = await memberShowId(req.user!.id);
  if (!sid) return res.json({ sponsors: [], not_connected: true });
  res.json(await pass(`/shows/${encodeURIComponent(sid)}/sponsors`));
}));
opportunitiesRouter.get('/api/opportunities/options', requireAuth, h(async (_req, res) => res.json(await pass('/opportunities/options'))));
opportunitiesRouter.post('/api/opportunities/:id/action', requireAuth, h(async (req, res) => {
  const b = parse(OpportunityActionSchema, req.body ?? {});
  res.json(await opportunityAction(req.user!, req.params.id, b.action, b.reason, b.note));
}));
opportunitiesRouter.get('/api/opportunities/:id/explain', requireAuth, h(async (req, res) => {
  const sid = await memberShowId(req.user!.id);
  const one = await pass(`/opportunities/${encodeURIComponent(req.params.id)}`);
  if (!sid || one.member_show_id !== sid) throw new HttpError(404, 'Opportunity not found');
  res.json(await pass(`/opportunities/${encodeURIComponent(req.params.id)}/explain`));
}));

// ---- admin: Engine tab ----
opportunitiesRouter.get('/api/admin/engine/metrics', requireAdmin, h(async (_req, res) => res.json(await pass('/admin/engine/metrics'))));
opportunitiesRouter.post('/api/admin/engine/regenerate', requireAdmin, h(async (req, res) => {
  const { showId } = parse(z.object({ showId: z.string().min(3).max(60) }), req.body);
  res.json(await pass('/opportunities/generate', { json: { member_show_id: showId, force: true } }));
}));
opportunitiesRouter.post('/api/admin/engine/demo-setup', requireAdmin, h(async (req, res) => {
  const { showId } = parse(z.object({ showId: z.string().optional() }), req.body ?? {});
  try { res.json(await demoSetup({ showId })); } catch (e) { if (e instanceof IntelDown) throw new HttpError(503, 'AI service unavailable'); throw e; }
}));

// ---- admin: Layer 2 sponsors ----
opportunitiesRouter.get('/api/admin/engine/sponsor-metrics', requireAdmin, h(async (_req, res) => res.json(await pass('/admin/engine/sponsor-metrics'))));
opportunitiesRouter.post('/api/admin/engine/sponsor-regenerate', requireAdmin, h(async (req, res) => {
  const { showId } = parse(z.object({ showId: z.string().min(3).max(60) }), req.body);
  res.json(await pass('/sponsor-opportunities/generate', { json: { member_show_id: showId, force: true } }));
}));
opportunitiesRouter.get('/api/admin/sponsors/stats', requireAdmin, h(async (_req, res) => res.json(await pass('/admin/sponsors/stats'))));
opportunitiesRouter.post('/api/admin/sponsors/scan', requireAdmin, h(async (_req, res) => res.json(await pass('/admin/sponsors/scan', { method: 'POST' }))));
opportunitiesRouter.get('/api/admin/sponsors/review/queue', requireAdmin, h(async (req, res) => {
  const qs = new URLSearchParams();
  if (typeof req.query.reviewer === 'string') qs.set('reviewer', req.query.reviewer);
  if (req.query.filter === 'disagree') qs.set('filter', 'disagree');            // Phase 4: "Rules vs AI disagree" first
  res.json(await pass(`/admin/sponsors/review/queue${qs.toString() ? `?${qs}` : ''}`));
}));
opportunitiesRouter.put('/api/admin/sponsors/review/:eventId', requireAdmin, h(async (req, res) => {
  const b = parse(z.object({ reviewer: z.string().trim().min(1).max(80), verdict: z.enum(['ok', 'reject']),
    correctClass: z.string().max(30).optional(), note: z.string().max(300).optional() }), req.body);
  res.json(await pass(`/admin/sponsors/review/${Number(req.params.eventId)}`, { method: 'PUT',
    json: { reviewer: b.reviewer, verdict: b.verdict, correct_class: b.correctClass, note: b.note } }));
}));
opportunitiesRouter.get('/api/admin/sponsors/brands', requireAdmin, h(async (req, res) => {
  const qs = new URLSearchParams();
  for (const k of ['q', 'status', 'limit', 'offset']) if (typeof req.query[k] === 'string') qs.set(k, String(req.query[k]));
  if (req.query.filter === 'disagree') qs.set('filter', 'disagree');
  res.json(await pass(`/admin/sponsors/brands?${qs}`));
}));
opportunitiesRouter.get('/api/admin/sponsors/brands/:id', requireAdmin, h(async (req, res) => res.json(await pass(`/admin/sponsors/brands/${encodeURIComponent(req.params.id)}`))));
opportunitiesRouter.post('/api/admin/sponsors/brands/merge', requireAdmin, h(async (req, res) => {
  const b = parse(z.object({ sourceId: z.string(), targetId: z.string() }), req.body);
  res.json(await pass('/admin/sponsors/brands/merge', { json: { source_id: b.sourceId, target_id: b.targetId, actor: req.user!.email } }));
}));
opportunitiesRouter.post('/api/admin/sponsors/brands/:id/split', requireAdmin, h(async (req, res) => {
  const b = parse(z.object({ domain: z.string().min(3).max(200) }), req.body);
  res.json(await pass(`/admin/sponsors/brands/${encodeURIComponent(req.params.id)}/split`, { json: { domain: b.domain, actor: req.user!.email } }));
}));
opportunitiesRouter.put('/api/admin/sponsors/brands/:id/categories', requireAdmin, h(async (req, res) => {
  const b = parse(z.object({ categories: z.array(z.string()).max(6) }), req.body);
  res.json(await pass(`/admin/sponsors/brands/${encodeURIComponent(req.params.id)}/categories`, { method: 'PUT',
    json: { categories: b.categories, actor: req.user!.email } }));
}));
opportunitiesRouter.post('/api/admin/sponsors/sync-advertisers', requireAdmin, h(async (_req, res) => res.json(await syncAdvertisers())));
opportunitiesRouter.post('/api/admin/sponsors/brands/:id/name', requireAdmin, h(async (req, res) => {
  const b = parse(z.object({ action: z.enum(['approve', 'reject']) }), req.body);
  res.json(await pass(`/admin/sponsors/brands/${encodeURIComponent(req.params.id)}/name`, { json: { action: b.action, actor: req.user!.email } }));
}));

// ---- admin: Phase 4 LLM (status / metrics / run / rules-vs-AI for the label set) ----
opportunitiesRouter.get('/api/admin/llm/status', requireAdmin, h(async (req, res) =>
  res.json(await pass(`/admin/llm/status${req.query.check === '1' ? '?check=true' : ''}`))));
opportunitiesRouter.get('/api/admin/llm/metrics', requireAdmin, h(async (_req, res) => res.json(await pass('/admin/llm/metrics'))));
opportunitiesRouter.post('/api/admin/llm/run', requireAdmin, h(async (req, res) => {
  const b = parse(z.object({ tasks: z.array(z.enum(['style', 'guests', 'topics', 'uncertain', 'organic', 'categories', 'names'])).max(7).optional(),
    limit: z.number().int().min(1).max(5000).optional() }), req.body ?? {});
  res.json(await pass('/admin/llm/run', { json: { tasks: b.tasks, limit: b.limit } }));
}));
opportunitiesRouter.get('/api/admin/llm/labels/disagreements', requireAdmin, h(async (_req, res) => res.json(await pass('/admin/llm/labels/disagreements'))));

// ---- admin: blind pair labels (/admin/labels/pairs) ----
opportunitiesRouter.get('/api/admin/engine/pairs/queue', requireAdmin, h(async (req, res) => {
  const lab = typeof req.query.labeler === 'string' ? `?labeler=${encodeURIComponent(req.query.labeler)}` : '';
  res.json(await pass(`/labels/pairs/queue${lab}`));
}));
opportunitiesRouter.put('/api/admin/engine/pairs/rate', requireAdmin, h(async (req, res) => {
  const b = parse(z.object({ memberShowId: z.string(), candidateShowId: z.string(), labeler: z.string().trim().min(1).max(80),
    rating: z.enum(['good', 'ok', 'bad']), note: z.string().max(300).optional() }), req.body);
  res.json(await pass('/labels/pairs/rate', { method: 'PUT', json: { member_show_id: b.memberShowId, candidate_show_id: b.candidateShowId,
    labeler: b.labeler, rating: b.rating, note: b.note } }));
}));
opportunitiesRouter.post('/api/admin/engine/pairs/items', requireAdmin, h(async (req, res) => {
  const b = parse(z.object({ n: z.number().int().min(3).max(50).default(20), replace: z.boolean().default(false) }), req.body ?? {});
  res.json(await pass('/labels/pairs/items', { json: b }));
}));
opportunitiesRouter.get('/api/admin/engine/pairs/agreement', requireAdmin, h(async (_req, res) => res.json(await pass('/labels/pairs/agreement'))));
