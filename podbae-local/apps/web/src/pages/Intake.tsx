import { CATEGORIES, COLLAB_TYPES, TONE_TAGS, VIBE_TAGS } from '@podbae/contracts';
import { useQuery } from '@tanstack/react-query';
import { CheckCircle2, MapPin, Megaphone, Mic, UserRound } from 'lucide-react';
import { useState } from 'react';
import { Link, useLocation } from 'wouter';
import { AppLayout, PublicLayout } from '../components/Layout';
import { Button, Card, ChipSelect, Field, Input, Textarea, toast } from '../components/ui';
import { api } from '../lib/api';
import { useMe } from '../lib/auth';
import { JobProgress } from './Intelligence';

export function GetStarted() {
  const roles = [
    [Mic, 'Podcaster', 'Find partners, sponsors, guests and venues.', '/submit'],
    [Megaphone, 'Advertiser', 'Reach engaged indie audiences.', '/advertiser-submit'],
    [MapPin, 'Venue', 'Host live recordings and events.', '/venue-submit'],
    [UserRound, 'Guest', 'Get booked on shows that fit you.', '/guest-submit'],
  ] as const;
  return (
    <PublicLayout>
      <div className="gradient-bg min-h-[70vh] px-4 py-16">
        <div className="mx-auto max-w-4xl">
          <h1 className="text-center text-4xl font-bold">How will you use PodBae?</h1>
          <p className="mt-2 text-center text-muted-foreground">Choose your role to get started.</p>
          <div className="mt-10 grid gap-5 sm:grid-cols-2">
            {roles.map(([Icon, t, d, href]) => (
              <Link key={t} href={href}>
                <Card className="cursor-pointer transition hover:border-primary">
                  <Icon className="mb-2 h-7 w-7 text-primary" /><h3 className="text-lg font-bold">{t}</h3><p className="text-sm text-muted-foreground">{d}</p>
                </Card>
              </Link>
            ))}
          </div>
        </div>
      </div>
    </PublicLayout>
  );
}

type Account = { name: string; email: string; password: string };

function IntakeShell({ title, subtitle, children }: { title: string; subtitle?: string; children: React.ReactNode }) {
  return (
    <PublicLayout>
      <div className="gradient-bg px-4 py-12">
        <div className="mx-auto max-w-2xl">
          <h1 className="text-3xl font-bold">{title}</h1>
          {subtitle && <p className="mb-6 mt-1 text-muted-foreground">{subtitle}</p>}
          <Card className="mt-6">{children}</Card>
        </div>
      </div>
    </PublicLayout>
  );
}

/** Shown only when logged out — submitting the form creates the account. */
function AccountFields({ value, onChange }: { value: Account; onChange: (a: Account) => void }) {
  const { me } = useMe();
  if (me) return <p className="rounded-lg bg-secondary p-3 text-sm text-muted-foreground">Signed in as {me.email}.</p>;
  return (
    <div className="space-y-4 rounded-lg border bg-secondary/40 p-4">
      <h3 className="text-sm font-semibold">Create your account</h3>
      <Field label="Your name"><Input value={value.name} onChange={(e) => onChange({ ...value, name: e.target.value })} required /></Field>
      <Field label="Email"><Input type="email" value={value.email} onChange={(e) => onChange({ ...value, email: e.target.value })} required /></Field>
      <Field label="Password" hint="(min 8 chars)"><Input type="password" minLength={8} value={value.password} onChange={(e) => onChange({ ...value, password: e.target.value })} required /></Field>
      <p className="text-xs text-muted-foreground">Already have an account? <Link href="/login?next=/submit" className="text-primary">Log in</Link></p>
    </div>
  );
}

function useSubmit(path: string) {
  const [, nav] = useLocation();
  const { me, refresh } = useMe();
  const [busy, setBusy] = useState(false);
  const submit = async (body: Record<string, unknown>, account: Account) => {
    setBusy(true);
    try {
      await api.post(path, { ...body, ...(me ? {} : { account }) });
      await refresh();
      nav('/success');
    } catch (err: any) {
      toast(err.message);
    } finally {
      setBusy(false);
    }
  };
  return { busy, submit };
}

