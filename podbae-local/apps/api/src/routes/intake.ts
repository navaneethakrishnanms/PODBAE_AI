import { AccountSchema, PodcasterSubmissionSchema } from '@podbae/contracts';
import { Router, type Request } from 'express';
import { z } from 'zod';
import { q, q1 } from '../db/client.js';
import { HttpError, h, parse } from '../lib.js';
import { generatePredictions, runMatching } from '../services/matching.js';
import { kickIntelIngest } from './intel.js';
import { createUser, startSession } from './auth.js';

export const intakeRouter = Router();

/** Logged-in user, or create the account supplied with the intake form. */
async function userForIntake(req: Request, role: string, account?: z.infer<typeof AccountSchema>) {
  if (req.user) return req.user;
  if (!account) throw new HttpError(401, 'Log in or provide account details');
  const user = await createUser(account, role);
  await startSession(req, user.id);
  return user;
}

const withAccount = <T extends z.ZodRawShape>(shape: T) => z.object({ account: AccountSchema.optional(), ...shape });

intakeRouter.post('/api/submissions', h(async (req, res) => {
  const b = parse(PodcasterSubmissionSchema, req.body);
  const user = await userForIntake(req, 'podcaster', b.account);
  const uid = user.id;
  const rss = b.rssUrl || null;
  const existing = await q1('SELECT id FROM podcasts WHERE owner_user_id = $1 ORDER BY id LIMIT 1', [uid]);
  const vals = [b.showName, rss, b.categories, b.vibeTags, b.toneTags, b.collaborationTypes,
    b.audienceNotes ?? null, b.location ?? null, b.goals ?? null];
  let podcastId: number;
  if (existing) {
    await q(
      `UPDATE podcasts SET name=$1, rss_url=COALESCE($2, rss_url), categories=$3, vibe_tags=$4, tone_tags=$5,
         collaboration_types=$6, audience_summary=$7, location=$8, goals=$9, updated_at=now() WHERE id=$10`,
      [...vals, existing.id]);
    podcastId = existing.id;
  } else {
    const p = await q1(
      `INSERT INTO podcasts (name, rss_url, categories, vibe_tags, tone_tags, collaboration_types,
         audience_summary, location, goals, owner_user_id, source)
       VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,'manual') RETURNING id`, [...vals, uid]);
    podcastId = p.id;
    await q(`INSERT INTO data_sources (entity_type, entity_id, source, ref) VALUES ('podcast',$1,'manual','user-submitted')
             ON CONFLICT DO NOTHING`, [podcastId]);
  }
  const sub = await q1(`INSERT INTO submissions (user_id, kind, payload) VALUES ($1,'podcaster',$2) RETURNING id`,
    [uid, JSON.stringify({ ...b, account: undefined })]);
  await q('UPDATE users SET onboarded = true WHERE id = $1', [uid]);
  const { count } = await runMatching(uid);
  await generatePredictions(uid);
  // Layer 1: a submitted RSS feed starts real ingestion (best effort: the intake never fails because the AI service is down)
  const ingest = rss ? await kickIntelIngest(podcastId, uid, rss).catch(() => null) : null;
  res.status(201).json({ submissionId: sub.id, podcastId, matchesCreated: count, intelJobId: ingest?.ok ? ingest.jobId : null, intelNote: ingest && !ingest.ok ? ingest.error : undefined });
}));

intakeRouter.get('/api/submissions/:id/matches', h(async (req, res) => {
  if (!req.user) throw new HttpError(401, 'Not authenticated');
  const sub = await q1('SELECT user_id FROM submissions WHERE id = $1', [req.params.id]);
  if (!sub) throw new HttpError(404, 'Submission not found');
  if (sub.user_id !== req.user.id && req.user.role !== 'admin') throw new HttpError(403, 'Forbidden');
  res.json({ matches: await q('SELECT * FROM matches WHERE user_id = $1 ORDER BY total_score DESC LIMIT 20', [sub.user_id]) });
}));

const VenueSchema = withAccount({
  name: z.string().min(1), venueType: z.string().optional(), location: z.string().optional(),
  capacity: z.number().int().optional(), description: z.string().optional(),
  categories: z.array(z.string()).default([]), vibeTags: z.array(z.string()).default([]),
  contactEmail: z.string().email().optional(),
});
intakeRouter.post('/api/venue-submissions', h(async (req, res) => {
  const b = parse(VenueSchema, req.body);
  const user = await userForIntake(req, 'venue', b.account);
  const v = await q1(
    `INSERT INTO venues (user_id, name, venue_type, location, capacity, description, categories, vibe_tags, contact_email)
     VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9) RETURNING *`,
    [user.id, b.name, b.venueType ?? null, b.location ?? null, b.capacity ?? null, b.description ?? null,
     b.categories, b.vibeTags, b.contactEmail ?? user.email]);
  await q('INSERT INTO submissions (user_id, kind, payload) VALUES ($1,$2,$3)', [user.id, 'venue', JSON.stringify({ ...b, account: undefined })]);
  await q(`INSERT INTO data_sources (entity_type, entity_id, source, ref) VALUES ('venue',$1,'manual','user-submitted')`, [v.id]);
  await q('UPDATE users SET onboarded = true WHERE id = $1', [user.id]);
  res.status(201).json({ venue: v });
}));

const GuestSchema = withAccount({
  name: z.string().min(1), expertise: z.string().optional(), bio: z.string().optional(),
  topics: z.array(z.string()).default([]), categories: z.array(z.string()).default([]),
  vibeTags: z.array(z.string()).default([]), location: z.string().optional(),
  contactEmail: z.string().email().optional(),
});
intakeRouter.post('/api/guest-submissions', h(async (req, res) => {
  const b = parse(GuestSchema, req.body);
  const user = await userForIntake(req, 'guest', b.account);
  const g = await q1(
    `INSERT INTO guests (user_id, name, expertise, bio, topics, categories, vibe_tags, location, contact_email)
     VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9) RETURNING *`,
    [user.id, b.name, b.expertise ?? null, b.bio ?? null, b.topics, b.categories, b.vibeTags,
     b.location ?? null, b.contactEmail ?? user.email]);
  await q('INSERT INTO submissions (user_id, kind, payload) VALUES ($1,$2,$3)', [user.id, 'guest', JSON.stringify({ ...b, account: undefined })]);
  await q(`INSERT INTO data_sources (entity_type, entity_id, source, ref) VALUES ('guest',$1,'manual','user-submitted')`, [g.id]);
  await q('UPDATE users SET onboarded = true WHERE id = $1', [user.id]);
  res.status(201).json({ guest: g });
}));

const InviteSchema = z.object({ email: z.string().email(), orgName: z.string().optional(), message: z.string().optional() });
intakeRouter.post('/api/partnership-invite', h(async (req, res) => {
  const b = parse(InviteSchema, req.body);
  const inv = await q1(
    `INSERT INTO partnership_invites (email, org_name, message, created_by) VALUES ($1,$2,$3,$4) RETURNING *`,
    [b.email, b.orgName ?? null, b.message ?? null, req.user?.id ?? null]);
  res.status(201).json({ invite: inv });
}));
intakeRouter.get('/api/partnership-invite/:id', h(async (req, res) => {
  if (!z.string().uuid().safeParse(req.params.id).success) throw new HttpError(400, 'Invalid id');
  const inv = await q1('SELECT * FROM partnership_invites WHERE id = $1', [req.params.id]);
  if (!inv) throw new HttpError(404, 'Invite not found');
  res.json({ invite: inv });
}));
