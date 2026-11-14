ALTER TABLE "opportunity_cache" DROP CONSTRAINT "opportunity_cache_user_id_unique";--> statement-breakpoint
ALTER TABLE "opportunity_cache" ADD COLUMN "kind" text DEFAULT 'partner' NOT NULL;--> statement-breakpoint
ALTER TABLE "opportunity_cache" ADD CONSTRAINT "opportunity_cache_user_kind" UNIQUE("user_id","kind");