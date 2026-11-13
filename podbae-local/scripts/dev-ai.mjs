// Starts the AI service with the torch_gpu Python DIRECTLY (not through `conda run`), so stopping `npm run dev` really
// stops it: `conda run` + uvicorn --reload on Windows left orphaned servers and hung on reload (Phase 2 finding).
//   node scripts/dev-ai.mjs            -> no reload (default, used by `npm run dev`)
//   node scripts/dev-ai.mjs --reload   -> auto-reload for AI development (`npm run dev:ai:reload`)
// Python is found via TORCH_GPU_PYTHON, else `conda run -n torch_gpu python -c "print(sys.executable)"`.
import { execFileSync, execSync, spawn } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const reload = process.argv.includes('--reload');
let py = process.env.TORCH_GPU_PYTHON;
if (!py) {
  try {
    // one quoted command string: with shell on Windows, separate args lose their quoting
    py = execSync('conda run -n torch_gpu python -c "import sys;print(sys.executable)"', { encoding: 'utf8' }).trim().split(/\r?\n/).pop();
  } catch (e) {
    console.error('[dev-ai] could not locate the torch_gpu Python (set TORCH_GPU_PYTHON or install conda env torch_gpu):', e.message);
    process.exit(1);
  }
}
const args = ['-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8000', ...(reload ? ['--reload'] : [])];
console.log(`[dev-ai] ${py} ${args.join(' ')}`);
const child = spawn(py, args, { cwd: path.join(root, 'services', 'ai'), stdio: 'inherit', env: { ...process.env, PYTHONUNBUFFERED: '1' } });

let stopping = false;
function stop(code = 0) {
  if (stopping) return;
  stopping = true;
  if (child.exitCode === null && child.pid) {
    if (process.platform === 'win32') {
      try { execFileSync('taskkill', ['/PID', String(child.pid), '/T', '/F'], { stdio: 'ignore' }); } catch { /* already gone */ }
    } else {
      child.kill('SIGTERM');
    }
  }
  process.exit(code);
}
for (const sig of ['SIGINT', 'SIGTERM', 'SIGBREAK', 'SIGHUP']) process.on(sig, () => stop(0));
process.on('exit', () => { if (!stopping && child.exitCode === null && child.pid && process.platform === 'win32') {
  try { execFileSync('taskkill', ['/PID', String(child.pid), '/T', '/F'], { stdio: 'ignore' }); } catch { /* gone */ } } });
child.on('exit', (code) => { if (!stopping) { console.error(`[dev-ai] AI service exited with code ${code}`); process.exit(code ?? 1); } });
