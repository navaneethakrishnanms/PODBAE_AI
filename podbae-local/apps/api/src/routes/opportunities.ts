// Layer 4 Opportunity Engine routes (podcast partners). Member actions + admin Engine tab + blind pair labels.
import { OpportunityActionSchema } from '@podbae/contracts';
import { Router } from 'express';
import { z } from 'zod';
import { HttpError, h, parse } from '../lib.js';
import { requireAdmin, requireAuth } from '../middleware/auth.js';
import { demoSetup } from '../services/demoMembers.js';
import { IntelDown, intel } from '../services/intel.js';
import { getOpportunities, memberShowId, opportunityAction } from '../services/opportunities.js';

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
  res.json(await getOpportunities(req.user!));
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
