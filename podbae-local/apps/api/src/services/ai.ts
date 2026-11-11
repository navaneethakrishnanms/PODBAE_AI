import { MatchResponseSchema, type MatchRequest, type MatchResponse } from '@podbae/contracts';
import { config } from '../config.js';
import { serviceHeaders } from './intel.js';
import { localMatch } from './scoring.js';

async function post(path: string, body: unknown): Promise<any> {
  const res = await fetch(`${config.aiServiceUrl}${path}`, {
    method: 'POST',
    headers: serviceHeaders({ 'content-type': 'application/json' }),
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(20_000),
  });
  if (!res.ok) throw new Error(`AI service ${res.status}`);
  return res.json();
}

/** Calls the Python service; falls back to the in-process TS copy of the same scoring. */
export async function aiMatch(req: MatchRequest, opts: { forceLocal?: boolean } = {}): Promise<MatchResponse> {
  if (!opts.forceLocal) {
    try {
      return MatchResponseSchema.parse(await post('/match', req));
    } catch {
      console.warn('[ai] service unavailable -> using in-process scoring fallback');
    }
  }
  return localMatch(req);
}

interface HeyBaeIn {
  message: string;
  context: { podcast?: { name?: string } | null; episodes?: unknown[]; matches?: { name?: string; targetType?: string; totalScore?: number; explanation?: { summary?: string } }[] };
  history: { role: string; content: string }[];
}

function localHeyBae({ context }: HeyBaeIn): string {
  const pod = context.podcast;
  const top = (context.matches ?? []).slice(0, 3);
  if (!pod) return "Hey! I don't see a podcast on your profile yet — finish your intake and I can help.";
  if (!top.length) return `Hi! I'm looking at ${pod.name}, but there are no matches yet. Try "Run matching".`;
  return `[mock] Here are your top matches for ${pod.name}:\n` +
    top.map((m) => `- ${m.name} (${m.targetType}, ${m.totalScore}%): ${m.explanation?.summary ?? ''}`).join('\n');
}

export async function aiHeyBae(body: HeyBaeIn): Promise<{ reply: string; provider: string }> {
  try {
    return await post('/heybae/chat', body);
  } catch {
    return { reply: localHeyBae(body), provider: 'mock-local' };
  }
}
