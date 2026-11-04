import { createApp } from './app.js';
import { config } from './config.js';
import { initDb } from './db/client.js';

await initDb(); // idempotent: applies pending migrations
createApp().listen(config.port, () => {
  console.log(`[api] http://localhost:${config.port}  (ai: ${config.aiServiceUrl}, db: ${config.pgliteDir})`);
});
