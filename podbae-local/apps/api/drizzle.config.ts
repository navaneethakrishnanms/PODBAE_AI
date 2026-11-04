import { defineConfig } from 'drizzle-kit';

// Drizzle schema (src/db/schema.ts) is the single source of truth. Migrations: `npm run db:generate`.
export default defineConfig({
  schema: './src/db/schema.ts',
  out: './drizzle',
  dialect: 'postgresql',
});
