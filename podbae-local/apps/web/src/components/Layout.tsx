import { useQuery } from '@tanstack/react-query';
import { Bell, Heart, Mic, Moon, Sun } from 'lucide-react';
import { useState, type ReactNode } from 'react';
import { Link, Redirect, useLocation } from 'wouter';
import { api } from '../lib/api';
import { useMe } from '../lib/auth';
import { Button } from './ui';

export function Logo() {
  return (
    <Link href="/" className="flex items-center gap-1.5 text-lg font-extrabold">
      <span className="relative inline-flex">
        <Heart className="h-7 w-7 fill-primary text-primary" />
        <Mic className="absolute left-1/2 top-1/2 h-3 w-3 -translate-x-1/2 -translate-y-[55%] text-white" />
      </span>
      <span>PodBae</span>
    </Link>
  );
}

export function ThemeToggle() {
  const [dark, setDark] = useState(document.documentElement.classList.contains('dark'));
  return (
    <button aria-label="Toggle dark mode" className="rounded-lg p-2 hover:bg-secondary"
      onClick={() => {
        const next = !dark;
        document.documentElement.classList.toggle('dark', next);
        try { localStorage.setItem('theme', next ? 'dark' : 'light'); } catch { /* ignore */ }
        setDark(next);
      }}>
      {dark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
    </button>
  );
}

export function PublicNav() {
  const { me } = useMe();
  return (
    <header className="sticky top-0 z-40 border-b bg-background/90 backdrop-blur">
      <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-4 py-3">
        <Logo />
        <nav className="hidden items-center gap-6 text-sm font-medium text-muted-foreground md:flex">
          <a href="/#how-it-works" className="hover:text-foreground">How It Works</a>
          <a href="/#features" className="hover:text-foreground">Features</a>
          <a href="/#pricing" className="hover:text-foreground">Pricing</a>
          <Link href="/advertiser-submit" className="font-semibold text-primary">Advertise with Us</Link>
        </nav>
        <div className="flex items-center gap-2">
          {me ? (
            <Link href="/dashboard"><Button size="sm">Dashboard</Button></Link>
          ) : (
            <>
              <Link href="/login"><Button variant="outline" size="sm">Log In</Button></Link>
              <Link href="/get-started"><Button size="sm">Get Started</Button></Link>
            </>
          )}
          <ThemeToggle />
        </div>
      </div>
    </header>
  );
}

export function Footer() {
  return (
    <footer className="border-t bg-card py-10 text-sm text-muted-foreground">
      <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-4 px-4">
        <Logo />
        <div className="flex flex-wrap gap-5">
          <a href="/#how-it-works">How It Works</a><a href="/#pricing">Pricing</a><a href="/#help-center">Help Center</a>
          <Link href="/discover">Discover</Link><Link href="/enterprise">Enterprise</Link>
          <Link href="/partnership-signup">Partnerships</Link><Link href="/advertiser-submit">Advertise</Link>
        </div>
        <span>© {new Date().getFullYear()} PodBae Local · demo build</span>
      </div>
    </footer>
  );
}

export function PublicLayout({ children }: { children: ReactNode }) {
  return (<><PublicNav /><main>{children}</main><Footer /></>);
}

const MEMBER_LINKS = [
  ['/dashboard', 'Dashboard'], ['/swipe', 'Swipe'], ['/messages', 'Messages'], ['/schedule', 'Schedule'],
  ['/analytics', 'Analytics'], ['/partners', 'Partners'], ['/listen', 'Listen'], ['/discover', 'Discover'], ['/profile', 'Profile'],
] as const;

/** Authenticated shell. Redirects to /login when logged out. */
export function AppLayout({ children, admin }: { children: ReactNode; admin?: boolean }) {
  const { me, loading, logout } = useMe();
  const [loc] = useLocation();
  const unread = useQuery({
    queryKey: ['unread'], enabled: !!me, refetchInterval: 5000,
    queryFn: () => api.get<{ count: number }>('/api/chat/unread-count'),
  });
  const notes = useQuery({
    queryKey: ['notifications'], enabled: !!me, refetchInterval: 15000,
    queryFn: () => api.get<{ notifications: { read: boolean }[] }>('/api/notifications'),
  });
  if (loading) return <div className="p-10 text-center text-muted-foreground">Loading…</div>;
  if (!me) return <Redirect to={`/login?next=${encodeURIComponent(loc)}`} />;
  if (admin && me.role !== 'admin') return <div className="p-10 text-center">Admins only.</div>;
  const unreadNotes = notes.data?.notifications.filter((n) => !n.read).length ?? 0;
  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-40 border-b bg-card/95 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-3 px-4 py-3">
          <Logo />
          <nav className="hidden items-center gap-4 text-sm font-medium text-muted-foreground lg:flex">
            {me.role === 'advertiser' && <Link href="/dashboard/campaign-builder" className={loc.startsWith('/dashboard/campaign') ? 'text-primary' : 'hover:text-foreground'}>Campaigns</Link>}
            {MEMBER_LINKS.map(([href, label]) => (
              <Link key={href} href={href} className={loc === href ? 'text-primary' : 'hover:text-foreground'}>
                {label}{href === '/messages' && (unread.data?.count ?? 0) > 0 && (
                  <span className="ml-1 rounded-full bg-primary px-1.5 text-xs text-primary-foreground">{unread.data!.count}</span>)}
              </Link>
            ))}
            {me.role === 'admin' && <Link href="/admin" className="text-purple-600">Admin</Link>}
          </nav>
          <div className="flex items-center gap-2 text-sm">
            <Link href="/dashboard" className="relative p-2" aria-label="Notifications">
              <Bell className="h-4 w-4" />
              {unreadNotes > 0 && <span className="absolute right-0 top-0 h-2 w-2 rounded-full bg-primary" />}
            </Link>
            <span className="hidden text-muted-foreground sm:inline">{me.name ?? me.email} · <b className="capitalize">{me.tier}</b></span>
            <Button variant="outline" size="sm" onClick={logout}>Log out</Button>
            <ThemeToggle />
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-4 py-8">{children}</main>
    </div>
  );
}
