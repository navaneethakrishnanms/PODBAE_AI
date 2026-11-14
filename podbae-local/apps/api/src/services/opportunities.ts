// Layer 4 Opportunity Engine wiring (podcast partners only). The engine lives in the AI service; Express adds the per-user
// parts: which show is "mine", the tier's daily allowance (never padded), impression logging with positions, the
// "may be outdated" fallback when the AI service is down, and the actions (save / dismiss / message / invite).
import { q, q1 } from '../db/client.js';
import { HttpError } from '../lib.js';
import { resolveShowId } from '../routes/intel.js';
import { IntelDown, intel } from './intel.js';
import { tierConfig } from './tiers.js';

export interface OppList {
  state: string; items: any[]; message?: string | null; suggestions?: any[]; outdated?: boolean; cached_at?: string | null;
  member_show_id?: string | null; limited?: boolean; daily_limit?: number; total_qualified?: number; [k: string]: unknown;
}

const claimed = new Set<string>();

/** The member's own show id in the intelligence store (null = not connected yet). Marks the show as a PodBae member's (claim). */
export async function memberShowId(userId: number): Promise<string | null> {
  const p = await q1('SELECT id FROM podcasts WHERE owner_user_id = $1 ORDER BY id LIMIT 1', [userId]);
  if (!p) return null;
  const link = await q1('SELECT * FROM intel_links WHERE podcast_id = $1', [p.id]);
  const sid = await resolveShowId(link);
  if (sid && !claimed.has(`${sid}:${userId}`)) {
    const demo = (await q1('SELECT demo FROM users WHERE id = $1', [userId]))?.demo === true;
    try {
      const r = await intel(`/shows/${encodeURIComponent(sid)}/claim?user_id=${userId}&demo=${demo}`, { method: 'POST' });
      if (r.status === 200) claimed.add(`${sid}:${userId}`);
    } catch { /* AI down: try again next time */ }
  }
  return sid;
}

/** Pure (unit-tested): a tier allows `limit` distinct opportunities per day. Items already shown today stay (stable list);
 *  new ones fill only the remaining slots. Never padded: if fewer qualify, fewer are shown. limit < 0 = unlimited. */
export function applyDailyOpportunityLimit<T extends { target?: { show_id?: string; target_id?: string } }>(items: T[], shownToday: string[], limit: number) {
  if (limit < 0) return { items, limited: false };
  const key = (i: T) => i.target?.show_id ?? i.target?.target_id ?? '';
  const today = new Set(shownToday);
  const already = items.filter((i) => today.has(key(i)));
  const slots = Math.max(0, limit - today.size);
  const fresh = items.filter((i) => !today.has(key(i))).slice(0, slots);
  const keep = new Set([...already, ...fresh]);
  const out = items.filter((i) => keep.has(i));
  return { items: out, limited: out.length < items.length };
}

const day = () => new Date().toISOString().slice(0, 10);

async function logImpressions(userId: number, items: any[]) {
  if (!items.length) return;
  const events = items.map((it, i) => ({
    opportunity_id: it.id, type: 'impression', user_id: String(userId), position: i + 1,
    idempotency_key: `imp:${it.id}:${userId}:${day()}`,
  }));
  try { await intel('/events', { json: { events } }); } catch { /* impressions are best-effort; never block the page */ }
}

async function waitForJob(jobId: string, ms: number) {
  const until = Date.now() + ms;
  while (Date.now() < until) {
    const j = await intel(`/jobs/${jobId}`);
    if (j.body?.status === 'succeeded' || j.body?.status === 'failed') return j.body.status;
    await new Promise((r) => setTimeout(r, 400));
  }
  return 'running';
}

export type OppKind = 'partner' | 'sponsor';

