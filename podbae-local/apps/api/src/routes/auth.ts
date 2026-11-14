import { AdvertiserRegisterSchema, LoginSchema, RegisterSchema, websiteDomain } from '@podbae/contracts';
import bcrypt from 'bcryptjs';
import { Router } from 'express';
import { z } from 'zod';
import { q, q1 } from '../db/client.js';
import { config } from '../config.js';
import { HttpError, h, parse } from '../lib.js';
import { USER_COLS, requireAuth } from '../middleware/auth.js';

export const authRouter = Router();

/** Creates a user from an intake `account` block (409 if the email exists). */
export async function createUser(a: { email: string; password: string; name?: string }, role: string) {
  const email = a.email.toLowerCase();
  if (await q1('SELECT 1 FROM users WHERE email = $1', [email])) throw new HttpError(409, 'Email already registered');
  return q1(
    `INSERT INTO users (email, password_hash, name, role) VALUES ($1,$2,$3,$4) RETURNING ${USER_COLS}`,
    [email, await bcrypt.hash(a.password, 10), a.name ?? null, role],
  );
}

export async function startSession(req: any, userId: number) {
  await new Promise<void>((res, rej) => req.session.regenerate((e: unknown) => (e ? rej(e) : res())));
  req.session.userId = userId;
  await new Promise<void>((res, rej) => req.session.save((e: unknown) => (e ? rej(e) : res())));
}

authRouter.post('/api/auth/register', h(async (req, res) => {
  const b = parse(RegisterSchema, req.body);
  if (await q1('SELECT 1 FROM users WHERE email = $1', [b.email.toLowerCase()]))
    throw new HttpError(409, 'Email already registered');
  const hash = await bcrypt.hash(b.password, 10);
  const user = await q1(
    `INSERT INTO users (email, password_hash, name, role) VALUES ($1,$2,$3,$4) RETURNING ${USER_COLS}`,
    [b.email.toLowerCase(), hash, b.name ?? null, b.role],
  );
  await startSession(req, user.id);
  res.status(201).json({ user });
}));

async function doLogin(req: any, role?: string) {
  const b = parse(LoginSchema, req.body);
  const row = await q1('SELECT id, password_hash, role FROM users WHERE email = $1', [b.email.toLowerCase()]);
  if (!row || !row.password_hash || !(await bcrypt.compare(b.password, row.password_hash)))
    throw new HttpError(401, 'Invalid email or password');
  if (role && row.role !== role) throw new HttpError(403, `Not a ${role} account`);
  await startSession(req, row.id);
  return q1(`SELECT ${USER_COLS} FROM users WHERE id = $1`, [row.id]);
}

authRouter.post('/api/auth/login', h(async (req, res) => res.json({ user: await doLogin(req) })));

const me = (req: any, res: any) => res.json({ user: req.user });
authRouter.get('/api/auth/me', requireAuth, me);
authRouter.get('/api/auth/user', requireAuth, me);

authRouter.get('/api/login', (_req, res) => res.redirect(`${config.webOrigin}/login`));

authRouter.post('/api/logout', (req, res) => {
  req.session.destroy(() => {
    res.clearCookie('connect.sid');
    res.json({ ok: true });
  });
});

authRouter.post('/api/forgot-password', h(async (req, res) => {
  const { email } = parse(z.object({ email: z.string().email() }), req.body);
  const u = await q1('SELECT id FROM users WHERE email = $1', [email.toLowerCase()]);
  if (u) console.log(`[forgot-password] reset link for ${email}: ${config.webOrigin}/login?reset=${crypto.randomUUID()}`);
  res.json({ ok: true }); // same response either way (no user enumeration)
}));

// ----- advertiser auth -----
authRouter.post('/api/advertiser/register', h(async (req, res) => {
  const b = parse(AdvertiserRegisterSchema, req.body);
  if (await q1('SELECT 1 FROM users WHERE email = $1', [b.email.toLowerCase()]))
    throw new HttpError(409, 'Email already registered');
  const hash = await bcrypt.hash(b.password, 10);
  const user = await q1(
    `INSERT INTO users (email, password_hash, name, role, onboarded) VALUES ($1,$2,$3,'advertiser',true)
     RETURNING ${USER_COLS}`, [b.email.toLowerCase(), hash, b.contactName ?? b.orgName]);
  const adv = await q1(
    `INSERT INTO advertisers (user_id, org_name, org_type, budget_min, audience, vibe_tags, brand_values,
       categories, goals, contact_name, contact_email, location, website)
     VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13) RETURNING *`,
    [user.id, b.orgName, b.orgType, b.budgetMin, b.audience ?? null, b.vibeTags, b.brandValues,
     b.categories, b.goals, b.contactName ?? null, b.email.toLowerCase(), b.location ?? null, websiteDomain(b.website)]);
  await q(`INSERT INTO data_sources (entity_type, entity_id, source, ref) VALUES ('advertiser',$1,'manual','user-submitted')`, [adv.id]);
  await startSession(req, user.id);
  res.status(201).json({ user, advertiser: adv });
}));

authRouter.post('/api/advertiser/login', h(async (req, res) => {
  const user = await doLogin(req, 'advertiser');
  res.json({ user, advertiser: await q1('SELECT * FROM advertisers WHERE user_id = $1', [user.id]) });
}));

authRouter.get('/api/advertiser/session', requireAuth, h(async (req, res) => {
  if (req.user!.role !== 'advertiser') throw new HttpError(403, 'Not an advertiser');
  res.json({ user: req.user, advertiser: await q1('SELECT * FROM advertisers WHERE user_id = $1', [req.user!.id]) });
}));

// ----- first admin bootstrap -----
authRouter.get('/api/admin/setup-needed', h(async (_req, res) => {
  const r = await q1<{ n: number }>(`SELECT count(*)::int AS n FROM users WHERE role='admin'`);
  res.json({ needed: (r?.n ?? 0) === 0 });
}));

authRouter.post('/api/admin/setup-first-admin', h(async (req, res) => {
  const r = await q1<{ n: number }>(`SELECT count(*)::int AS n FROM users WHERE role='admin'`);
  if ((r?.n ?? 0) > 0) throw new HttpError(403, 'Admin already exists');
  const b = parse(z.object({ email: z.string().email(), password: z.string().min(8), name: z.string().optional() }), req.body);
  const user = await q1(
    `INSERT INTO users (email, password_hash, name, role, tier, onboarded) VALUES ($1,$2,$3,'admin','premium',true)
     RETURNING ${USER_COLS}`, [b.email.toLowerCase(), await bcrypt.hash(b.password, 10), b.name ?? 'Admin']);
  await startSession(req, user.id);
  res.status(201).json({ user });
}));
