import { describe, expect, it } from 'vitest';
import { applyMatchLimit, isUnlimited, tierConfig } from '../src/services/tiers.js';

describe('tiers', () => {
  it('flirt shows only top 3 matches/day', () => {
    expect(applyMatchLimit([1, 2, 3, 4, 5], 'flirt')).toEqual([1, 2, 3]);
  });
  it('commit is unlimited and unlocks Hey Bae', () => {
    expect(applyMatchLimit([1, 2, 3, 4, 5], 'commit')).toHaveLength(5);
    expect(tierConfig('commit').heyBae).toBe(true);
    expect(isUnlimited(tierConfig('commit').swipesPerDay)).toBe(true);
  });
  it('unknown tier falls back to flirt', () => {
    expect(tierConfig('nope').matchesPerDay).toBe(3);
  });
});
