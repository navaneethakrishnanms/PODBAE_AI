// Client for the AI service /v1 API (the intelligence store is reachable ONLY this way — never by direct DB access).
import { config } from '../config.js';

export class IntelDown extends Error {
  constructor(msg = 'AI service unavailable') { super(msg); }
}
export interface IntelResult<T = any> { status: number; body: T }

/** Every call to the AI service carries the shared service token (the service is 401 without it). */
export function serviceHeaders(extra: Record<string, string> = {}): Record<string, string> {
  return { ...extra, 'x-service-token': config.intelServiceToken };
}

export async function intel<T = any>(path: string, init: { method?: string; json?: unknown; form?: FormData; timeoutMs?: number } = {}): Promise<IntelResult<T>> {
  let res: Response;
  try {
    res = await fetch(`${config.aiServiceUrl}/v1${path}`, {
      method: init.method ?? (init.json || init.form ? 'POST' : 'GET'),
      headers: serviceHeaders(init.json ? { 'content-type': 'application/json' } : {}),
      body: init.form ?? (init.json ? JSON.stringify(init.json) : undefined),
      signal: AbortSignal.timeout(init.timeoutMs ?? 20_000),
    });
  } catch (e) {
    throw new IntelDown(e instanceof Error ? e.message : 'fetch failed');
  }
  const text = await res.text();
  let body: any = text;
  try { body = text ? JSON.parse(text) : {}; } catch { /* non-JSON body */ }
  return { status: res.status, body };
}

/** Fields that are private to the creator and must not appear on a public profile. */
const PRIVATE_PREFIXES = ['audience.', 'creator.'];
export function publicProfile(profile: any) {
  if (!profile?.fields) return profile;
  const fields = Object.fromEntries(Object.entries(profile.fields).filter(([k]) => !PRIVATE_PREFIXES.some((p) => k.startsWith(p))));
  return { ...profile, fields, missing: [], improve: [], refresh_job: null };
}
