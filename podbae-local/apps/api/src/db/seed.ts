import { CATEGORIES } from '@podbae/contracts';
import bcrypt from 'bcryptjs';
import { generatePredictions, runMatching } from '../services/matching.js';
import { db, q, q1 } from './client.js';
import * as s from './schema.js';

const [ARTS, COMEDY, NEWS, SOCIAL] = CATEGORIES;
const DAY = 86400_000;

const PODCASTERS = [
  { email: 'podcaster@podbae.local', pw: 'demo123', owner: 'Demo Host', show: 'Laugh Track Lounge', cat: [COMEDY], loc: 'New York, NY',
    vibe: ['Casual', 'Humorous', 'Energetic'], tone: ['Playful', 'Witty'], kw: ['comedy', 'banter', 'humor'],
    collab: ['Promo Swap/Feed Swap', 'Guest Swap'], last: 3, verified: true, featured: 1, tier: 'flirt' },
  { email: 'founder@demo.podbae.local', pw: 'demo123', owner: 'Devon Reed', show: 'Founder Fuel', cat: [ARTS], loc: 'Atlanta, GA',
    vibe: ['Professional', 'Educational', 'Inspirational'], tone: ['Direct', 'Calm'], kw: ['startups', 'business', 'founders'],
    collab: ['Guest Swap', 'Sponsorship'], last: 10, verified: true, featured: 2, tier: 'date' },
  { email: 'mindful@demo.podbae.local', pw: 'demo123', owner: 'Priya Nair', show: 'Mindful Mornings', cat: [ARTS], loc: 'Los Angeles, CA',
    vibe: ['Relaxed', 'Wellness-Focused', 'Reflective'], tone: ['Calm', 'Warm'], kw: ['wellness', 'meditation', 'calm'],
    collab: ['Promo Swap/Feed Swap', 'Sponsorship'], last: 21, verified: true, featured: 0, tier: 'commit' },
  { email: 'gridiron@demo.podbae.local', pw: 'demo123', owner: 'Sam Okafor', show: 'Gridiron Gab', cat: [COMEDY], loc: 'Houston, TX',
    vibe: ['Energetic', 'Casual', 'Humorous'], tone: ['Playful', 'Direct'], kw: ['sports', 'football', 'fans'],
    collab: ['Live Event', 'Guest Swap'], last: 5, verified: false, featured: 0, tier: 'flirt' },
  { email: 'crime@demo.podbae.local', pw: 'demo123', owner: 'Lena Fischer', show: 'True Crime Tuesday', cat: [NEWS], loc: 'Chicago, IL',
    vibe: ['Compelling', 'Personal Narrative', 'Reflective'], tone: ['Intense', 'Direct'], kw: ['crime', 'mystery', 'investigation'],
    collab: ['Guest Swap', 'Sponsorship'], last: 40, verified: true, featured: 3, tier: 'flirt' },
  { email: 'learn@demo.podbae.local', pw: 'demo123', owner: 'Jo Alvarez', show: 'Learn Out Loud', cat: [ARTS], loc: 'Los Angeles, CA',
    vibe: ['Educational', 'Uplifting', 'Personal Narrative'], tone: ['Warm', 'Calm'], kw: ['teaching', 'education', 'learning'],
    collab: ['Promo Swap/Feed Swap'], last: 12, verified: false, featured: 0, tier: 'flirt' },
  { email: 'justice@demo.podbae.local', pw: 'demo123', owner: 'Marcus Webb', show: 'Justice Beat', cat: [NEWS], loc: 'Chicago, IL',
    vibe: ['Professional', 'Compelling', 'Inspirational'], tone: ['Intellectual', 'Direct'], kw: ['justice', 'news', 'community'],
    collab: ['Guest Swap', 'Live Event'], last: 2, verified: true, featured: 0, tier: 'flirt' },
  { email: 'creator@demo.podbae.local', pw: 'demo123', owner: 'Tasha Boyd', show: 'Creator Corner', cat: [SOCIAL], loc: 'New York, NY',
    vibe: ['Casual', 'Energetic', 'Inspirational'], tone: ['Witty', 'Playful'], kw: ['creators', 'social media', 'growth'],
    collab: ['Promo Swap/Feed Swap', 'Guest Swap'], last: 60, verified: false, featured: 0, tier: 'flirt' },
];

