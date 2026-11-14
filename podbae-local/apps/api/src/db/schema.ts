// Single source of truth for the database. Migrations are generated from this file (drizzle-kit).
import { sql } from 'drizzle-orm';
import {
  boolean, check, doublePrecision, index, integer, jsonb, pgTable, serial, text, timestamp,
  unique, uniqueIndex, uuid,
} from 'drizzle-orm/pg-core';

const tags = (name: string) => text(name).array().notNull().default(sql`'{}'::text[]`);
const ts = (name: string) => timestamp(name, { withTimezone: true });

export const users = pgTable('users', {
  id: serial('id').primaryKey(),
  email: text('email').notNull().unique(),
  passwordHash: text('password_hash'),
  name: text('name'),
  role: text('role').notNull().default('podcaster'), // podcaster|advertiser|venue|guest|admin
  tier: text('tier').notNull().default('flirt'), // flirt|date|commit|premium
  goals: tags('goals'),
  publicProfile: jsonb('public_profile').notNull().default({}),
  onboarded: boolean('onboarded').notNull().default(false),
  demo: boolean('demo').notNull().default(false),
  createdAt: ts('created_at').notNull().defaultNow(),
});

export const podcasts = pgTable('podcasts', {
  id: serial('id').primaryKey(),
  ownerUserId: integer('owner_user_id').references(() => users.id, { onDelete: 'set null' }),
  source: text('source').notNull().default('manual'), // taddy|rss|manual
  sourceId: text('source_id'),
  rssUrl: text('rss_url'),
  name: text('name').notNull(),
  description: text('description'),
  author: text('author'),
  artworkUrl: text('artwork_url'),
  language: text('language').default('en'),
  categories: tags('categories'),
  location: text('location'),
  episodeCount: integer('episode_count').notNull().default(0),
  lastEpisodeAt: ts('last_episode_at'),
  vibeTags: tags('vibe_tags'),
  toneTags: tags('tone_tags'),
  topics: tags('topics'),
  keywords: tags('keywords'),
  audienceSummary: text('audience_summary'),
  collaborationTypes: tags('collaboration_types'),
  goals: text('goals'),
  verified: boolean('verified').notNull().default(false),
  featured: boolean('featured').notNull().default(false),
  featuredOrder: integer('featured_order').notNull().default(0),
  demo: boolean('demo').notNull().default(false),
  enrichmentVersion: integer('enrichment_version'),
  enrichedAt: ts('enriched_at'),
  createdAt: ts('created_at').notNull().defaultNow(),
  updatedAt: ts('updated_at').notNull().defaultNow(),
}, (t) => [
  index('podcasts_owner_idx').on(t.ownerUserId),
  uniqueIndex('podcasts_source_uidx').on(t.source, t.sourceId).where(sql`${t.sourceId} is not null`),
  uniqueIndex('podcasts_rss_uidx').on(t.rssUrl).where(sql`${t.rssUrl} is not null`),
]);

export const episodes = pgTable('episodes', {
  id: serial('id').primaryKey(),
  podcastId: integer('podcast_id').notNull().references(() => podcasts.id, { onDelete: 'cascade' }),
  guid: text('guid').notNull(),
  title: text('title').notNull(),
  description: text('description'),
  publishedAt: ts('published_at'),
  durationSec: integer('duration_sec'),
  audioUrl: text('audio_url'),
  transcriptUrl: text('transcript_url'),
  transcriptText: text('transcript_text'),
}, (t) => [unique('episodes_podcast_guid').on(t.podcastId, t.guid)]);

export const advertisers = pgTable('advertisers', {
  id: serial('id').primaryKey(),
  userId: integer('user_id').references(() => users.id, { onDelete: 'cascade' }),
  orgName: text('org_name').notNull(),
  orgType: text('org_type').notNull().default('Other'),
  description: text('description'),
  budgetMin: integer('budget_min'),
  audience: text('audience'),
  vibeTags: tags('vibe_tags'),
  toneTags: tags('tone_tags'),
  brandValues: tags('brand_values'),
  categories: tags('categories'),
  goals: tags('goals'),
  location: text('location'),
  contactName: text('contact_name'),
  contactEmail: text('contact_email'),
  website: text('website'),   // Phase 4: company website DOMAIN only (e.g. betterhelp.com); used for domain-only brand matching
  demo: boolean('demo').notNull().default(false),
  createdAt: ts('created_at').notNull().defaultNow(),
}, (t) => [check('advertisers_budget_min', sql`${t.budgetMin} is null or ${t.budgetMin} >= 150`)]);

export const campaigns = pgTable('campaigns', {
  id: serial('id').primaryKey(),
  advertiserId: integer('advertiser_id').notNull().references(() => advertisers.id, { onDelete: 'cascade' }),
  name: text('name').notNull(),
  description: text('description'),
  budgetMin: integer('budget_min').notNull(),
  budgetMax: integer('budget_max'),
  categories: tags('categories'),
  vibeTags: tags('vibe_tags'),
  toneTags: tags('tone_tags'),
  location: text('location'),
  status: text('status').notNull().default('active'),
  demo: boolean('demo').notNull().default(false),
  createdAt: ts('created_at').notNull().defaultNow(),
}, (t) => [check('campaigns_budget_min', sql`${t.budgetMin} >= 150`)]);

