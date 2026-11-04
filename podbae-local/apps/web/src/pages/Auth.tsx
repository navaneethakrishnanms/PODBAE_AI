import { useState } from 'react';
import { Link, useLocation } from 'wouter';
import { PublicLayout } from '../components/Layout';
import { Button, Card, Field, Input, toast } from '../components/ui';
import { api } from '../lib/api';
import { useMe } from '../lib/auth';

const ROLE_HOME: Record<string, string> = {
  podcaster: '/submit', advertiser: '/advertiser-submit', venue: '/venue-submit', guest: '/guest-submit',
};

export function Login() {
  const [, nav] = useLocation();
  const { refresh } = useMe();
  const [mode, setMode] = useState<'login' | 'register' | 'forgot'>('login');
  const [f, setF] = useState({ email: '', password: '', name: '', role: 'podcaster' });
  const [busy, setBusy] = useState(false);
  const next = new URLSearchParams(window.location.search).get('next');
  const set = (k: string) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      if (mode === 'forgot') {
        await api.post('/api/forgot-password', { email: f.email });
        toast('If that account exists, a reset link was logged by the API.');
        setMode('login');
      } else if (mode === 'register') {
        if (f.role === 'advertiser') return nav('/advertiser-submit');
        await api.post('/api/auth/register', f);
        await refresh();
        nav(ROLE_HOME[f.role] ?? '/onboarding');
      } else {
        const { user } = await api.post('/api/auth/login', { email: f.email, password: f.password });
        await refresh();
        nav(next ?? (user.onboarded ? (user.role === 'admin' ? '/admin' : '/dashboard') : ROLE_HOME[user.role] ?? '/dashboard'));
      }
    } catch (err: any) {
      toast(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <PublicLayout>
      <div className="mx-auto max-w-md px-4 py-16">
        <Card>
          <h1 className="mb-4 text-2xl font-extrabold">{mode === 'login' ? 'Welcome back' : mode === 'register' ? 'Create your account' : 'Reset password'}</h1>
          <form onSubmit={submit} className="space-y-4">
            {mode === 'register' && (
              <>
                <Field label="Name"><Input value={f.name} onChange={set('name')} required /></Field>
                <Field label="I am a…">
                  <select className="w-full rounded-lg border border-input bg-card px-3 py-2 text-sm" value={f.role} onChange={set('role')}>
                    <option value="podcaster">Podcaster</option><option value="advertiser">Advertiser / Sponsor</option>
                    <option value="venue">Venue</option><option value="guest">Guest</option>
                  </select>
                </Field>
              </>
            )}
            <Field label="Email"><Input type="email" value={f.email} onChange={set('email')} required /></Field>
            {mode !== 'forgot' && <Field label="Password" hint={mode === 'register' ? '(min 8 chars)' : ''}><Input type="password" value={f.password} onChange={set('password')} required minLength={mode === 'register' ? 8 : 1} /></Field>}
            <Button className="w-full" disabled={busy}>{mode === 'login' ? 'Log in' : mode === 'register' ? 'Sign up' : 'Send reset link'}</Button>
          </form>
          <div className="mt-4 flex justify-between text-sm text-muted-foreground">
            {mode === 'login' ? (
              <><button onClick={() => setMode('register')}>Create account</button><button onClick={() => setMode('forgot')}>Forgot password?</button></>
            ) : (<button onClick={() => setMode('login')}>Back to login</button>)}
          </div>
          <p className="mt-4 rounded-lg bg-secondary p-3 text-xs text-muted-foreground">Demo: podcaster@podbae.local / demo123 · brand@podbae.local / demo123 · admin@podbae.local / admin123</p>
          <Link href="/admin/setup" className="mt-2 block text-xs text-muted-foreground">Admin setup</Link>
        </Card>
      </div>
    </PublicLayout>
  );
}