const ADVERTISERS = [
  { email: 'brand@podbae.local', org: 'Demo Brew Co', type: 'Local Business', budget: 300, loc: 'New York, NY', cat: [COMEDY, ARTS],
    vibe: ['Casual', 'Energetic'], tone: ['Playful', 'Warm'], values: ['local', 'sustainable'], goals: ['brand awareness'], camp: ['Morning Roast Spots', 300, 600] },
  { email: 'fit@demo.podbae.local', org: 'Demo FitGear', type: 'Emerging Brand', budget: 500, loc: 'Houston, TX', cat: [COMEDY],
    vibe: ['Energetic', 'Inspirational'], tone: ['Direct'], values: ['health'], goals: ['sales'], camp: ['Season Kickoff Gear', 500, 1500] },
  { email: 'edu@demo.podbae.local', org: 'Demo LearnLab', type: 'Agency', budget: 800, loc: 'Los Angeles, CA', cat: [ARTS],
    vibe: ['Educational', 'Professional'], tone: ['Calm', 'Direct'], values: ['education'], goals: ['lead gen'], camp: ['Back-to-School', 800, 2000] },
  { email: 'shop@demo.podbae.local', org: 'Demo Corner Shop', type: 'Local Business', budget: 150, loc: 'Chicago, IL', cat: [NEWS, COMEDY],
    vibe: ['Casual', 'Relaxed'], tone: ['Warm'], values: ['community'], goals: ['local reach'], camp: ['Neighborhood Night', 150, 300] },
  { email: 'ngo@demo.podbae.local', org: 'Demo Open Voices', type: 'Nonprofit', budget: 200, loc: 'Atlanta, GA', cat: [NEWS, ARTS],
    vibe: ['Wellness-Focused', 'Uplifting'], tone: ['Warm', 'Calm'], values: ['mental health'], goals: ['donations'], camp: ['Mind Matters Month', 200, 800] },
];

const VENUES = [
  { email: 'venue.nyc@demo.podbae.local', name: 'Demo Loft NYC', type: 'Recording studio', loc: 'New York, NY', cap: 40, cat: [COMEDY, SOCIAL], vibe: ['Casual', 'Energetic'], tone: ['Playful'] },
  { email: 'venue.atl@demo.podbae.local', name: 'Demo Studio ATL', type: 'Podcast studio', loc: 'Atlanta, GA', cap: 25, cat: [ARTS], vibe: ['Professional'], tone: ['Direct'] },
  { email: 'venue.la@demo.podbae.local', name: 'Demo Sound LA', type: 'Small theater', loc: 'Los Angeles, CA', cap: 120, cat: [ARTS, COMEDY], vibe: ['Relaxed', 'Uplifting'], tone: ['Calm'] },
  { email: 'venue.cafe@demo.podbae.local', name: 'Demo Cafe NYC', type: 'Cafe back room', loc: 'New York, NY', cap: 60, cat: [COMEDY, ARTS], vibe: ['Casual', 'Relaxed'], tone: ['Warm'] },
];

const GUESTS = [
  { email: 'guest1@demo.podbae.local', name: 'Dr. Demo Alder', exp: 'Sleep science', loc: 'Los Angeles, CA', cat: [ARTS], topics: ['sleep', 'wellness'], vibe: ['Educational', 'Relaxed'], tone: ['Calm'] },
  { email: 'guest2@demo.podbae.local', name: 'Demo Riley Chen', exp: 'Bootstrapped startups', loc: 'New York, NY', cat: [ARTS, SOCIAL], topics: ['startups', 'business'], vibe: ['Professional', 'Inspirational'], tone: ['Direct'] },
  { email: 'guest3@demo.podbae.local', name: 'Demo Tasha Comic', exp: 'Stand-up comedy', loc: 'Atlanta, GA', cat: [COMEDY], topics: ['comedy', 'banter'], vibe: ['Humorous', 'Energetic'], tone: ['Witty'] },
  { email: 'guest4@demo.podbae.local', name: 'Demo Marcus Cold', exp: 'Cold-case analysis', loc: 'Chicago, IL', cat: [NEWS], topics: ['crime', 'mystery'], vibe: ['Compelling', 'Reflective'], tone: ['Direct'] },
  { email: 'guest5@demo.podbae.local', name: 'Demo Elena Voss', exp: 'Classroom innovation', loc: 'Los Angeles, CA', cat: [ARTS], topics: ['teaching', 'education'], vibe: ['Uplifting', 'Educational'], tone: ['Warm'] },
];

