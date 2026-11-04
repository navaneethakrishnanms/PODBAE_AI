import { PGlite } from '@electric-sql/pglite';
import { vector } from '@electric-sql/pglite/vector';
import { drizzle } from 'drizzle-orm/pglite';
import { migrate } from 'drizzle-orm/pglite/migrator';
import fs from 'node:fs';
import { config } from '../config.js';
import * as schema from './schema.js';

if (!config.pgliteDir.startsWith('memory://')) fs.mkdirSync(config.pgliteDir, { recursive: true });

/** Embedded Postgres (PGlite), persisted to ./data/pglite. pgvector is loaded (unused for now). */
export const client = new PGlite(config.pgliteDir, { extensions: { vector } });
export const db = drizzle(client, { schema });

/** Enable extensions + apply drizzle-kit migrations. Idempotent. */
export async function initDb() {
  await client.exec('CREATE EXTENSION IF NOT EXISTS vector');
  await migrate(db, { migrationsFolder: config.migrationsDir });
}

/** Raw SQL helpers ($1-style params) over the same PGlite instance. */
export async function q<T = any>(text: string, params: unknown[] = []): Promise<T[]> {
  const r = await client.query<T>(text, params as any[]);
  return r.rows;
}
export async function q1<T = any>(text: string, params: unknown[] = []): Promise<T | undefined> {
  return (await q<T>(text, params))[0];
}
