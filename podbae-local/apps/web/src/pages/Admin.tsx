import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { useLocation } from 'wouter';
import { AppLayout, PublicLayout } from '../components/Layout';
import { Badge, Button, Card, Field, Input, Spinner, Tabs, toast } from '../components/ui';
import { api } from '../lib/api';
import { useMe } from '../lib/auth';

export function AdminSetup() {
  const [, nav] = useLocation();
  const { refresh } = useMe();
  const needed = useQuery({ queryKey: ['setup-needed'], queryFn: () => api.get('/api/admin/setup-needed') });
  const [f, setF] = useState({ email: '', password: '', name: '' });
  return (
    <PublicLayout>
      <div className="mx-auto max-w-md px-4 py-16">
        <h1 className="mb-6 text-3xl font-extrabold">Admin setup</h1>
        {needed.isLoading ? <Spinner /> : !needed.data?.needed ? <Card>An admin already exists. Log in instead.</Card> : (
          <Card className="space-y-4">
            <Field label="Name"><Input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
            <Field label="Email"><Input type="email" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} /></Field>
            <Field label="Password" hint="(min 8)"><Input type="password" value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} /></Field>
            <Button onClick={async () => { try { await api.post('/api/admin/setup-first-admin', f); await refresh(); nav('/admin'); } catch (e: any) { toast(e.message); } }}>Create admin</Button>
          </Card>
        )}
      </div>
    </PublicLayout>
  );
}

