/** In-process copy of services/ai scoring (fallback when the AI service is down). Keep in sync. */
import type { MatchCandidate, MatchRequest, MatchResponse } from '@podbae/contracts';
import { load } from './weights.js';

type Parts = Record<string, number>;
const COMPONENTS = ['genreScore', 'locationScore', 'toneScore', 'keywordScore', 'vibeScore', 'performanceScore'];
const LABEL: Record<string, string> = {
  genreScore: 'genre', locationScore: 'location', toneScore: 'tone', keywordScore: 'keywords',
  vibeScore: 'vibe', performanceScore: 'activity',
};

const norm = (t: string[] = []) => new Set(t.map((x) => x.trim().toLowerCase()).filter(Boolean));
function jaccard(a: string[] = [], b: string[] = []) {
  const sa = norm(a), sb = norm(b);
  if (!sa.size || !sb.size) return 0;
  const inter = [...sa].filter((x) => sb.has(x)).length;
  return inter / new Set([...sa, ...sb]).size;
}
function locationScore(a?: string | null, b?: string | null) {
  if (!a || !b) return 0;
  const ta = a.split(',').map((s) => s.trim().toLowerCase()).filter(Boolean);
  const tb = b.split(',').map((s) => s.trim().toLowerCase()).filter(Boolean);
  if (!ta.length || !tb.length) return 0;
  if (ta[0] === tb[0]) return 1;
  return ta.some((x) => tb.includes(x)) ? 0.5 : 0;
}
const daysSince = (ts: string | null | undefined, now: Date) =>
  ts ? Math.max(Math.floor((now.getTime() - new Date(ts).getTime()) / 86400000), 0) : null;
const round = (n: number, d: number) => Number(n.toFixed(d));
const shared = (a: string[] = [], b: string[] = []) => {
  const sb = norm(b);
  return [...new Set(a.filter((t) => sb.has(t.trim().toLowerCase())))];
};

function performance(c: MatchCandidate, now: Date, half: number) {
  if (c.type !== 'podcast' && c.type !== 'collaborator') return 0.5;
  const d = daysSince(c.lastEpisodeAt, now);
  if (d === null) return 0;
  return round(0.7 * 0.5 ** (d / half) + 0.3 * Math.min((c.episodeCount ?? 0) / 24, 1), 6);
}

type Subject = MatchRequest['podcast'];

function reason(key: string, s: Subject, c: MatchCandidate, now: Date) {
  switch (key) {
    case 'genreScore': return `Shared categories: ${shared(s.categories, c.categories).join(', ')}.`;
    case 'locationScore': return locationScore(s.location, c.location) >= 1 ? `Both based in ${c.location}.` : 'Overlapping region.';
    case 'toneScore': return `Similar tone: ${shared(s.toneTags, c.toneTags).join(', ')}.`;
    case 'keywordScore': return `Common keywords: ${shared(s.keywords, c.keywords).join(', ')}.`;
    case 'vibeScore': return `Shared vibe: ${shared(s.vibeTags, c.vibeTags).join(', ')}.`;
    default: return `Actively publishing (last episode ${daysSince(c.lastEpisodeAt, now)} day(s) ago).`;
  }
}

export function localMatch(req: MatchRequest, asOf: Date = new Date()): MatchResponse {
  const { weights, halfLifeDays } = load();
  const wsum = Object.values(weights).reduce((a, b) => a + b, 0) || 1;
  const s = req.podcast;
  const results = req.candidates.filter((c) => req.targetTypes.includes(c.type)).map((c) => {
    const parts: Parts = {
      genreScore: jaccard(s.categories, c.categories), locationScore: locationScore(s.location, c.location),
      toneScore: jaccard(s.toneTags, c.toneTags), keywordScore: jaccard(s.keywords, c.keywords),
      vibeScore: jaccard(s.vibeTags, c.vibeTags), performanceScore: performance(c, asOf, halfLifeDays), listenScore: 0,
    };
    const total = round(Object.entries(parts).reduce((a, [k, v]) => a + (weights[k] ?? 0) * v, 0) / wsum * 100, 2);
    const keys = COMPONENTS.filter((k) => parts[k] > 0 && !(k === 'performanceScore' && c.type !== 'podcast' && c.type !== 'collaborator'))
      .sort((a, b) => (weights[b] ?? 0) * parts[b] - (weights[a] ?? 0) * parts[a] || COMPONENTS.indexOf(a) - COMPONENTS.indexOf(b));
    const top = keys.slice(0, 2);
    const days = daysSince(s.lastEpisodeAt, asOf);
    const whyNow = days === null ? 'Publish an episode to keep your matches fresh.'
      : days <= 14 ? `You published ${days} day(s) ago — momentum is high, a good time to reach out.`
      : `It's been ${days} days since your last episode — a new partnership could re-engage listeners.`;
    const r = (k: string) => round(parts[k], 4);
    return {
      targetType: c.type, targetId: c.id, totalScore: total,
      scoreBreakdown: {
        genreScore: r('genreScore'), locationScore: r('locationScore'), toneScore: r('toneScore'),
        keywordScore: r('keywordScore'), vibeScore: r('vibeScore'), performanceScore: r('performanceScore'),
        listenScore: 0, weights, total,
      },
      explanation: {
        summary: `${c.name} is a ${total.toFixed(0)}% match${top.length ? ` — strongest on ${LABEL[top[0]]}` : ''}.`,
        reasons: top.length ? top.map((k) => reason(k, s, c, asOf)) : ['Low overlap; included as a stretch match.'],
        whyNow,
        evidence: [{ source: `db:${c.type}`, ref: String(c.id), fetchedAt: asOf.toISOString() }],
      },
    };
  });
  results.sort((a, b) => b.totalScore - a.totalScore || a.targetType.localeCompare(b.targetType) || a.targetId - b.targetId);
  return { matches: results.slice(0, req.limit) };
}
