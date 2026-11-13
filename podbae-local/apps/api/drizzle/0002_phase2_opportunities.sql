CREATE TABLE "opportunity_cache" (
	"id" serial PRIMARY KEY NOT NULL,
	"user_id" integer NOT NULL,
	"member_show_id" text,
	"payload" jsonb NOT NULL,
	"cached_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "opportunity_cache_user_id_unique" UNIQUE("user_id")
);
--> statement-breakpoint
ALTER TABLE "partnership_invites" ALTER COLUMN "email" DROP NOT NULL;--> statement-breakpoint
ALTER TABLE "partnership_invites" ADD COLUMN "kind" text DEFAULT 'signup' NOT NULL;--> statement-breakpoint
ALTER TABLE "partnership_invites" ADD COLUMN "target_show_id" text;--> statement-breakpoint
ALTER TABLE "partnership_invites" ADD COLUMN "opportunity_id" text;--> statement-breakpoint
ALTER TABLE "opportunity_cache" ADD CONSTRAINT "opportunity_cache_user_id_users_id_fk" FOREIGN KEY ("user_id") REFERENCES "public"."users"("id") ON DELETE cascade ON UPDATE no action;