/** Ranked, tier-limited opportunities of one kind (podcast partners or sponsors) for a member, with the outdated fallback. */
export async function getOpportunities(user: { id: number; tier: string },
  opts: { waitMs?: number; logImpressions?: boolean; kind?: OppKind } = {}): Promise<OppList> {
  const kind: OppKind = opts.kind ?? 'partner';
  const tc = tierConfig(user.tier) as ReturnType<typeof tierConfig> & { sponsorPerDay?: number };
  const limit = kind === 'sponsor' ? (tc.sponsorPerDay ?? 0) : tc.matchesPerDay;
  if (kind === 'sponsor' && limit === 0) {
    return { state: 'locked', kind, items: [], daily_limit: 0,
      message: 'Sponsor recommendations are part of the Date plan (2 per day) and the Commit plan (all). Upgrade to see brands that sponsor shows like yours.' };
  }
  const cached = await q1('SELECT payload, cached_at FROM opportunity_cache WHERE user_id = $1 AND kind = $2', [user.id, kind]);
  let sid: string | null;
  try {
    sid = await memberShowId(user.id);
  } catch (e) {
    if (e instanceof IntelDown && cached) return { ...cached.payload, outdated: true, cached_at: cached.cached_at };
    throw e;
  }
  if (!sid) {
    if (cached) return { ...cached.payload, outdated: true, cached_at: cached.cached_at,
      message: 'The intelligence service is unreachable. Showing your last saved opportunities; they may be outdated.' };
    return { state: 'not_connected', items: [], message: 'Connect your RSS feed on the Intelligence page to get podcast-partner opportunities.', member_show_id: null };
  }
  try {
    const path = `/${kind === 'sponsor' ? 'sponsor-opportunities' : 'opportunities'}?member_show_id=${encodeURIComponent(sid)}&user_id=${user.id}&limit=50`;
    let r = await intel(path);
    if (r.status !== 200) throw new HttpError(r.status, r.body?.detail ?? 'Opportunity engine error');
    if ((r.body.state === 'generating' || r.body.stale) && r.body.job?.id && (opts.waitMs ?? 6000) > 0) {
      await waitForJob(r.body.job.id, opts.waitMs ?? 6000);
      r = await intel(path);
    }
    const body = r.body;
    const lim = applyDailyOpportunityLimit(body.items ?? [], body.shown_today_target_ids ?? [], limit);
    const out: OppList = { ...body, items: lim.items, limited: lim.limited, daily_limit: limit, outdated: false, cached_at: null };
    if (opts.logImpressions !== false) await logImpressions(user.id, lim.items);
    await q(`INSERT INTO opportunity_cache (user_id, kind, member_show_id, payload, cached_at) VALUES ($1,$2,$3,$4,now())
             ON CONFLICT (user_id, kind) DO UPDATE SET member_show_id = EXCLUDED.member_show_id, payload = EXCLUDED.payload, cached_at = now()`,
      [user.id, kind, sid, JSON.stringify(out)]);
    return out;
  } catch (e) {
    if (!(e instanceof IntelDown)) throw e;
    if (cached) return { ...cached.payload, outdated: true, cached_at: cached.cached_at,
      message: 'The intelligence service is unreachable. Showing your last saved opportunities; they may be outdated.' };
    return { state: 'ai_unavailable', items: [], outdated: true, message: 'The intelligence service is unreachable and no saved opportunities exist yet.' };
  }
}

const EVENT_FOR: Record<string, string> = { open: 'open', save: 'save', unsave: 'unsave', dismiss: 'dismiss', message: 'contact', invite: 'invite',
  contacted: 'contact' };
const SPONSOR_ACTIONS = new Set(['open', 'save', 'unsave', 'dismiss', 'contacted']);
const SPONSOR_REASONS = new Set(['not_my_audience', 'category_conflict', 'too_big', 'already_contacted', 'other']);

