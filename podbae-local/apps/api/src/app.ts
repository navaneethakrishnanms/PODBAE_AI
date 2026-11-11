import cors from 'cors';
import express from 'express';
import session from 'express-session';
import { config } from './config.js';
import { PgliteStore } from './db/sessionStore.js';
import { camelize, errorHandler } from './lib.js';
import { loadUser } from './middleware/auth.js';
import { adminRouter } from './routes/admin.js';
import { authRouter } from './routes/auth.js';
import { intakeRouter } from './routes/intake.js';
import { intelRouter } from './routes/intel.js';
import { memberRouter } from './routes/member.js';
import { podcastsRouter, publicRouter } from './routes/podcasts.js';
import { socialRouter } from './routes/social.js';

export function createApp() {
  const app = express();

  app.use(cors({ origin: config.webOrigin, credentials: true }));
  app.use(express.json({ limit: '1mb' }));
  app.use(
    session({
      store: new PgliteStore(),
      secret: config.sessionSecret,
      resave: false,
      saveUninitialized: false,
      cookie: { httpOnly: true, sameSite: 'lax', maxAge: 1000 * 60 * 60 * 24 * 14 },
    }),
  );

  // DB rows are snake_case; the contract is camelCase.
  app.use((_req, res, next) => {
    const json = res.json.bind(res);
    res.json = (body: unknown) => json(camelize(body));
    next();
  });
  app.use(loadUser);

  app.get('/api/health', (_req, res) => res.json({ ok: true }));
  app.use(authRouter); // includes public /api/admin/setup-* — must precede adminRouter
  app.use(intakeRouter);
  app.use(intelRouter); // before adminRouter: /api/admin/intel/* are admin-guarded inside
  app.use(podcastsRouter);
  app.use(publicRouter);
  app.use(memberRouter);
  app.use(socialRouter);
  app.use(adminRouter);

  app.use('/api', (_req, res) => res.status(404).json({ error: 'Not found' }));
  app.use(errorHandler);
  return app;
}
