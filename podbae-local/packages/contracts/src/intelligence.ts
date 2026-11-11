// Layer 1 (Podcast Intelligence) contracts — TS mirror of services/ai/app/intel/api.py + profile.py (pydantic/JSON).
// The web app and Node API talk to the intelligence store ONLY through the AI service /v1 HTTP API.
import { z } from 'zod';

export const DATA_TIERS = ['verified', 'creator_provided', 'estimated', 'inferred'] as const;
export type DataTier = (typeof DATA_TIERS)[number];
export const TIER_LABELS: Record<DataTier, string> = {
  verified: 'Verified', creator_provided: 'Creator-provided', estimated: 'Estimated', inferred: 'AI-inferred',
};
export const FRESHNESS = ['fresh', 'stale', 'no_expiry'] as const;
export const ACTIVITY = ['active', 'slowing', 'inactive'] as const;
export const JOB_STATUSES = ['queued', 'running', 'succeeded', 'failed', 'cancelled'] as const;
export const INGEST_STAGES = ['feed', 'directory', 'transcripts', 'enrich', 'embed'] as const;
export const COLLAB_OPENNESS = ['open', 'selective', 'closed'] as const;

export const IntelJobSchema = z.object({
  id: z.string(), type: z.string(), status: z.enum(JOB_STATUSES), attempts: z.number(), max_attempts: z.number(),
  last_error: z.string().nullable(), stages_done: z.array(z.string()), stages: z.array(z.string()), percent: z.number(),
  show_id: z.string().nullable().optional(), result: z.record(z.any()).nullable(), created_at: z.string(), updated_at: z.string(),
});
export type IntelJob = z.infer<typeof IntelJobSchema>;

export const IntelEvidenceSchema = z.object({ id: z.number(), snippet: z.string().max(300), locator: z.record(z.any()) });

export const ProfileFieldSchema = z.object({
  label: z.string(), group: z.string(), value: z.any(),
  data_tier: z.enum(DATA_TIERS), tier_label: z.string(),
  source: z.object({ name: z.string(), kind: z.string() }), source_ref: z.string().nullable(), method: z.string(),
  model_version: z.string().nullable(), fetched_at: z.string(), expires_at: z.string().nullable(),
  freshness: z.enum(FRESHNESS), confidence: z.number().min(0).max(1), low_confidence: z.boolean(),
  evidence: z.array(IntelEvidenceSchema),
  alternatives: z.array(z.object({ value: z.any(), data_tier: z.enum(DATA_TIERS), source: z.string(), fetched_at: z.string() })),
  conflict: z.boolean(), provenance_id: z.number(),
});
export type ProfileField = z.infer<typeof ProfileFieldSchema>;

export const PodcastIntelligenceProfileSchema = z.object({
  show_id: z.string(), title: z.string(), feed_url: z.string(),
  status: z.enum(['preliminary', 'partial', 'complete']),
  completeness: z.object({ score: z.number(), by_group: z.record(z.number()), max: z.number() }),
  fields: z.record(ProfileFieldSchema),
  missing: z.array(z.object({ field: z.string(), label: z.string(), group: z.string() })),
  improve: z.array(z.object({ code: z.string(), gain_points: z.number(), action: z.string(), detail: z.string() })),
  warnings: z.array(z.object({ code: z.string(), message: z.string(), severity: z.string(), fields: z.array(z.string()).optional() })),
  refresh_job: z.object({ id: z.string(), status: z.string() }).nullable(),
  feed: z.object({ last_fetch_at: z.string().nullable(), last_fetch_ok: z.boolean().nullable(), last_error: z.string().nullable() }),
  generated_at: z.string(), trust_note: z.string(),
});
export type PodcastIntelligenceProfile = z.infer<typeof PodcastIntelligenceProfileSchema>;

export const IntelShowSummarySchema = z.object({
  id: z.string(), title: z.string(), language: z.string().nullable(), activity: z.enum(ACTIVITY).nullable(),
  categories: z.array(z.string()), episode_count: z.number().nullable(), last_published: z.string().nullable(),
  description: z.string(), feed_url: z.string(), data_tier: z.literal('verified'), source: z.literal('rss'),
  last_fetch_at: z.string().nullable(), last_fetch_ok: z.boolean().nullable(),
});
export type IntelShowSummary = z.infer<typeof IntelShowSummarySchema>;

export const IngestRssRequestSchema = z.object({ rss_url: z.string().url(), user_id: z.string().optional(), force: z.boolean().optional() });
export const DiscoverRequestSchema = z.object({ query: z.string().optional(), category: z.string().optional(), limit: z.number().int().min(1).max(100).default(25) });
export const CreatorProfileSchema = z.object({
  user_id: z.string().optional(), goals: z.array(z.string()).max(10).optional(),
  collaboration_openness: z.enum(COLLAB_OPENNESS).optional(), blocked_categories: z.array(z.string()).max(20).optional(),
});

export const AUDIENCE_KINDS = ['countries', 'cities', 'age_bands', 'totals'] as const;
export const AudienceMappingSchema = z.object({
  kind: z.enum(AUDIENCE_KINDS), label_col: z.string().nullable().optional(), value_col: z.string().nullable().optional(),
  percent_col: z.string().nullable().optional(), columns: z.record(z.string()).optional(),
});
export type AudienceMapping = z.infer<typeof AudienceMappingSchema>;

export const SimilarShowSchema = z.object({
  show_id: z.string(), title: z.string(), similarity: z.number(), space: z.enum(['content', 'style']),
  reason_fields: z.record(z.any()), language: z.string().nullable(),
});

/** Interpretive fields, always data_tier='inferred'. Phase 1: produced by rules (method 'rule') or the local embedding model
 *  (method 'model' / 'rule+model'); no LLM is called. A later LLM phase may refine them (method 'llm'), never other fields.
 *  Demographics / counts are NOT representable here, by design. */
export const INFERRED_FIELDS = ['topics', 'vibe', 'tone', 'conversational_style', 'values', 'guest_friendliness', 'brand_safety_flags', 'likely_audience'] as const;
/** @deprecated name kept for compatibility; see INFERRED_FIELDS. */
export const LLM_INFERRED_FIELDS = INFERRED_FIELDS;
/** Conversational style values. 'unknown' = no rule was confident (never a guess). */
export const CONVERSATIONAL_STYLES = ['solo_monologue', 'co_hosted_banter', 'interview', 'panel', 'narrative_storytelling', 'unknown'] as const;
