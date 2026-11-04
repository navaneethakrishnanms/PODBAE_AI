import { TIER_CONFIG, type Tier } from '@podbae/contracts';
import { q1 } from '../db/client.js';

export function tierConfig(tier: string) {
  return TIER_CONFIG[(tier as Tier) in TIER_CONFIG ? (tier as Tier) : 'flirt'];
}

export async function swipesToday(userId: number): Promise<number> {
  const r = await q1<{ n: number }>(
    `SELECT count(*)::int AS n FROM swipes WHERE user_id = $1 AND created_at >= date_trunc('day', now())`,
    [userId],
  );
  return r?.n ?? 0;
}

export function isUnlimited(limit: number) {
  return limit < 0;
}

export async function quota(userId: number, tier: string) {
  const cfg = tierConfig(tier);
  const used = await swipesToday(userId);
  const limit = cfg.swipesPerDay;
  return {
    tier,
    quotaUsed: used,
    quotaLimit: limit,
    canSwipe: isUnlimited(limit) || used < limit,
    matchesPerDay: cfg.matchesPerDay,
    features: cfg,
  };
}

/** Pure helper (unit-tested): slice a ranked list to the tier's daily match allowance. */
export function applyMatchLimit<T>(items: T[], tier: string): T[] {
  const n = tierConfig(tier).matchesPerDay;
  return isUnlimited(n) ? items : items.slice(0, n);
}