const EMPTY_ACCOUNT: Account = { name: '', email: '', password: '' };

export function PodcasterSubmit() {
  const { busy, submit } = useSubmit('/api/submissions');
  const [acct, setAcct] = useState(EMPTY_ACCOUNT);
  const [f, setF] = useState({ showName: '', rssUrl: '', categories: [] as string[], vibeTags: [] as string[], toneTags: [] as string[],
    collaborationTypes: [] as string[], audienceNotes: '', location: '', goals: '' });
  return (
    <IntakeShell title="Tell us about your show" subtitle="We'll use this to find your best matches. Free to submit.">
      <form onSubmit={(e) => { e.preventDefault(); if (!f.categories.length) return toast('Pick at least one category'); submit(f, acct); }} className="space-y-5">
        <Field label="Show name"><Input value={f.showName} onChange={(e) => setF({ ...f, showName: e.target.value })} required /></Field>
        <Field label="RSS URL" hint="(optional)"><Input type="url" value={f.rssUrl} onChange={(e) => setF({ ...f, rssUrl: e.target.value })} placeholder="https://…" /></Field>
        <Field label="Category"><ChipSelect options={CATEGORIES} value={f.categories} onChange={(categories) => setF({ ...f, categories })} /></Field>
        <Field label="Vibe tags"><ChipSelect options={VIBE_TAGS} value={f.vibeTags} onChange={(vibeTags) => setF({ ...f, vibeTags })} /></Field>
        <Field label="Tone tags"><ChipSelect options={TONE_TAGS} value={f.toneTags} onChange={(toneTags) => setF({ ...f, toneTags })} /></Field>
        <Field label="Collaboration type"><ChipSelect options={COLLAB_TYPES} value={f.collaborationTypes} onChange={(collaborationTypes) => setF({ ...f, collaborationTypes })} /></Field>
        <Field label="Location" hint="(City, ST)"><Input value={f.location} onChange={(e) => setF({ ...f, location: e.target.value })} placeholder="New York, NY" /></Field>
        <Field label="Audience notes"><Textarea value={f.audienceNotes} onChange={(e) => setF({ ...f, audienceNotes: e.target.value })} /></Field>
        <Field label="Goals"><Textarea value={f.goals} onChange={(e) => setF({ ...f, goals: e.target.value })} /></Field>
        <AccountFields value={acct} onChange={setAcct} />
        <Button className="w-full" size="lg" disabled={busy}>{busy ? 'Finding matches…' : 'Find my matches'}</Button>
      </form>
    </IntakeShell>
  );
}

export function VenueSubmit() {
  const { busy, submit } = useSubmit('/api/venue-submissions');
  const [acct, setAcct] = useState(EMPTY_ACCOUNT);
  const [f, setF] = useState({ name: '', venueType: '', location: '', capacity: '', description: '', categories: [] as string[], vibeTags: [] as string[] });
  return (
    <IntakeShell title="List your venue" subtitle="Get matched with podcasters looking for live-recording spaces.">
      <form onSubmit={(e) => { e.preventDefault(); submit({ ...f, capacity: f.capacity ? Number(f.capacity) : undefined }, acct); }} className="space-y-5">
        <Field label="Venue name"><Input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} required /></Field>
        <Field label="Venue type"><Input value={f.venueType} onChange={(e) => setF({ ...f, venueType: e.target.value })} placeholder="Studio, theater, cafe…" /></Field>
        <Field label="Location"><Input value={f.location} onChange={(e) => setF({ ...f, location: e.target.value })} placeholder="Atlanta, GA" /></Field>
        <Field label="Capacity"><Input type="number" value={f.capacity} onChange={(e) => setF({ ...f, capacity: e.target.value })} /></Field>
        <Field label="Categories"><ChipSelect options={CATEGORIES} value={f.categories} onChange={(categories) => setF({ ...f, categories })} /></Field>
        <Field label="Vibe"><ChipSelect options={VIBE_TAGS} value={f.vibeTags} onChange={(vibeTags) => setF({ ...f, vibeTags })} /></Field>
        <Field label="Description"><Textarea value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} /></Field>
        <AccountFields value={acct} onChange={setAcct} />
        <Button className="w-full" size="lg" disabled={busy}>Submit venue</Button>
      </form>
    </IntakeShell>
  );
}

