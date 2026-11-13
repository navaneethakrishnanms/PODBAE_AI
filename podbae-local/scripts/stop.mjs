// `npm run stop`: stops anything of ours still listening on 5173 (web), 5000 (api), 8000 (ai), including orphaned
// uvicorn workers left by an interrupted `npm run dev`. Only kills processes whose command line looks like ours.
import { execFileSync } from 'node:child_process';

const PORTS = [5173, 5000, 8000];
const OURS = /vite|tsx|uvicorn|dev-ai|podbae|multiprocessing\.spawn/i;
if (process.platform !== 'win32') {
  for (const p of PORTS) { try { execFileSync('sh', ['-c', `lsof -ti tcp:${p} | xargs -r kill`]); } catch { /* none */ } }
  process.exit(0);
}
const ps = `$ErrorActionPreference='SilentlyContinue';
$out=@(); Get-NetTCPConnection -State Listen | Where-Object { $_.LocalPort -in ${PORTS.join(',')} } | ForEach-Object {
  $p=Get-CimInstance Win32_Process -Filter "ProcessId=$($_.OwningProcess)"; $out += [pscustomobject]@{port=$_.LocalPort; pid=$_.OwningProcess; cmd=$p.CommandLine} }
Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -like '*uvicorn*app.main:app*' } | ForEach-Object {
  $out += [pscustomobject]@{port=0; pid=$_.ProcessId; cmd=$_.CommandLine} }
$out | ConvertTo-Json -Compress`;
const raw = execFileSync('powershell', ['-NoProfile', '-Command', ps], { encoding: 'utf8' }).trim();
const rows = raw ? [].concat(JSON.parse(raw)) : [];
const seen = new Set();
for (const r of rows) {
  if (seen.has(r.pid)) continue;
  seen.add(r.pid);
  if (!OURS.test(r.cmd ?? '')) { console.log(`skip pid ${r.pid} on port ${r.port}: not a PodBae process (${(r.cmd ?? '?').slice(0, 80)})`); continue; }
  try { execFileSync('taskkill', ['/PID', String(r.pid), '/T', '/F'], { stdio: 'ignore' }); console.log(`stopped pid ${r.pid}${r.port ? ` (port ${r.port})` : ''}`); }
  catch { /* already gone */ }
}
if (!seen.size) console.log('nothing running on 5173/5000/8000');
