// FROZEN CONTRACT — shared by apps/api, apps/web and mirrored by services/ai (pydantic).
import { z } from 'zod';

// ---------- fixed vocabularies ----------
export const VIBE_TAGS = [
  'Casual', 'Compelling', 'Educational', 'Energetic', 'Humorous', 'Inspirational',
  'Personal Narrative', 'Professional', 'Reflective', 'Relaxed', 'Uplifting', 'Wellness-Focused',
] as const;
export const TONE_TAGS = [
  'Warm', 'Witty', 'Direct', 'Calm', 'Playful', 'Intense', 'Intellectual', 'Edgy',
] as const;
// Category labels exactly as the live MVP intake presents them.
export const CATEGORIES = [
  'Podcaster- Arts/Education/Kids',
  'Podcaster- Entertainment/ Comedy/ Society & Culture',
  'Podcaster- News/ Social Justice/ True Crime',
  'Host- IG/Tik Tok/ YouTube/Social Media',
] as const;
export const COLLAB_TYPES = ['Promo Swap/Feed Swap', 'Guest Swap', 'Sponsorship', 'Live Event'] as const;
/** Podcasts that offer this collaboration type are also surfaced as "collaborator" matches. */
export const COLLABORATOR_COLLAB_TYPE = 'Guest Swap';
export const ORG_TYPES = ['Emerging Brand', 'Local Business', 'Agency', 'Nonprofit', 'Creator/Founder', 'Other'] as const;
export const USER_ROLES = ['podcaster', 'advertiser', 'venue', 'guest', 'admin'] as const;
export const TIERS = ['flirt', 'date', 'commit', 'premium'] as const;
export const TARGET_TYPES = ['podcast', 'sponsor', 'guest', 'venue', 'collaborator'] as const;
export const MIN_CAMPAIGN_BUDGET = 150;

export const TierSchema = z.enum(TIERS);
export const TargetTypeSchema = z.enum(TARGET_TYPES);
export const UserRoleSchema = z.enum(USER_ROLES);

// ---------- core entities ----------
export const EvidenceSchema = z.object({
  source: z.string(),
  ref: z.string(),
  fetchedAt: z.string(),
});

export const ExplanationSchema = z.object({
  summary: z.string(),
  reasons: z.array(z.string()),
  whyNow: z.string().optional(),
  evidence: z.array(EvidenceSchema),
});

export const ScoreBreakdownSchema = z.object({
  genreScore: z.number(),
  locationScore: z.number(),
  toneScore: z.number(),
  keywordScore: z.number(),
  vibeScore: z.number(),
  performanceScore: z.number(),
  listenScore: z.number(),
  weights: z.record(z.number()),
  total: z.number(),
});

export const PodcastSchema = z.object({
  id: z.number(),
  ownerUserId: z.number().nullable(),
  source: z.enum(['taddy', 'rss', 'manual']),
  sourceId: z.string().nullable().optional(),
  rssUrl: z.string().nullable().optional(),
  name: z.string(),
  description: z.string().nullable().optional(),
  author: z.string().nullable().optional(),
  artworkUrl: z.string().nullable().optional(),
  language: z.string().nullable().optional(),
  categories: z.array(z.string()),
  location: z.string().nullable().optional(),
  episodeCount: z.number(),
  lastEpisodeAt: z.string().nullable().optional(),
  vibeTags: z.array(z.string()),
  toneTags: z.array(z.string()),
  topics: z.array(z.string()),
  audienceSummary: z.string().nullable().optional(),
  collaborationTypes: z.array(z.string()),
  verified: z.boolean(),
  demo: z.boolean(),
  enrichmentVersion: z.number().nullable().optional(),
  enrichedAt: z.string().nullable().optional(),
});

export const EpisodeSchema = z.object({
  id: z.number(),
  podcastId: z.number(),
  guid: z.string(),
  title: z.string(),
  description: z.string().nullable().optional(),
  publishedAt: z.string().nullable().optional(),
  durationSec: z.number().nullable().optional(),
  audioUrl: z.string().nullable().optional(),
  transcriptUrl: z.string().nullable().optional(),
  transcriptText: z.string().nullable().optional(),
});

export const MatchSchema = z.object({
  id: z.number(),
  userId: z.number(),
  targetType: TargetTypeSchema,
  targetId: z.number(),
  targetUserId: z.number().nullable().optional(),
  totalScore: z.number(),
  scoreBreakdown: ScoreBreakdownSchema,
  explanation: ExplanationSchema,
  status: z.string(),
  createdAt: z.string(),
});

export const PredictionSchema = z.object({
  id: z.number(),
  userId: z.number(),
  type: z.string(),
  title: z.string(),
  payload: z.record(z.unknown()),
  score: z.number(),
  why: z.string().nullable().optional(),
  whyNow: z.string().nullable().optional(),
  evidence: z.array(EvidenceSchema),
  status: z.enum(['new', 'saved', 'dismissed', 'acted']),
  createdAt: z.string(),
});
export const OpportunitySchema = PredictionSchema;

export const HeyBaeMessageSchema = z.object({
  id: z.number(),
  userId: z.number(),
  role: z.enum(['user', 'assistant']),
  content: z.string(),
  createdAt: z.string(),
});

