import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { Link } from 'wouter';
import { AppLayout, PublicLayout } from '../components/Layout';
import { Badge, Button, Card, Empty, Field, Input, Spinner, Textarea, toast } from '../components/ui';
import { api } from '../lib/api';

// ---------- /schedule : sessions stored in the DB ----------
export function Schedule() {
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({ queryKey: ['schedule'], queryFn: () => api.get('/api/schedule') });
  const [f, setF] = useState({ title: '', startsAt: '', notes: '' });
  const add = useMutation({
    mutationFn: () => api.post('/api/schedule', { ...f, startsAt: new Date(f.startsAt).toISOString() }),
    onSuccess: () => { setF({ title: '', startsAt: '', notes: '' }); qc.invalidateQueries({ queryKey: ['schedule'] }); toast('Session added'); },
    onError: (e: Error) => toast(e.message),
  });
  const del = useMutation({
    mutationFn: (id: number) => api.delete(`/api/schedule/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['schedule'] }),
  });
  const sessions: any[] = data?.sessions ?? [];
  return (
    <AppLayout>
      <h1 className="mb-1 text-3xl font-bold">Schedule</h1>
      <p className="mb-6 text-sm text-muted-foreground">Add recordings, swaps and events. (Calendar integrations come later.)</p>
      <Card className="mb-6 grid gap-3 sm:grid-cols-[1fr_auto]">
        <Field label="Title"><Input value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} placeholder="Guest recording with…" /></Field>
        <Field label="When"><Input type="datetime-local" value={f.startsAt} onChange={(e) => setF({ ...f, startsAt: e.target.value })} /></Field>
        <div className="sm:col-span-2"><Field label="Notes"><Textarea rows={2} value={f.notes} onChange={(e) => setF({ ...f, notes: e.target.value })} /></Field></div>
        <div className="sm:col-span-2"><Button disabled={!f.title || !f.startsAt || add.isPending} onClick={() => add.mutate()}>Add session</Button></div>
      </Card>
      {isLoading ? <Spinner /> : !sessions.length ? <Empty>No sessions scheduled.</Empty> : (
        <div className="space-y-2">{sessions.map((s) => (
          <Card key={s.id} className="flex items-center justify-between py-3">
            <span><b>{s.title}</b> · {new Date(s.startsAt).toLocaleString()}{s.notes && <span className="block text-xs text-muted-foreground">{s.notes}</span>}</span>
            <button className="text-xs text-muted-foreground hover:text-destructive" onClick={() => del.mutate(s.id)}>Remove</button>
          </Card>
        ))}</div>
      )}
    </AppLayout>
  );
}

// ---------- /analytics ----------
export function Analytics() {
  const ins = useQuery({ queryKey: ['insights'], queryFn: () => api.get('/api/member/insights') });
  const eps = useQuery({ queryKey: ['my-eps'], queryFn: () => api.get('/api/member/podcast-episodes') });
  return (
    <AppLayout>
      <h1 className="mb-4 text-3xl font-bold">Analytics</h1>
      {ins.isLoading ? <Spinner /> : (
        <div className="grid gap-4 md:grid-cols-3">
          <Card><div className="text-3xl font-bold text-primary">{(ins.data?.byType ?? []).reduce((a: number, t: any) => a + t.n, 0)}</div><div className="text-sm text-muted-foreground">Total matches</div></Card>
          <Card><div className="text-3xl font-bold text-primary">{ins.data?.savedCount}</div><div className="text-sm text-muted-foreground">Saved</div></Card>
          <Card><div className="text-3xl font-bold text-primary">{ins.data?.mutualCount}</div><div className="text-sm text-muted-foreground">Mutual matches</div></Card>
          <Card className="md:col-span-3"><h3 className="mb-2 font-semibold">Your episodes ({eps.data?.episodes?.length ?? 0})</h3>
            {(eps.data?.episodes ?? []).slice(0, 8).map((e: any) => <div key={e.id} className="text-sm">{e.title} <span className="text-muted-foreground">· {e.publishedAt ? new Date(e.publishedAt).toLocaleDateString() : ''}</span></div>)}</Card>
        </div>
      )}
    </AppLayout>
  );
}

// ---------- /partners ----------
export function Partners() {
  const { data, isLoading } = useQuery({ queryKey: ['sponsors'], queryFn: () => api.get('/api/sponsors') });
  return (
    <AppLayout>
      <h1 className="mb-4 text-3xl font-bold">Partners & sponsors</h1>
      {isLoading ? <Spinner /> : (
        <div className="grid gap-4 md:grid-cols-2">
          {(data?.sponsors ?? []).map((s: any) => (
            <Card key={s.id}><div className="flex flex-wrap items-center gap-2"><b>{s.orgName}</b><Badge>{s.orgType}</Badge>{s.demo && <Badge tone="gray">demo</Badge>}</div>
              <p className="text-sm text-muted-foreground">{s.location} · {s.activeCampaigns} active campaign(s)</p>
              <div className="mt-2 flex flex-wrap gap-1">{(s.categories ?? []).map((c: string) => <Badge key={c} tone="pink">{c}</Badge>)}</div></Card>
          ))}
        </div>
      )}
    </AppLayout>
  );
}

// ---------- /listen & /listener-recommendations ----------
export function Listen() {
  const { data, isLoading } = useQuery({ queryKey: ['listen'], queryFn: () => api.get('/api/listener-recommendations') });
  return (
    <PublicLayout>
      <div className="mx-auto max-w-6xl px-4 py-12">
        <h1 className="mb-6 text-4xl font-bold">Listener recommendations</h1>
        {isLoading ? <Spinner /> : (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {(data?.recommendations ?? []).map((p: any) => (
              <Card key={p.id}><div className="flex items-center gap-2"><b>{p.name}</b>{p.verified && <Badge tone="green">verified</Badge>}{p.demo && <Badge tone="gray">demo</Badge>}</div>
                <p className="mt-1 line-clamp-2 text-sm text-muted-foreground">{p.description}</p>
                {p.latestEpisode && <p className="mt-2 text-xs">Latest: {p.latestEpisode}</p>}</Card>
            ))}
          </div>
        )}
      </div>
    </PublicLayout>
  );
}

// ---------- /enterprise ----------
export function Enterprise() {
  return (
    <PublicLayout>
      <div className="gradient-bg px-4 py-20 text-center">
        <h1 className="text-4xl font-bold">PodBae for Enterprise</h1>
        <p className="mx-auto mt-3 max-w-xl text-muted-foreground">Networks, agencies and brands managing many shows: custom matching, integrations and reporting.</p>
        <Link href="/partnership-signup"><Button size="lg" className="mt-6">Talk to us</Button></Link>
      </div>
    </PublicLayout>
  );
}

// ---------- /partnership-signup ----------
export function PartnershipSignup() {
  const [f, setF] = useState({ email: '', orgName: '', message: '' });
  const [done, setDone] = useState(false);
  return (
    <PublicLayout>
      <div className="gradient-bg px-4 py-16">
        <div className="mx-auto max-w-lg">
          <h1 className="mb-6 text-3xl font-bold">Partnership signup</h1>
          {done ? <Card>Thanks! We'll be in touch.</Card> : (
            <Card className="space-y-4">
              <Field label="Email"><Input type="email" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} /></Field>
              <Field label="Organization"><Input value={f.orgName} onChange={(e) => setF({ ...f, orgName: e.target.value })} /></Field>
              <Field label="Message"><Textarea value={f.message} onChange={(e) => setF({ ...f, message: e.target.value })} /></Field>
              <Button disabled={!f.email} onClick={async () => { try { await api.post('/api/partnership-invite', f); setDone(true); } catch (e: any) { toast(e.message); } }}>Send</Button>
            </Card>
          )}
        </div>
      </div>
    </PublicLayout>
  );
}
