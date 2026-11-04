import type { NextFunction, Request, Response } from 'express';
import { q1 } from '../db/client.js';
import { HttpError } from '../lib.js';

declare module 'express-session' {
  interface SessionData {
    userId?: number;
  }
}

export interface AuthUser {
  id: number;
  email: string;
  name: string | null;
  role: string;
  tier: string;
  onboarded: boolean;
  demo: boolean;
}

declare module 'express-serve-static-core' {
  interface Request {
    user?: AuthUser;
  }
}

export const USER_COLS = 'id, email, name, role, tier, onboarded, demo';

export async function loadUser(req: Request, _res: Response, next: NextFunction) {
  try {
    if (req.session.userId) {
      req.user = await q1<AuthUser>(`SELECT ${USER_COLS} FROM users WHERE id = $1`, [
        req.session.userId,
      ]);
    }
    next();
  } catch (e) {
    next(e);
  }
}

export function requireAuth(req: Request, _res: Response, next: NextFunction) {
  if (!req.user) return next(new HttpError(401, 'Not authenticated'));
  next();
}

export function requireRole(...roles: string[]) {
  return (req: Request, _res: Response, next: NextFunction) => {
    if (!req.user) return next(new HttpError(401, 'Not authenticated'));
    if (!roles.includes(req.user.role)) return next(new HttpError(403, 'Forbidden'));
    next();
  };
}
export const requireAdmin = requireRole('admin');
