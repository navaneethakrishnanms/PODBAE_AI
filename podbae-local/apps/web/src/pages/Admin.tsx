import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { Link, useLocation } from 'wouter';
import { EngineTab } from '../components/EngineTab';
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
  const jobs = useQuery({ queryKey: ['a-jobs'], enabled: tab === 'ingestion', refetchInterval: tab === 'ingestion' ? 3000 : false, queryFn: () => api.get('/api/admin/intel/jobs') });
  const cov = useQuery({ queryKey: ['a-cov'], enabled: tab === 'coverage', queryFn: () => api.get('/api/admin/intel/coverage') });
  const costs = useQuery({ queryKey: ['a-costs'], enabled: tab === 'costs', queryFn: () => api.get('/api/admin/intel/costs') });
  const health = useQuery({ queryKey: ['a-health'], enabled: tab === 'ingestion' || tab === 'costs', queryFn: () => api.get('/api/intel/health') });
  const failures = useQuery({ queryKey: ['a-fail'], enabled: tab === 'coverage', queryFn: () => api.get('/api/admin/intel/feed-failures') });
  const agree = useQuery({ queryKey: ['a-agree'], enabled: tab === 'labels', queryFn: () => api.get('/api/admin/intel/labels/agreement') });
  const [feed, setFeed] = useState('');
  const [disc, setDisc] = useState('');
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
        { id: 'ingestion', label: 'Ingestion jobs' }, { id: 'coverage', label: 'Coverage' }, { id: 'costs', label: 'Costs' }, { id: 'labels', label: 'Labels' }, { id: 'engine', label: 'Engine' },
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
        {tab === 'ingestion' && (
          <div className="space-y-4">
            <Card className="space-y-3">
              <p className="text-sm text-muted-foreground">AI service: {health.data?.up ? <b className="text-green-600">up</b> : <b className="text-destructive">down</b>}
                {health.data?.llm && <> · LLM <b>{health.data.llm.active}</b> · embeddings <b>{health.data.embeddings?.active}</b> · podcastindex key {health.data.providers?.podcastindex ? 'yes' : 'no'} · taddy {health.data.providers?.taddy ? 'on' : 'off'}</>}</p>
              <div className="flex gap-2"><Input placeholder="RSS feed URL to ingest" value={feed} onChange={(e) => setFeed(e.target.value)} />
                <Button size="sm" onClick={run('Ingest', () => api.post('/api/admin/intel/ingest', { rssUrl: feed }))} disabled={!feed}>Ingest feed</Button></div>
              <div className="flex gap-2"><Input placeholder="Discover shows by search term (Podcast Index, else iTunes Search)" value={disc} onChange={(e) => setDisc(e.target.value)} />
                <Button size="sm" variant="outline" onClick={run('Discover', () => api.post('/api/admin/intel/discover', { query: disc, limit: 25 }))} disabled={!disc}>Discover</Button></div>
              <div className="flex items-center gap-2"><Button size="sm" variant="outline" onClick={run('Recalibrate', () => api.post('/api/admin/intel/recalibrate'))}>Recalibrate corpus</Button>
                <span className="text-xs text-muted-foreground">Recomputes vibe z-scores and style-vector centring across all shows (no LLM).</span></div>
            </Card>
            <div className="flex flex-wrap gap-2 text-sm">{Object.entries(jobs.data?.counts ?? {}).map(([k, v]) => <Badge key={k} tone={k === 'failed' ? 'pink' : k === 'succeeded' ? 'green' : 'gray'}>{k}: {String(v)}</Badge>)}</div>
            <div className="space-y-1 text-sm">{(jobs.data?.jobs ?? []).map((j: any) => (
              <Card key={j.id} className="py-2"><b>{j.type}</b> <span className="text-xs text-muted-foreground">{j.id}</span> · {j.status} · {j.percent}% · attempts {j.attempts}/{j.max_attempts}
                {j.last_error && <span className="text-destructive"> · {j.last_error}</span>}</Card>))}</div>
          </div>
        )}
        {tab === 'coverage' && (
          <div className="space-y-4">
            <p className="text-sm text-muted-foreground">Measured data-feasibility matrix: share of successfully fetched shows where each connector actually returned the field. {cov.data?.note}</p>
            {Object.entries(cov.data?.connectors ?? {}).map(([name, c]: any) => (
              <Card key={name}><h3 className="font-semibold">{name} <span className="text-xs font-normal text-muted-foreground">{c.shows_ok}/{c.shows_attempted} shows fetched OK</span></h3>
                <table className="mt-2 w-full text-sm"><tbody>{Object.entries(c.fields).map(([f, v]: any) => (
                  <tr key={f}><td className="w-56 py-0.5">{f}</td><td><div className="h-2 w-full rounded bg-muted"><div className="h-2 rounded bg-primary" style={{ width: `${v.pct}%` }} /></div></td><td className="w-20 text-right">{v.pct}%</td></tr>))}</tbody></table></Card>))}
            {cov.data && !Object.keys(cov.data.connectors).length && <p className="text-sm text-muted-foreground">No ingestion has run yet.</p>}
            {failures.data && (
              <Card><h3 className="font-semibold">Feed fetch outcomes <span className="text-xs font-normal text-muted-foreground">latest attempt per feed URL · {failures.data.ok}/{failures.data.feeds} ok
                {failures.data.success_rate != null && ` (${Math.round(failures.data.success_rate * 100)}%)`}</span></h3>
                {Object.keys(failures.data.by_reason ?? {}).length === 0 ? <p className="mt-2 text-sm text-muted-foreground">No failed feeds.</p> : (
                  <table className="mt-2 text-sm"><tbody>{Object.entries(failures.data.by_reason).map(([k, v]: any) => (
                    <tr key={k}><td className="w-40 py-0.5">{k}</td><td className="text-right">{v}</td></tr>))}</tbody></table>)}
                {(failures.data.recent_failures ?? []).length > 0 && (
                  <details className="mt-2"><summary className="cursor-pointer text-xs text-muted-foreground">Recent failures</summary>
                    <ul className="mt-1 space-y-0.5 text-xs">{failures.data.recent_failures.slice(-20).map((f: any) => <li key={f.target}><b>{f.error_kind}</b> · {f.target}</li>)}</ul></details>)}
              </Card>)}
          </div>
        )}
        {tab === 'labels' && (
          <Card className="space-y-2">
            <h3 className="font-semibold">Human evaluation labels</h3>
            <p className="text-sm text-muted-foreground">30 real shows, labelled one at a time. Only human labels are scored; machine-written drafts are excluded.</p>
            <div className="text-sm">{(agree.data?.labelers ?? []).length ? agree.data.labelers.map((l: any) => `${l.labeler}: ${l.labelled}/${l.of}`).join(' · ') : 'No labels yet.'}</div>
            <p className="text-sm">{agree.data?.status === 'ok' ? `Agreement available for ${agree.data.pairs.length} labeler pair(s).` : agree.data?.message}</p>
            <Link href="/admin/labels"><Button size="sm">Open the labelling page</Button></Link>
          </Card>
        )}
        {tab === 'engine' && <EngineTab />}
        {tab === 'costs' && (
          <div className="grid gap-4 md:grid-cols-2">
            <Card><h3 className="mb-2 font-semibold">Totals (estimates)</h3>
              <div className="text-sm">Total: <b>${costs.data?.total_usd ?? 0}</b> · avg/show <b>${costs.data?.avg_usd_per_show ?? 0}</b> · p95/show <b>${costs.data?.p95_usd_per_show ?? 0}</b></div>
              <div className="text-sm">Enrichment cache hit rate: <b>{costs.data?.cache_hit_rate_enrichment ?? 'n/a'}</b></div>
              <div className="mt-2 text-xs text-muted-foreground">Mock LLM and local embeddings cost $0 in API spend; GPU time is an estimate.</div></Card>
            <Card><h3 className="mb-2 font-semibold">Budgets</h3>{(costs.data?.budgets ?? []).map((b: any, i: number) => <div key={i} className="flex justify-between text-sm"><span>{b.scope}:{b.key} / {b.period}</span><span>${b.used_usd} of ${b.limit_usd}</span></div>)}</Card>
            <Card className="md:col-span-2"><h3 className="mb-2 font-semibold">By operation</h3>
              {Object.entries(costs.data?.by_operation ?? {}).map(([op, v]: any) => <div key={op} className="flex justify-between text-sm"><span>{op}</span><span>{v.calls} calls · {v.cache_hits} cache hits · {v.skipped} skipped · ${v.usd}</span></div>)}</Card>
          </div>
        )}
      </div>
    </AppLayout>
  );
}
