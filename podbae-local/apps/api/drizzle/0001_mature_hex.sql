CREATE TABLE "intel_links" (
	"id" serial PRIMARY KEY NOT NULL,
	"podcast_id" integer NOT NULL,
	"intel_show_id" text,
	"rss_url" text,
	"last_job_id" text,
	"profile" jsonb,
	"profile_cached_at" timestamp with time zone,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "intel_links_podcast_id_unique" UNIQUE("podcast_id")
);
--> statement-breakpoint
ALTER TABLE "intel_links" ADD CONSTRAINT "intel_links_podcast_id_podcasts_id_fk" FOREIGN KEY ("podcast_id") REFERENCES "public"."podcasts"("id") ON DELETE cascade ON UPDATE no action;