export default function Admin() {
  const qc = useQueryClient();
  const [tab, setTab] = useState('podcasts');
  const [q, setQ] = useState('');
  const podcasts = useQuery({ queryKey: ['a-pods'], queryFn: () => api.get('/api/admin/podcasts') });
  const users = useQuery({ queryKey: ['a-users'], enabled: tab === 'users', queryFn: () => api.get('/api/admin/users') });
  const status = useQuery({ queryKey: ['a-status'], queryFn: () => api.get('/api/admin/directory-status') });
  const metrics = useQuery({ queryKey: ['a-metrics'], enabled: tab === 'metrics', queryFn: () => api.get('/api/admin/vibe-logic-metrics') });
  const recs = useQuery({ queryKey: ['a-recs'], enabled: tab === 'metrics', queryFn: () => api.get('/api/admin/vibe-logic-recommendations') });
  const invites = useQuery({ queryKey: ['a-inv'], enabled: tab === 'invites', queryFn: () => api.get('/api/admin/partnership-invites') });
  const jobs = useQuery({ queryKey: ['a-jobs'], enabled: tab === 'ingestion', queryFn: () => api.get('/api/admin/ingestion-jobs') });
  const [hits, setHits] = useState<any[]>([]);
  useEffect(() => { if (tab === 'showcase') api.get(`/api/admin/showcase/directory-search?q=${encodeURIComponent(q)}`).then((r) => setHits(r.podcasts)); }, [tab, q]);

  const refresh = () => qc.invalidateQueries({ predicate: (x) => String(x.queryKey[0]).startsWith('a-') });
  const run = (label: string, fn: () => Promise<any>) => async () => { try { const r = await fn(); toast(`${label}: ${JSON.stringify(r).slice(0, 80)}`); refresh(); } catch (e: any) { toast(e.message); } };

  return (
    <AppLayout admin>
      <h1 className="mb-4 text-3xl font-extrabold">Admin</h1>
      <div className="mb-6 flex flex-wrap gap-4">
        {[['Podcasts', status.data?.total], ['Verified', status.data?.verified], ['Demo', status.data?.demo], ['Featured', status.data?.featured], ['Enriched', status.data?.enriched]].map(([l, v]) => (
          <Card key={l as string} className="px-5 py-3"><div className="text-2xl font-extrabold text-primary">{v ?? '–'}</div><div className="text-xs text-muted-foreground">{l}</div></Card>
        ))}
      </div>
      <div className="mb-6 flex flex-wrap gap-2">
        <Button size="sm" onClick={run('Generate opportunities', () => api.post('/api/admin/generate-opportunities'))}>Generate opportunities</Button>
        <Button size="sm" variant="outline" onClick={run('Enhanced matching', () => api.post('/api/run-enhanced-matching'))}>Run enhanced matching (me)</Button>
        <Button size="sm" variant="outline" onClick={run('Seed test podcasts', () => api.post('/api/admin/seed-test-podcasts'))}>Seed test podcasts</Button>
      </div>
      <Tabs value={tab} onChange={setTab} tabs={[
        { id: 'podcasts', label: 'Podcasts' }, { id: 'users', label: 'Users' }, { id: 'metrics', label: 'Vibe-logic metrics' },
        { id: 'showcase', label: 'Showcase' }, { id: 'invites', label: 'Partnership invites' },
      ]} />
      <div className="pt-6">
        {tab === 'podcasts' && (
          <div className="space-y-2">{(podcasts.data?.podcasts ?? []).map((p: any) => (
            <Card key={p.id} className="flex items-center justify-between py-3">
              <span><b>{p.name}</b> <span className="text-xs text-muted-foreground">#{p.id} · {p.source}</span> {p.demo && <Badge tone="gray">demo</Badge>}</span>
              <Button size="sm" variant={p.verified ? 'outline' : 'default'} onClick={run('Verify', () => api.post(`/api/admin/podcasts/${p.id}/verify`, { verified: !p.verified }))}>{p.verified ? 'Unverify' : 'Verify'}</Button>
            </Card>))}</div>
        )}
        {tab === 'users' && <div className="space-y-1 text-sm">{(users.data?.users ?? []).map((u: any) => <div key={u.id}>#{u.id} {u.email} · {u.role} · {u.tier}</div>)}</div>}
        {tab === 'metrics' && (
          <div className="grid gap-4 md:grid-cols-2">
            <Card><h3 className="mb-2 font-semibold">Engine: {metrics.data?.engine}</h3>
              {Object.entries(metrics.data?.weights ?? {}).map(([k, v]) => <div key={k} className="flex justify-between text-sm"><span>{k}</span><span>{v as number}</span></div>)}</Card>
            <Card><h3 className="mb-2 font-semibold">Matches by type</h3>
              {(metrics.data?.byType ?? []).map((t: any) => <div key={t.targetType} className="flex justify-between text-sm"><span>{t.targetType}</span><span>{t.n} · avg {t.avgScore} · max {t.maxScore}</span></div>)}</Card>
            <Card className="md:col-span-2"><h3 className="mb-2 font-semibold">Recommendations</h3>
              {(recs.data?.recommendations ?? []).map((r: any, i: number) => <p key={i} className="text-sm">• {r.message}</p>)}</Card>
          </div>
        )}
        {tab === 'showcase' && (
          <div className="space-y-3">
            <Input placeholder="Search directory…" value={q} onChange={(e) => setQ(e.target.value)} />
            {hits.map((p) => (
              <Card key={p.id} className="flex items-center justify-between py-3"><span>{p.name}</span>
                <Button size="sm" variant={p.featured ? 'outline' : 'default'} onClick={async () => { await api.post(`/api/admin/showcase/${p.id}/feature`, { featured: !p.featured }); setQ(q + ' '); setQ(q); toast('Updated'); }}>{p.featured ? 'Unfeature' : 'Feature'}</Button></Card>
            ))}
          </div>
        )}
        {tab === 'invites' && <div className="space-y-2 text-sm">{(invites.data?.invites ?? []).map((i: any) => <Card key={i.id}>{i.email} · {i.orgName} · {i.status}<p className="text-muted-foreground">{i.message}</p></Card>)}</div>}
        {tab === 'ingestion' && <Card><p className="text-sm text-muted-foreground">{jobs.data?.note ?? 'Loading…'}</p><p className="mt-2 text-sm">Jobs recorded: {jobs.data?.jobs?.length ?? 0}</p></Card>}
      </div>
    </AppLayout>
  );
}