export const venues = pgTable('venues', {
  id: serial('id').primaryKey(),
  userId: integer('user_id').references(() => users.id, { onDelete: 'cascade' }),
  name: text('name').notNull(),
  venueType: text('venue_type'),
  location: text('location'),
  capacity: integer('capacity'),
  description: text('description'),
  categories: tags('categories'),
  vibeTags: tags('vibe_tags'),
  toneTags: tags('tone_tags'),
  contactEmail: text('contact_email'),
  demo: boolean('demo').notNull().default(false),
  createdAt: ts('created_at').notNull().defaultNow(),
});

export const guests = pgTable('guests', {
  id: serial('id').primaryKey(),
  userId: integer('user_id').references(() => users.id, { onDelete: 'cascade' }),
  name: text('name').notNull(),
  expertise: text('expertise'),
  bio: text('bio'),
  topics: tags('topics'),
  categories: tags('categories'),
  vibeTags: tags('vibe_tags'),
  toneTags: tags('tone_tags'),
  location: text('location'),
  contactEmail: text('contact_email'),
  demo: boolean('demo').notNull().default(false),
  createdAt: ts('created_at').notNull().defaultNow(),
});

export const submissions = pgTable('submissions', {
  id: serial('id').primaryKey(),
  userId: integer('user_id').references(() => users.id, { onDelete: 'cascade' }),
  kind: text('kind').notNull(),
  payload: jsonb('payload').notNull().default({}),
  createdAt: ts('created_at').notNull().defaultNow(),
});

export const matches = pgTable('matches', {
  id: serial('id').primaryKey(),
  userId: integer('user_id').notNull().references(() => users.id, { onDelete: 'cascade' }),
  targetType: text('target_type').notNull(), // podcast|sponsor|guest|venue|collaborator
  targetId: integer('target_id').notNull(),
  targetUserId: integer('target_user_id').references(() => users.id, { onDelete: 'set null' }),
  targetSnapshot: jsonb('target_snapshot').notNull().default({}),
  totalScore: doublePrecision('total_score').notNull(),
  scoreBreakdown: jsonb('score_breakdown').notNull().default({}),
  explanation: jsonb('explanation').notNull().default({}),
  status: text('status').notNull().default('new'),
  createdAt: ts('created_at').notNull().defaultNow(),
}, (t) => [unique('matches_user_target').on(t.userId, t.targetType, t.targetId)]);

export const predictions = pgTable('predictions', {
  id: serial('id').primaryKey(),
  userId: integer('user_id').notNull().references(() => users.id, { onDelete: 'cascade' }),
  type: text('type').notNull(),
  title: text('title').notNull(),
  payload: jsonb('payload').notNull().default({}),
  score: doublePrecision('score').notNull().default(0),
  why: text('why'),
  whyNow: text('why_now'),
  evidence: jsonb('evidence').notNull().default([]),
  status: text('status').notNull().default('new'), // new|saved|dismissed|acted
  createdAt: ts('created_at').notNull().defaultNow(),
});

export const swipes = pgTable('swipes', {
  id: serial('id').primaryKey(),
  userId: integer('user_id').notNull().references(() => users.id, { onDelete: 'cascade' }),
  targetUserId: integer('target_user_id').notNull().references(() => users.id, { onDelete: 'cascade' }),
  direction: text('direction').notNull(),
  createdAt: ts('created_at').notNull().defaultNow(),
}, (t) => [unique('swipes_user_target').on(t.userId, t.targetUserId)]);

export const savedMatches = pgTable('saved_matches', {
  id: serial('id').primaryKey(),
  userId: integer('user_id').notNull().references(() => users.id, { onDelete: 'cascade' }),
  matchId: integer('match_id').notNull().references(() => matches.id, { onDelete: 'cascade' }),
  createdAt: ts('created_at').notNull().defaultNow(),
}, (t) => [unique('saved_user_match').on(t.userId, t.matchId)]);

export const conversations = pgTable('conversations', {
  id: serial('id').primaryKey(),
  userA: integer('user_a').notNull().references(() => users.id, { onDelete: 'cascade' }),
  userB: integer('user_b').notNull().references(() => users.id, { onDelete: 'cascade' }),
  createdAt: ts('created_at').notNull().defaultNow(),
}, (t) => [unique('conversations_pair').on(t.userA, t.userB), check('conversations_order', sql`${t.userA} < ${t.userB}`)]);