export async function seedDatabase(): Promise<{ skipped: boolean }> {
  if (await q1(`SELECT 1 FROM users WHERE email = 'admin@podbae.local'`)) return { skipped: true };
  const rounds = process.env.NODE_ENV === 'test' ? 4 : 10;
  const hash = (pw: string) => bcrypt.hash(pw, rounds);
  const user = async (email: string, pw: string, name: string, role: string, tier = 'flirt') =>
    (await db.insert(s.users).values({ email, passwordHash: await hash(pw), name, role, tier, onboarded: true, demo: true }).returning())[0];
  const source = (entityType: string, entityId: number) =>
    db.insert(s.dataSources).values({ entityType, entityId, source: 'manual', ref: 'seed:demo', payload: { demo: true } }).onConflictDoNothing();

  await user('admin@podbae.local', 'admin123', 'Demo Admin', 'admin', 'premium');

  const podcasterIds: number[] = [];
  for (const p of PODCASTERS) {
    const u = await user(p.email, p.pw, p.owner, 'podcaster', p.tier);
    podcasterIds.push(u.id);
    const lastAt = new Date(Date.now() - p.last * DAY);
    const [pod] = await db.insert(s.podcasts).values({
      ownerUserId: u.id, source: 'manual', name: p.show, description: `${p.show}: a fake demo show hosted by ${p.owner}.`,
      author: p.owner, categories: p.cat, location: p.loc, vibeTags: p.vibe, toneTags: p.tone, keywords: p.kw, topics: p.kw.slice(0, 2),
      audienceSummary: 'Demo audience (fake).', collaborationTypes: p.collab, goals: 'Grow audience and find partners',
      verified: p.verified, featured: p.featured > 0, featuredOrder: p.featured, demo: true, episodeCount: 8, lastEpisodeAt: lastAt,
    }).returning();
    await db.insert(s.episodes).values(Array.from({ length: 8 }, (_, i) => ({
      podcastId: pod.id, guid: `demo-${pod.id}-${i + 1}`, title: `${p.show} — Episode ${8 - i}`,
      description: `Demo episode ${8 - i} of ${p.show}.`, publishedAt: new Date(lastAt.getTime() - i * 7 * DAY), durationSec: 1500 + i * 90,
    })));
    await source('podcast', pod.id);
  }

  for (const a of ADVERTISERS) {
    const u = await user(a.email, 'demo123', a.org, 'advertiser');
    const [adv] = await db.insert(s.advertisers).values({
      userId: u.id, orgName: a.org, orgType: a.type, description: `${a.org} (fake demo brand).`, budgetMin: a.budget, audience: 'Demo audience',
      vibeTags: a.vibe, toneTags: a.tone, brandValues: a.values, categories: a.cat, goals: a.goals, location: a.loc,
      contactName: 'Demo Contact', contactEmail: a.email, demo: true,
    }).returning();
    await db.insert(s.campaigns).values({
      advertiserId: adv.id, name: a.camp[0] as string, description: 'Host-read sponsorship spots (fake).', budgetMin: a.camp[1] as number,
      budgetMax: a.camp[2] as number, categories: a.cat, vibeTags: a.vibe, toneTags: a.tone, location: a.loc, demo: true,
    });
    await source('advertiser', adv.id);
  }

  for (const v of VENUES) {
    const u = await user(v.email, 'demo123', v.name, 'venue');
    const [row] = await db.insert(s.venues).values({
      userId: u.id, name: v.name, venueType: v.type, location: v.loc, capacity: v.cap, description: `${v.name} (fake demo venue).`,
      categories: v.cat, vibeTags: v.vibe, toneTags: v.tone, contactEmail: v.email, demo: true,
    }).returning();
    await source('venue', row.id);
  }

  for (const g of GUESTS) {
    const u = await user(g.email, 'demo123', g.name, 'guest');
    const [row] = await db.insert(s.guests).values({
      userId: u.id, name: g.name, expertise: g.exp, bio: `${g.name}: fake demo guest.`, topics: g.topics, categories: g.cat,
      vibeTags: g.vibe, toneTags: g.tone, location: g.loc, contactEmail: g.email, demo: true,
    }).returning();
    await source('guest', row.id);
  }

  // matches + predictions (in-process scoring, so seeding never needs the Python service)
  for (const id of podcasterIds) {
    await runMatching(id, { forceLocal: true });
    await generatePredictions(id, 2);
  }

  const demoId = podcasterIds[0];
  await db.insert(s.notifications).values([
    { userId: demoId, type: 'welcome', title: 'Welcome to PodBae 💕', body: 'Your demo profile is ready.' },
    { userId: demoId, type: 'matches', title: 'Your daily matches are ready', body: 'Open the dashboard to see your top matches.' },
    { userId: demoId, type: 'prediction', title: 'New opportunity predicted', body: 'Check the Predictions tab.' },
  ]);
  await q('SELECT 1');
  return { skipped: false };
}
