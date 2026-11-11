// Connects the demo podcaster (podcaster@podbae.local) to a real RSS feed through the running API, then waits for ingestion.
// Usage: npm run intel:connect-demo [-- <rss-url>]     (needs `npm run dev` running)
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const base = process.env.API_URL ?? 'http://localhost:5000';
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
let feed = process.argv[2];
if (!feed) {
  try {
    const lines = readFileSync(path.join(root, 'services/ai/seed/feeds.txt'), 'utf8').split('\n').filter((l) => l.trim() && !l.startsWith('#'));
    feed = lines[0]?.split('\t')[0];
  } catch { /* no bundled list */ }
}
if (!feed) { console.error('No feed URL given and services/ai/seed/feeds.txt is missing. Pass one: npm run intel:connect-demo -- https://…'); process.exit(1); }

const login = await fetch(`${base}/api/auth/login`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ email: 'podcaster@podbae.local', password: 'demo123' }) });
if (!login.ok) { console.error('login failed', login.status, await login.text()); process.exit(1); }
const cookie = login.headers.getSetCookie().map((c) => c.split(';')[0]).join('; ');
const call = (p, init = {}) => fetch(`${base}${p}`, { ...init, headers: { 'content-type': 'application/json', cookie, ...(init.headers ?? {}) } }).then(async (r) => ({ status: r.status, body: await r.json().catch(() => ({})) }));

console.log(`Connecting demo podcaster to ${feed}`);
const r = await call('/api/agent/ingest-rss', { method: 'POST', body: JSON.stringify({ rssUrl: feed }) });
console.log(r.status, JSON.stringify(r.body));
if (r.status !== 202 || !r.body.ai_available) { console.error('AI service not reachable: start everything with `npm run dev`.'); process.exit(1); }

const t0 = Date.now();
for (;;) {
  const s = await call('/api/intel/my/status');
  const j = s.body.job;
  process.stdout.write(`\r  job ${j?.status ?? '?'} ${j?.percent ?? 0}%  stages: ${(j?.stages_done ?? []).join(', ')}      `);
  if (j?.status === 'succeeded') { console.log('\nDone. Open http://localhost:5173/intelligence (log in as podcaster@podbae.local / demo123).'); break; }
  if (j?.status === 'failed') { console.error('\nIngestion failed:', j.last_error); process.exit(1); }
  if (Date.now() - t0 > 180_000) { console.error('\nTimed out waiting for the job.'); process.exit(1); }
  await new Promise((r2) => setTimeout(r2, 1500));
}
