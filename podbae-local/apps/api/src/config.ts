import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
export const REPO_ROOT = path.resolve(here, '../../..');

export const config = {
  port: Number(process.env.PORT ?? 5000),
  /** 'memory://' in tests; otherwise ./data/pglite at the repo root. */
  pgliteDir: process.env.PGLITE_DIR ?? path.join(REPO_ROOT, 'data', 'pglite'),
  migrationsDir: path.resolve(here, '../drizzle'),
  sessionSecret: process.env.SESSION_SECRET ?? 'dev-secret-change-me',
  aiServiceUrl: process.env.AI_SERVICE_URL ?? 'http://localhost:8000',
  /** Shared secret sent as X-Service-Token on every AI-service call (the service rejects calls without it). */
  intelServiceToken: process.env.INTEL_SERVICE_TOKEN ?? '',
  webOrigin: process.env.WEB_ORIGIN ?? 'http://localhost:5173',
  demoAutoLike: (process.env.DEMO_AUTO_LIKE ?? 'false').toLowerCase() === 'true',
  /** Podcast-partner matching: 'engine' = Layer 4 Opportunity Engine (AI service); 'legacy' = old tag-overlap scorer (fallback + eval baseline). */
  engine: ((process.env.ENGINE ?? 'engine').toLowerCase() === 'legacy' ? 'legacy' : 'engine') as 'engine' | 'legacy',
};
