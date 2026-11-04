import { COLLABORATOR_COLLAB_TYPE, type MatchCandidate } from '@podbae/contracts';
import { q, q1 } from '../db/client.js';
import { aiMatch } from './ai.js';

interface Snap {
  name: string;
  location: string | null;
  categories: string[];
  vibeTags: string[];
  toneTags: string[];
  artworkUrl: string | null;
  demo: boolean;
  userId: number | null;
}

const iso = (d: unknown) => (d ? new Date(d as string).toISOString() : null);

function podcastCandidate(p: any, type: 'podcast' | 'collaborator'): [MatchCandidate, Snap] {
  const cand: MatchCandidate = {
    id: p.id, type, userId: p.owner_user_id, name: p.name,
    categories: p.categories, location: p.location,
    vibeTags: p.vibe_tags, toneTags: p.tone_tags,
    keywords: [...(p.keywords ?? []), ...(p.topics ?? [])],
    lastEpisodeAt: iso(p.last_episode_at), episodeCount: p.episode_count,
  };
  return [cand, { name: p.name, location: p.location, categories: p.categories,
    vibeTags: p.vibe_tags, toneTags: p.tone_tags, artworkUrl: p.artwork_url, demo: p.demo,
    userId: p.owner_user_id }];
}

function simpleCandidate(r: any, type: 'sponsor' | 'guest' | 'venue', kw: string[]): [MatchCandidate, Snap] {
  return [
    { id: r.id, type, userId: r.user_id, name: r.name, categories: r.categories,
      location: r.location, vibeTags: r.vibe_tags, toneTags: r.tone_tags, keywords: kw },
    { name: r.name, location: r.location, categories: r.categories, vibeTags: r.vibe_tags,
      toneTags: r.tone_tags, artworkUrl: null, demo: r.demo, userId: r.user_id },
  ];
}

export async function loadCandidates(excludeUserId: number) {
  const out: [MatchCandidate, Snap][] = [];

  const pods = await q('SELECT * FROM podcasts WHERE owner_user_id IS DISTINCT FROM $1', [excludeUserId]);
  for (const p of pods) {
    // Exclusive types so a show never appears twice: Promo-Swap shows are "podcast" partners;
    // shows offering only guest swaps / live events are "collaborators".
    const collab: string[] = p.collaboration_types ?? [];
    const isCollaborator = collab.includes(COLLABORATOR_COLLAB_TYPE) && !collab.includes('Promo Swap/Feed Swap');
    out.push(podcastCandidate(p, isCollaborator ? 'collaborator' : 'podcast'));
  }

  const sponsors = await q(`
    SELECT a.id, a.user_id, a.org_name AS name, a.location, a.vibe_tags, a.tone_tags, a.demo,
           a.brand_values, a.goals,
           ARRAY(SELECT DISTINCT x FROM unnest(a.categories ||
             COALESCE((SELECT array_agg(DISTINCT cat) FROM campaigns cp, unnest(cp.categories) cat
                       WHERE cp.advertiser_id = a.id), '{}')) x) AS categories
    FROM advertisers a WHERE a.user_id IS DISTINCT FROM $1`, [excludeUserId]);
  for (const s of sponsors) out.push(simpleCandidate(s, 'sponsor', [...s.brand_values, ...s.goals]));

  const guests = await q('SELECT * FROM guests WHERE user_id IS DISTINCT FROM $1', [excludeUserId]);
  for (const g of guests) out.push(simpleCandidate(g, 'guest', g.topics));

  const venues = await q('SELECT * FROM venues WHERE user_id IS DISTINCT FROM $1', [excludeUserId]);
  for (const v of venues) out.push(simpleCandidate(v, 'venue', []));

  return out;
}

export async function runMatching(userId: number, opts: { forceLocal?: boolean } = {}): Promise<{ count: number }> {
  const p = await q1('SELECT * FROM podcasts WHERE owner_user_id = $1 ORDER BY id LIMIT 1', [userId]);
  if (!p) return { count: 0 };

  const cands = await loadCandidates(userId);
  const snaps = new Map(cands.map(([c, s]) => [`${c.type}:${c.id}`, s]));
  const [subject] = podcastCandidate(p, 'podcast');
  const { type: _t, ...subj } = subject;
  void _t;

  const res = await aiMatch({
    podcast: subj,
    candidates: cands.map(([c]) => c),
    targetTypes: ['podcast', 'sponsor', 'guest', 'venue', 'collaborator'],
    limit: 200,
  }, opts);

  for (const m of res.matches) {
    const snap = snaps.get(`${m.targetType}:${m.targetId}`)!;
    await q(
      `INSERT INTO matches (user_id, target_type, target_id, target_user_id, target_snapshot,
                            total_score, score_breakdown, explanation)
       VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
       ON CONFLICT (user_id, target_type, target_id) DO UPDATE SET
         target_user_id = EXCLUDED.target_user_id, target_snapshot = EXCLUDED.target_snapshot,
         total_score = EXCLUDED.total_score, score_breakdown = EXCLUDED.score_breakdown,
         explanation = EXCLUDED.explanation`,
      [userId, m.targetType, m.targetId, snap.userId, JSON.stringify(snap), m.totalScore,
       JSON.stringify(m.scoreBreakdown), JSON.stringify(m.explanation)],
    );
  }
  return { count: res.matches.length };
}

const PRED_TYPE: Record<string, string> = {
  sponsor: 'sponsor_opportunity', guest: 'guest_booking', venue: 'live_event',
  podcast: 'podcast_swap', collaborator: 'collaboration',
};
const PRED_LABEL: Record<string, string> = {
  sponsor: 'Sponsor opportunity', guest: 'Guest booking', venue: 'Live recording venue',
  podcast: 'Cross-promo partner', collaborator: 'Collaboration',
};

/** Creates predictions (opportunities) from the user's best matches per type. Idempotent per match. */
export async function generatePredictions(userId: number, perType = 2): Promise<number> {
  const top = await q(
    `SELECT * FROM (SELECT m.*, row_number() OVER (PARTITION BY target_type ORDER BY total_score DESC) rn
                    FROM matches m WHERE user_id = $1) t WHERE rn <= $2`, [userId, perType]);
  let created = 0;
  for (const m of top) {
    const exists = await q1(`SELECT 1 FROM predictions WHERE user_id=$1 AND payload->>'matchId' = $2`, [userId, String(m.id)]);
    if (exists) continue;
    const whyNow: string = m.explanation?.whyNow ?? 'Add episodes to keep matches fresh.';
    await q(
      `INSERT INTO predictions (user_id, type, title, payload, score, why, why_now, evidence)
       VALUES ($1,$2,$3,$4,$5,$6,$7,$8)`,
      [userId, PRED_TYPE[m.target_type], `${PRED_LABEL[m.target_type]}: ${m.target_snapshot?.name ?? ''}`,
       JSON.stringify({ matchId: m.id, targetType: m.target_type, targetId: m.target_id }),
       m.total_score, m.explanation?.summary ?? null, whyNow, JSON.stringify(m.explanation?.evidence ?? [])],
    );
    created++;
  }
  return created;
}