// ---------- API <-> AI service contract ----------
export const MatchCandidateSchema = z.object({
  id: z.number(),
  type: TargetTypeSchema,
  userId: z.number().nullable().optional(),
  name: z.string(),
  categories: z.array(z.string()).default([]),
  location: z.string().nullable().optional(),
  vibeTags: z.array(z.string()).default([]),
  toneTags: z.array(z.string()).default([]),
  keywords: z.array(z.string()).default([]),
  lastEpisodeAt: z.string().nullable().optional(),
  episodeCount: z.number().nullable().optional(),
});
export const MatchSubjectSchema = MatchCandidateSchema.omit({ type: true });

export const MatchRequestSchema = z.object({
  podcast: MatchSubjectSchema,
  candidates: z.array(MatchCandidateSchema),
  targetTypes: z.array(TargetTypeSchema).default([...TARGET_TYPES]),
  limit: z.number().int().positive().default(50),
});

export const MatchResultSchema = z.object({
  targetType: TargetTypeSchema,
  targetId: z.number(),
  totalScore: z.number(),
  scoreBreakdown: ScoreBreakdownSchema,
  explanation: ExplanationSchema,
});
export const MatchResponseSchema = z.object({ matches: z.array(MatchResultSchema) });

// ---------- request bodies ----------
export const RegisterSchema = z.object({
  email: z.string().email(),
  password: z.string().min(8),
  name: z.string().min(1).optional(),
  role: z.enum(['podcaster', 'guest', 'venue', 'advertiser']).default('podcaster'),
});
export const LoginSchema = z.object({ email: z.string().email(), password: z.string().min(1) });

/** Sent with an intake when the visitor is not logged in: creates the account. */
export const AccountSchema = z.object({
  email: z.string().email(),
  password: z.string().min(8),
  name: z.string().min(1).optional(),
});

export const ScheduleCreateSchema = z.object({
  title: z.string().min(1),
  startsAt: z.string().min(1),
  notes: z.string().optional(),
});

export const PodcasterSubmissionSchema = z.object({
  account: AccountSchema.optional(),
  showName: z.string().min(1),
  rssUrl: z.string().url().optional().or(z.literal('')),
  categories: z.array(z.string()).min(1),
  vibeTags: z.array(z.string()).default([]),
  toneTags: z.array(z.string()).default([]),
  collaborationTypes: z.array(z.string()).default([]),
  audienceNotes: z.string().optional(),
  location: z.string().optional(),
  goals: z.string().optional(),
});

export const AdvertiserRegisterSchema = z.object({
  email: z.string().email(),
  password: z.string().min(8),
  orgName: z.string().min(1),
  orgType: z.enum(ORG_TYPES),
  budgetMin: z.number().int().min(MIN_CAMPAIGN_BUDGET),
  audience: z.string().optional(),
  vibeTags: z.array(z.string()).default([]),
  brandValues: z.array(z.string()).default([]),
  categories: z.array(z.string()).default([]),
  goals: z.array(z.string()).default([]),
  contactName: z.string().optional(),
  location: z.string().optional(),
});

export const CampaignCreateSchema = z.object({
  name: z.string().min(1),
  description: z.string().optional(),
  budgetMin: z.number().int().min(MIN_CAMPAIGN_BUDGET),
  budgetMax: z.number().int().optional(),
  categories: z.array(z.string()).default([]),
  vibeTags: z.array(z.string()).default([]),
  toneTags: z.array(z.string()).default([]),
  location: z.string().optional(),
});

export const SwipeSchema = z.object({
  targetUserId: z.number().int(),
  direction: z.enum(['left', 'right']),
});

export const TIER_CONFIG = {
  flirt: { price: 0, matchesPerDay: 3, swipesPerDay: 10, ads: true, heyBae: false, forecasting: false, revenueRecs: 0, predictionsLimit: 3 },
  date: { price: 19, matchesPerDay: 10, swipesPerDay: 50, ads: false, heyBae: false, forecasting: false, revenueRecs: 3, predictionsLimit: 10 },
  commit: { price: 29, matchesPerDay: -1, swipesPerDay: -1, ads: false, heyBae: true, forecasting: true, revenueRecs: -1, predictionsLimit: -1 },
  premium: { price: null, matchesPerDay: -1, swipesPerDay: -1, ads: false, heyBae: true, forecasting: true, revenueRecs: -1, predictionsLimit: -1 },
} as const;

export type Podcast = z.infer<typeof PodcastSchema>;
export type Episode = z.infer<typeof EpisodeSchema>;
export type Match = z.infer<typeof MatchSchema>;
export type ScoreBreakdown = z.infer<typeof ScoreBreakdownSchema>;
export type Explanation = z.infer<typeof ExplanationSchema>;
export type Evidence = z.infer<typeof EvidenceSchema>;
export type Prediction = z.infer<typeof PredictionSchema>;
export type HeyBaeMessage = z.infer<typeof HeyBaeMessageSchema>;
export type MatchRequest = z.infer<typeof MatchRequestSchema>;
export type MatchCandidate = z.infer<typeof MatchCandidateSchema>;
export type MatchResponse = z.infer<typeof MatchResponseSchema>;
export type Tier = z.infer<typeof TierSchema>;
export type TargetType = z.infer<typeof TargetTypeSchema>;
