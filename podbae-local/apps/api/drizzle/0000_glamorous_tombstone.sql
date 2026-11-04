CREATE TABLE "advertisers" (
	"id" serial PRIMARY KEY NOT NULL,
	"user_id" integer,
	"org_name" text NOT NULL,
	"org_type" text DEFAULT 'Other' NOT NULL,
	"description" text,
	"budget_min" integer,
	"audience" text,
	"vibe_tags" text[] DEFAULT '{}'::text[] NOT NULL,
	"tone_tags" text[] DEFAULT '{}'::text[] NOT NULL,
	"brand_values" text[] DEFAULT '{}'::text[] NOT NULL,
	"categories" text[] DEFAULT '{}'::text[] NOT NULL,
	"goals" text[] DEFAULT '{}'::text[] NOT NULL,
	"location" text,
	"contact_name" text,
	"contact_email" text,
	"demo" boolean DEFAULT false NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "advertisers_budget_min" CHECK ("advertisers"."budget_min" is null or "advertisers"."budget_min" >= 150)
);
--> statement-breakpoint
CREATE TABLE "campaigns" (
	"id" serial PRIMARY KEY NOT NULL,
	"advertiser_id" integer NOT NULL,
	"name" text NOT NULL,
	"description" text,
	"budget_min" integer NOT NULL,
	"budget_max" integer,
	"categories" text[] DEFAULT '{}'::text[] NOT NULL,
	"vibe_tags" text[] DEFAULT '{}'::text[] NOT NULL,
	"tone_tags" text[] DEFAULT '{}'::text[] NOT NULL,
	"location" text,
	"status" text DEFAULT 'active' NOT NULL,
	"demo" boolean DEFAULT false NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "campaigns_budget_min" CHECK ("campaigns"."budget_min" >= 150)
);
--> statement-breakpoint
CREATE TABLE "conversations" (
	"id" serial PRIMARY KEY NOT NULL,
	"user_a" integer NOT NULL,
	"user_b" integer NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "conversations_pair" UNIQUE("user_a","user_b"),
	CONSTRAINT "conversations_order" CHECK ("conversations"."user_a" < "conversations"."user_b")
);
--> statement-breakpoint
CREATE TABLE "data_sources" (
	"id" serial PRIMARY KEY NOT NULL,
	"entity_type" text NOT NULL,
	"entity_id" integer NOT NULL,
	"source" text NOT NULL,
	"ref" text,
	"fetched_at" timestamp with time zone DEFAULT now() NOT NULL,
	"payload" jsonb,
	CONSTRAINT "data_sources_entity_source" UNIQUE("entity_type","entity_id","source")
);
--> statement-breakpoint
CREATE TABLE "episodes" (
	"id" serial PRIMARY KEY NOT NULL,
	"podcast_id" integer NOT NULL,
	"guid" text NOT NULL,
	"title" text NOT NULL,
	"description" text,
	"published_at" timestamp with time zone,
	"duration_sec" integer,
	"audio_url" text,
	"transcript_url" text,
	"transcript_text" text,
	CONSTRAINT "episodes_podcast_guid" UNIQUE("podcast_id","guid")
);
--> statement-breakpoint
CREATE TABLE "guests" (
	"id" serial PRIMARY KEY NOT NULL,
	"user_id" integer,
	"name" text NOT NULL,
	"expertise" text,
	"bio" text,
	"topics" text[] DEFAULT '{}'::text[] NOT NULL,
	"categories" text[] DEFAULT '{}'::text[] NOT NULL,
	"vibe_tags" text[] DEFAULT '{}'::text[] NOT NULL,
	"tone_tags" text[] DEFAULT '{}'::text[] NOT NULL,
	"location" text,
	"contact_email" text,
	"demo" boolean DEFAULT false NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "hey_bae_messages" (
	"id" serial PRIMARY KEY NOT NULL,
	"user_id" integer NOT NULL,
	"role" text NOT NULL,
	"content" text NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "ingestion_jobs" (
	"id" serial PRIMARY KEY NOT NULL,
	"source" text NOT NULL,
	"params" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"status" text DEFAULT 'pending' NOT NULL,
	"progress" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"error" text,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "matches" (
	"id" serial PRIMARY KEY NOT NULL,
	"user_id" integer NOT NULL,
	"target_type" text NOT NULL,
	"target_id" integer NOT NULL,
	"target_user_id" integer,
	"target_snapshot" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"total_score" double precision NOT NULL,
	"score_breakdown" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"explanation" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"status" text DEFAULT 'new' NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "matches_user_target" UNIQUE("user_id","target_type","target_id")
);
--> statement-breakpoint
CREATE TABLE "messages" (
	"id" serial PRIMARY KEY NOT NULL,
	"conversation_id" integer NOT NULL,
	"sender_id" integer NOT NULL,
	"body" text NOT NULL,
	"read_at" timestamp with time zone,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "notifications" (
	"id" serial PRIMARY KEY NOT NULL,
	"user_id" integer NOT NULL,
	"type" text NOT NULL,
	"title" text NOT NULL,
	"body" text,
	"read" boolean DEFAULT false NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "partnership_invites" (
	"id" uuid PRIMARY KEY DEFAULT gen_random_uuid() NOT NULL,
	"email" text NOT NULL,
	"org_name" text,
	"message" text,
	"status" text DEFAULT 'pending' NOT NULL,
	"created_by" integer,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "podcasts" (
	"id" serial PRIMARY KEY NOT NULL,
	"owner_user_id" integer,
	"source" text DEFAULT 'manual' NOT NULL,
	"source_id" text,
	"rss_url" text,
	"name" text NOT NULL,
	"description" text,
	"author" text,
	"artwork_url" text,
	"language" text DEFAULT 'en',
	"categories" text[] DEFAULT '{}'::text[] NOT NULL,
	"location" text,
	"episode_count" integer DEFAULT 0 NOT NULL,
	"last_episode_at" timestamp with time zone,
	"vibe_tags" text[] DEFAULT '{}'::text[] NOT NULL,
	"tone_tags" text[] DEFAULT '{}'::text[] NOT NULL,
	"topics" text[] DEFAULT '{}'::text[] NOT NULL,
	"keywords" text[] DEFAULT '{}'::text[] NOT NULL,
	"audience_summary" text,
	"collaboration_types" text[] DEFAULT '{}'::text[] NOT NULL,
	"goals" text,
	"verified" boolean DEFAULT false NOT NULL,
	"featured" boolean DEFAULT false NOT NULL,
	"featured_order" integer DEFAULT 0 NOT NULL,
	"demo" boolean DEFAULT false NOT NULL,
	"enrichment_version" integer,
	"enriched_at" timestamp with time zone,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "predictions" (
	"id" serial PRIMARY KEY NOT NULL,
	"user_id" integer NOT NULL,
	"type" text NOT NULL,
	"title" text NOT NULL,
	"payload" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"score" double precision DEFAULT 0 NOT NULL,
	"why" text,
	"why_now" text,
	"evidence" jsonb DEFAULT '[]'::jsonb NOT NULL,
	"status" text DEFAULT 'new' NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "saved_matches" (
	"id" serial PRIMARY KEY NOT NULL,
	"user_id" integer NOT NULL,
	"match_id" integer NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "saved_user_match" UNIQUE("user_id","match_id")
);
--> statement-breakpoint
CREATE TABLE "scheduled_sessions" (
	"id" serial PRIMARY KEY NOT NULL,
	"user_id" integer NOT NULL,
	"title" text NOT NULL,
	"starts_at" timestamp with time zone NOT NULL,
	"notes" text,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "sessions" (
	"sid" text PRIMARY KEY NOT NULL,
	"sess" jsonb NOT NULL,
	"expire" timestamp with time zone NOT NULL
);
--> statement-breakpoint
CREATE TABLE "submissions" (
	"id" serial PRIMARY KEY NOT NULL,
	"user_id" integer,
	"kind" text NOT NULL,
	"payload" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "swipes" (
	"id" serial PRIMARY KEY NOT NULL,
	"user_id" integer NOT NULL,
	"target_user_id" integer NOT NULL,
	"direction" text NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "swipes_user_target" UNIQUE("user_id","target_user_id")
);
--> statement-breakpoint
CREATE TABLE "users" (
	"id" serial PRIMARY KEY NOT NULL,
	"email" text NOT NULL,
	"password_hash" text,
	"name" text,
	"role" text DEFAULT 'podcaster' NOT NULL,
	"tier" text DEFAULT 'flirt' NOT NULL,
	"goals" text[] DEFAULT '{}'::text[] NOT NULL,
	"public_profile" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"onboarded" boolean DEFAULT false NOT NULL,
	"demo" boolean DEFAULT false NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "users_email_unique" UNIQUE("email")
);
--> statement-breakpoint
CREATE TABLE "venues" (
	"id" serial PRIMARY KEY NOT NULL,
	"user_id" integer,
	"name" text NOT NULL,
	"venue_type" text,
	"location" text,
	"capacity" integer,
	"description" text,
	"categories" text[] DEFAULT '{}'::text[] NOT NULL,
	"vibe_tags" text[] DEFAULT '{}'::text[] NOT NULL,
	"tone_tags" text[] DEFAULT '{}'::text[] NOT NULL,
	"contact_email" text,
	"demo" boolean DEFAULT false NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
ALTER TABLE "advertisers" ADD CONSTRAINT "advertisers_user_id_users_id_fk" FOREIGN KEY ("user_id") REFERENCES "public"."users"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "campaigns" ADD CONSTRAINT "campaigns_advertiser_id_advertisers_id_fk" FOREIGN KEY ("advertiser_id") REFERENCES "public"."advertisers"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "conversations" ADD CONSTRAINT "conversations_user_a_users_id_fk" FOREIGN KEY ("user_a") REFERENCES "public"."users"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "conversations" ADD CONSTRAINT "conversations_user_b_users_id_fk" FOREIGN KEY ("user_b") REFERENCES "public"."users"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "episodes" ADD CONSTRAINT "episodes_podcast_id_podcasts_id_fk" FOREIGN KEY ("podcast_id") REFERENCES "public"."podcasts"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "guests" ADD CONSTRAINT "guests_user_id_users_id_fk" FOREIGN KEY ("user_id") REFERENCES "public"."users"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "hey_bae_messages" ADD CONSTRAINT "hey_bae_messages_user_id_users_id_fk" FOREIGN KEY ("user_id") REFERENCES "public"."users"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "matches" ADD CONSTRAINT "matches_user_id_users_id_fk" FOREIGN KEY ("user_id") REFERENCES "public"."users"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "matches" ADD CONSTRAINT "matches_target_user_id_users_id_fk" FOREIGN KEY ("target_user_id") REFERENCES "public"."users"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "messages" ADD CONSTRAINT "messages_conversation_id_conversations_id_fk" FOREIGN KEY ("conversation_id") REFERENCES "public"."conversations"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "messages" ADD CONSTRAINT "messages_sender_id_users_id_fk" FOREIGN KEY ("sender_id") REFERENCES "public"."users"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "notifications" ADD CONSTRAINT "notifications_user_id_users_id_fk" FOREIGN KEY ("user_id") REFERENCES "public"."users"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "partnership_invites" ADD CONSTRAINT "partnership_invites_created_by_users_id_fk" FOREIGN KEY ("created_by") REFERENCES "public"."users"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "podcasts" ADD CONSTRAINT "podcasts_owner_user_id_users_id_fk" FOREIGN KEY ("owner_user_id") REFERENCES "public"."users"("id") ON DELETE set null ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "predictions" ADD CONSTRAINT "predictions_user_id_users_id_fk" FOREIGN KEY ("user_id") REFERENCES "public"."users"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "saved_matches" ADD CONSTRAINT "saved_matches_user_id_users_id_fk" FOREIGN KEY ("user_id") REFERENCES "public"."users"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "saved_matches" ADD CONSTRAINT "saved_matches_match_id_matches_id_fk" FOREIGN KEY ("match_id") REFERENCES "public"."matches"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "scheduled_sessions" ADD CONSTRAINT "scheduled_sessions_user_id_users_id_fk" FOREIGN KEY ("user_id") REFERENCES "public"."users"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "submissions" ADD CONSTRAINT "submissions_user_id_users_id_fk" FOREIGN KEY ("user_id") REFERENCES "public"."users"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "swipes" ADD CONSTRAINT "swipes_user_id_users_id_fk" FOREIGN KEY ("user_id") REFERENCES "public"."users"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "swipes" ADD CONSTRAINT "swipes_target_user_id_users_id_fk" FOREIGN KEY ("target_user_id") REFERENCES "public"."users"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "venues" ADD CONSTRAINT "venues_user_id_users_id_fk" FOREIGN KEY ("user_id") REFERENCES "public"."users"("id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
CREATE INDEX "messages_conv_idx" ON "messages" USING btree ("conversation_id","created_at");--> statement-breakpoint
CREATE INDEX "podcasts_owner_idx" ON "podcasts" USING btree ("owner_user_id");--> statement-breakpoint
CREATE UNIQUE INDEX "podcasts_source_uidx" ON "podcasts" USING btree ("source","source_id") WHERE "podcasts"."source_id" is not null;--> statement-breakpoint
CREATE UNIQUE INDEX "podcasts_rss_uidx" ON "podcasts" USING btree ("rss_url") WHERE "podcasts"."rss_url" is not null;--> statement-breakpoint
CREATE INDEX "sessions_expire_idx" ON "sessions" USING btree ("expire");