export function GuestSubmit() {
  const { busy, submit } = useSubmit('/api/guest-submissions');
  const [acct, setAcct] = useState(EMPTY_ACCOUNT);
  const [f, setF] = useState({ name: '', expertise: '', bio: '', topics: '', location: '', categories: [] as string[], vibeTags: [] as string[] });
  return (
    <IntakeShell title="Become a guest" subtitle="Get booked on shows that fit your expertise.">
      <form onSubmit={(e) => { e.preventDefault(); submit({ ...f, topics: f.topics.split(',').map((s) => s.trim()).filter(Boolean) }, acct); }} className="space-y-5">
        <Field label="Display name"><Input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} required /></Field>
        <Field label="Expertise"><Input value={f.expertise} onChange={(e) => setF({ ...f, expertise: e.target.value })} /></Field>
        <Field label="Topics" hint="(comma separated)"><Input value={f.topics} onChange={(e) => setF({ ...f, topics: e.target.value })} /></Field>
        <Field label="Location"><Input value={f.location} onChange={(e) => setF({ ...f, location: e.target.value })} /></Field>
        <Field label="Categories"><ChipSelect options={CATEGORIES} value={f.categories} onChange={(categories) => setF({ ...f, categories })} /></Field>
        <Field label="Vibe"><ChipSelect options={VIBE_TAGS} value={f.vibeTags} onChange={(vibeTags) => setF({ ...f, vibeTags })} /></Field>
        <Field label="Bio"><Textarea value={f.bio} onChange={(e) => setF({ ...f, bio: e.target.value })} /></Field>
        <AccountFields value={acct} onChange={setAcct} />
        <Button className="w-full" size="lg" disabled={busy}>Submit</Button>
      </form>
    </IntakeShell>
  );
}

export function Onboarding() {
  const { me } = useMe();
  const home: Record<string, string> = { podcaster: '/submit', advertiser: '/advertiser-submit', venue: '/venue-submit', guest: '/guest-submit' };
  return (
    <AppLayout>
      <div className="mx-auto max-w-lg text-center">
        <h1 className="text-3xl font-bold">Welcome{me?.name ? `, ${me.name}` : ''} 💕</h1>
        <p className="mt-2 text-muted-foreground">Let's set up your profile so we can start matching.</p>
        <Link href={home[me?.role ?? 'podcaster'] ?? '/dashboard'}><Button size="lg" className="mt-6">Continue</Button></Link>
      </div>
    </AppLayout>
  );
}

/** Live progress of the RSS ingestion job started by the intake (only shown when an RSS feed was submitted). */
function IntelProgress() {
  const { data } = useQuery({
    queryKey: ['intel-status'], retry: false, queryFn: () => api.get('/api/intel/my/status'),
    refetchInterval: (q) => { const j = q.state.data?.job; return j && ['queued', 'running'].includes(j.status) ? 1500 : false; },
  });
  if (!data?.job) return null;
  return (
    <div className="mt-6 text-left">
      <JobProgress job={data.job} />
      {data.job.status === 'succeeded' && <Link href="/intelligence" className="mt-2 inline-block text-sm font-medium text-primary">See your Podcast Intelligence profile →</Link>}
    </div>
  );
}

export function Success() {
  const { me } = useMe();
  const next = me?.role === 'advertiser' ? '/dashboard/campaign-builder' : '/dashboard';
  return (
    <AppLayout>
      <div className="mx-auto max-w-lg text-center">
        <CheckCircle2 className="mx-auto h-14 w-14 text-primary" />
        <h1 className="mt-3 text-3xl font-bold">You're in! 🎉</h1>
        <p className="mt-2 text-muted-foreground">Your submission is saved{me?.role === 'podcaster' ? ' and your matches are ready' : ''}.</p>
        {me?.role === 'podcaster' && <IntelProgress />}
        <Link href={next}><Button size="lg" className="mt-6">Go to dashboard</Button></Link>
      </div>
    </AppLayout>
  );
}