export const messages = pgTable('messages', {
  id: serial('id').primaryKey(),
  conversationId: integer('conversation_id').notNull().references(() => conversations.id, { onDelete: 'cascade' }),
  senderId: integer('sender_id').notNull().references(() => users.id, { onDelete: 'cascade' }),
  body: text('body').notNull(),
  readAt: ts('read_at'),
  createdAt: ts('created_at').notNull().defaultNow(),
}, (t) => [index('messages_conv_idx').on(t.conversationId, t.createdAt)]);

export const heyBaeMessages = pgTable('hey_bae_messages', {
  id: serial('id').primaryKey(),
  userId: integer('user_id').notNull().references(() => users.id, { onDelete: 'cascade' }),
  role: text('role').notNull(),
  content: text('content').notNull(),
  createdAt: ts('created_at').notNull().defaultNow(),
});

export const notifications = pgTable('notifications', {
  id: serial('id').primaryKey(),
  userId: integer('user_id').notNull().references(() => users.id, { onDelete: 'cascade' }),
  type: text('type').notNull(),
  title: text('title').notNull(),
  body: text('body'),
  read: boolean('read').notNull().default(false),
  createdAt: ts('created_at').notNull().defaultNow(),
});

export const partnershipInvites = pgTable('partnership_invites', {
  id: uuid('id').primaryKey().defaultRandom(),
  /** null for "Invite to PodBae" records created from an opportunity card: we never derive or store a show owner's e-mail. */
  email: text('email'),
  orgName: text('org_name'),
  message: text('message'),
  status: text('status').notNull().default('pending'),
  /** signup (public form) | podbae_invite (Layer 4: invite a non-member show; nothing is sent externally) */
  kind: text('kind').notNull().default('signup'),
  targetShowId: text('target_show_id'),
  opportunityId: text('opportunity_id'),
  createdBy: integer('created_by').references(() => users.id, { onDelete: 'set null' }),
  createdAt: ts('created_at').notNull().defaultNow(),
});

/** Last podcast-partner opportunity list served to each member (Layer 4). Served with an "may be outdated" banner when the AI
 *  service is unreachable, so members still see their stored opportunities. */
export const opportunityCache = pgTable('opportunity_cache', {
  id: serial('id').primaryKey(),
  userId: integer('user_id').notNull().references(() => users.id, { onDelete: 'cascade' }),
  /** partner | sponsor (Phase 3): one cached list per user per opportunity kind */
  kind: text('kind').notNull().default('partner'),
  memberShowId: text('member_show_id'),
  payload: jsonb('payload').notNull(),
  cachedAt: ts('cached_at').notNull().defaultNow(),
}, (t) => [unique('opportunity_cache_user_kind').on(t.userId, t.kind)]);

export const scheduledSessions = pgTable('scheduled_sessions', {
  id: serial('id').primaryKey(),
  userId: integer('user_id').notNull().references(() => users.id, { onDelete: 'cascade' }),
  title: text('title').notNull(),
  startsAt: ts('starts_at').notNull(),
  notes: text('notes'),
  createdAt: ts('created_at').notNull().defaultNow(),
});

// Seams for later phases (kept so the schema is stable):
export const ingestionJobs = pgTable('ingestion_jobs', {
  id: serial('id').primaryKey(),
  source: text('source').notNull(),
  params: jsonb('params').notNull().default({}),
  status: text('status').notNull().default('pending'),
  progress: jsonb('progress').notNull().default({}),
  error: text('error'),
  createdAt: ts('created_at').notNull().defaultNow(),
  updatedAt: ts('updated_at').notNull().defaultNow(),
});

/** Link between an app podcast and its show in the AI service's intelligence store (the app never reads that store directly).
 *  `profile` is the last profile fetched over HTTP, kept so the UI can still show it ("may be outdated") if the AI service is down. */
export const intelLinks = pgTable('intel_links', {
  id: serial('id').primaryKey(),
  podcastId: integer('podcast_id').notNull().unique().references(() => podcasts.id, { onDelete: 'cascade' }),
  intelShowId: text('intel_show_id'),
  rssUrl: text('rss_url'),
  lastJobId: text('last_job_id'),
  profile: jsonb('profile'),
  profileCachedAt: ts('profile_cached_at'),
  createdAt: ts('created_at').notNull().defaultNow(),
  updatedAt: ts('updated_at').notNull().defaultNow(),
});

/** Provenance: every seeded / submitted / external fact shown to users has a row here. */
export const dataSources = pgTable('data_sources', {
  id: serial('id').primaryKey(),
  entityType: text('entity_type').notNull(),
  entityId: integer('entity_id').notNull(),
  source: text('source').notNull(),
  ref: text('ref'),
  fetchedAt: ts('fetched_at').notNull().defaultNow(),
  payload: jsonb('payload'),
}, (t) => [unique('data_sources_entity_source').on(t.entityType, t.entityId, t.source)]);

export const sessions = pgTable('sessions', {
  sid: text('sid').primaryKey(),
  sess: jsonb('sess').notNull(),
  expire: ts('expire').notNull(),
}, (t) => [index('sessions_expire_idx').on(t.expire)]);
