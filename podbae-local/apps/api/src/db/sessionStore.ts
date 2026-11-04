import session from 'express-session';
import { q, q1 } from './client.js';

/** express-session store backed by the `sessions` table (same PGlite DB). */
export class PgliteStore extends session.Store {
  private expiry(sess: session.SessionData) {
    const exp = sess.cookie?.expires;
    return exp ? new Date(exp) : new Date(Date.now() + 14 * 86400_000);
  }

  get(sid: string, cb: (err?: unknown, s?: session.SessionData | null) => void) {
    q1<{ sess: session.SessionData }>('SELECT sess FROM sessions WHERE sid = $1 AND expire > now()', [sid])
      .then((r) => cb(null, r?.sess ?? null), cb);
  }
  set(sid: string, sess: session.SessionData, cb?: (err?: unknown) => void) {
    q(`INSERT INTO sessions (sid, sess, expire) VALUES ($1, $2, $3)
       ON CONFLICT (sid) DO UPDATE SET sess = EXCLUDED.sess, expire = EXCLUDED.expire`,
      [sid, JSON.stringify(sess), this.expiry(sess).toISOString()]).then(() => cb?.(), (e) => cb?.(e));
  }
  touch(sid: string, sess: session.SessionData, cb?: (err?: unknown) => void) {
    q('UPDATE sessions SET expire = $2 WHERE sid = $1', [sid, this.expiry(sess).toISOString()])
      .then(() => cb?.(), (e) => cb?.(e));
  }
  destroy(sid: string, cb?: (err?: unknown) => void) {
    q('DELETE FROM sessions WHERE sid = $1', [sid]).then(() => cb?.(), (e) => cb?.(e));
  }
}
