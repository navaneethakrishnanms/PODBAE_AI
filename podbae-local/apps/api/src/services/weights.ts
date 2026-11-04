import { readFileSync } from 'node:fs';
import path from 'node:path';
import { REPO_ROOT } from '../config.js';

export const DEFAULT_WEIGHTS: Record<string, number> = {
  genreScore: 0.25, locationScore: 0.15, toneScore: 0.15, keywordScore: 0.15,
  vibeScore: 0.2, performanceScore: 0.1, listenScore: 0,
};
export const DEFAULT_PERF = { halfLifeDays: 45 };

/** Reads services/ai/app/weights.yaml (single config shared with the Python service). */
export function load(): { weights: Record<string, number>; halfLifeDays: number } {
  try {
    const text = readFileSync(path.join(REPO_ROOT, 'services/ai/app/weights.yaml'), 'utf8');
    const weights: Record<string, number> = {};
    let section = '';
    let half = DEFAULT_PERF.halfLifeDays;
    for (const line of text.split(/\r?\n/)) {
      const top = line.match(/^(\w+):/);
      if (top) { section = top[1]; continue; }
      const m = line.match(/^\s+(\w+):\s*([\d.]+)/);
      if (!m) continue;
      if (section === 'weights') weights[m[1]] = Number(m[2]);
      if (section === 'performance' && m[1] === 'recency_half_life_days') half = Number(m[2]);
    }
    return Object.keys(weights).length ? { weights, halfLifeDays: half } : { weights: DEFAULT_WEIGHTS, halfLifeDays: half };
  } catch {
    return { weights: DEFAULT_WEIGHTS, halfLifeDays: DEFAULT_PERF.halfLifeDays };
  }
}