/** Save / dismiss (with reason) / message (members only) / invite (non-members; recorded, nothing is sent). Every action is an event. */
export async function opportunityAction(user: { id: number; name: string | null }, oppId: string, action: string, reason?: string, note?: string) {
  const sid = await memberShowId(user.id);
  if (!sid) throw new HttpError(404, 'Connect your RSS feed first');
  let opp: any;
  try {
    const r = await intel(`/opportunities/${encodeURIComponent(oppId)}`);
    if (r.status !== 200) throw new HttpError(404, 'Opportunity not found');
    opp = r.body;
  } catch (e) { if (e instanceof IntelDown) throw new HttpError(503, 'AI service unavailable'); throw e; }
  if (opp.member_show_id !== sid) throw new HttpError(404, 'Opportunity not found');
  const target = opp.target ?? {};
  const result: Record<string, unknown> = { ok: true, action };
  if (opp.type === 'sponsor') {
    // brands are never messaged or invited from PodBae in this phase; "Mark as contacted" only logs that YOU reached out
    if (!SPONSOR_ACTIONS.has(action)) throw new HttpError(400, 'Sponsor cards support Save, Dismiss and Mark as contacted. Nothing is sent to brands.');
    if (action === 'dismiss' && !SPONSOR_REASONS.has(reason ?? '')) throw new HttpError(400, 'Pick a sponsor dismiss reason');
    if (action === 'contacted') { note = note ?? 'marked as contacted by the member (manual; nothing was sent by PodBae)'; result.note = 'Logged. PodBae did not contact the brand.'; }
  } else if (action === 'contacted') {
    throw new HttpError(400, 'Use Message (members) or Invite to PodBae for podcast partners');
  }

  if (action === 'message') {
    const other = Number(target.member_user_id);
    if (!target.is_member || !other) throw new HttpError(400, 'Only PodBae members can be messaged in-app. Invite them to PodBae instead.');
    if (other === user.id) throw new HttpError(400, 'That is your own show');
    const [a, b] = user.id < other ? [user.id, other] : [other, user.id];
    const conv = await q1(`INSERT INTO conversations (user_a, user_b) VALUES ($1,$2)
                           ON CONFLICT (user_a, user_b) DO UPDATE SET user_a = EXCLUDED.user_a RETURNING id`, [a, b]);
    await q(`INSERT INTO notifications (user_id, type, title, body) VALUES ($1,'partner',$2,'Open Messages to reply.')`,
      [other, `${user.name ?? 'A PodBae member'} wants to talk about a ${opp.type_label ?? 'cross-promo'} partnership`]);
    result.conversationId = conv.id;
  }
  if (action === 'invite') {
    if (target.is_member) throw new HttpError(400, 'This show is already on PodBae: message them instead.');
    const inv = await q1(`INSERT INTO partnership_invites (email, org_name, message, status, kind, target_show_id, opportunity_id, created_by)
       VALUES (NULL, $1, $2, 'recorded', 'podbae_invite', $3, $4, $5) RETURNING id`,
      [target.title ?? null, 'Invite to PodBae recorded from an opportunity card. Nothing was sent externally.', target.show_id ?? null, oppId, user.id]);
    result.inviteId = inv.id;
    result.note = 'Invite recorded. Nothing is sent outside PodBae in this version.';
  }
  let ev;
  try {
    ev = await intel('/events', { json: { events: [{ opportunity_id: oppId, type: EVENT_FOR[action], user_id: String(user.id), reason, note }] } });
  } catch (e) { if (e instanceof IntelDown) throw new HttpError(503, 'AI service unavailable'); throw e; }
  if (ev.status >= 400) throw new HttpError(ev.status === 422 ? 400 : ev.status, String(ev.body?.detail ?? 'Event rejected'));
  return result;
}


/** Registered PodBae advertisers -> Layer 2 brands, matched by registrable DOMAIN only (never by name). Only a registered
 *  advertiser with an active campaign can make a sponsor card "Verified". The domain comes from the optional
 *  "Company website" field (signup or campaign builder); an advertiser without one is never matched. */
export async function syncAdvertisers() {
  const rows = await q(`SELECT a.id, a.categories, a.website,
      EXISTS(SELECT 1 FROM campaigns c WHERE c.advertiser_id = a.id AND c.status = 'active') AS active,
      (SELECT min(c.created_at) FROM campaigns c WHERE c.advertiser_id = a.id AND c.status = 'active') AS started,
      ARRAY(SELECT DISTINCT x FROM unnest(a.categories || COALESCE((SELECT array_agg(DISTINCT cat) FROM campaigns c, unnest(c.categories) cat
                                                                   WHERE c.advertiser_id = a.id AND c.status = 'active'), '{}')) x) AS cats
    FROM advertisers a`);
  const advertisers = rows.filter((r: any) => r.website).map((r: any) => ({ advertiser_ref: String(r.id), domain: r.website,
    active_campaign: r.active, campaign_categories: r.cats, campaign_started_at: r.started ? new Date(r.started).toISOString() : null }));
  const out = advertisers.length ? (await intel('/sponsors/registrations', { json: { advertisers } })).body : { linked: 0, unmatched: [] };
  return { advertisers: rows.length, with_website: advertisers.length, ...out,
    note: advertisers.length ? undefined : 'No PodBae advertiser has a website on file, so no brand can be matched (matching is by domain only).' };
}
