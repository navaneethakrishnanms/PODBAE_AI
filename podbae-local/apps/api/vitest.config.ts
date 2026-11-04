import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    testTimeout: 60_000,
    hookTimeout: 120_000,
    fileParallelism: false,
    env: {
      NODE_ENV: 'test',
      PGLITE_DIR: 'memory://', // temporary in-memory PGlite DB
      DEMO_AUTO_LIKE: 'true',
      AI_SERVICE_URL: 'http://127.0.0.1:9', // dead port -> exercises the in-process scoring fallback
      SESSION_SECRET: 'test-secret',
    },
  },
});
