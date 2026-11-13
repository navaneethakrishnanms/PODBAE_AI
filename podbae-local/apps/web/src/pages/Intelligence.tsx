import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AlertTriangle, BadgeCheck, Bot, CheckCircle2, Clock, FileUp, RefreshCw, ShieldQuestion, UserCheck } from 'lucide-react';
import { useState } from 'react';
import { INGEST_STAGES, TIER_LABELS, type DataTier } from '@podbae/contracts';
import { AppLayout } from '../components/Layout';
import { Badge, Button, Card, Empty, Field, Input, Spinner, toast } from '../components/ui';
import { api } from '../lib/api';

const TIER_STYLE: Record<DataTier, string> = {
  verified: 'bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-300',
  creator_provided: 'bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-300',
  estimated: 'bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300',
  inferred: 'bg-purple-100 text-purple-800 dark:bg-purple-900/40 dark:text-purple-300',
};
const TIER_ICON: Record<DataTier, typeof BadgeCheck> = { verified: BadgeCheck, creator_provided: UserCheck, estimated: Clock, inferred: Bot };
const STAGE_LABEL: Record<string, string> = {
  feed: 'Reading your RSS feed', directory: 'Matching directory records', transcripts: 'Checking transcripts',
  enrich: 'Understanding your content (rules + local model)', embed: 'Building similarity vectors',
};
export const GROUPS: [string, string][] = [['identity', 'Identity'], ['activity', 'Activity & format'], ['content', 'Content understanding (inferred by rules + a local model; no LLM)'],
  ['audience', 'Audience (creator analytics only)'], ['creator', 'Your goals']];

const fmtDate = (s?: string | null) => (s ? new Date(s).toLocaleString() : '—');

export function TierBadge({ field }: { field: any }) {
  const tier = field.data_tier as DataTier;
  const Icon = TIER_ICON[tier];
  const tip = [`Source: ${field.source.name} (${field.source.kind})`, `Method: ${field.method}${field.model_version ? ` · ${field.model_version}` : ''}`,
    `Fetched: ${fmtDate(field.fetched_at)}`, field.expires_at ? `Fresh until: ${fmtDate(field.expires_at)}` : 'No expiry',
    `Confidence: ${Math.round(field.confidence * 100)}%`, field.source_ref ? `Ref: ${field.source_ref}` : ''].filter(Boolean).join('\n');
  return (
    <span title={tip} className={`inline-flex cursor-help items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold ${TIER_STYLE[tier]}`}>
      <Icon className="h-3 w-3" />{TIER_LABELS[tier]}
    </span>
  );
}

export function JobProgress({ job }: { job: any }) {
  const done: string[] = job?.stages_done ?? [];
  const failed = job?.status === 'failed';
  return (
    <Card>
      <div className="mb-3 flex items-center justify-between">
        <h3 className="font-semibold">{failed ? 'Ingestion failed' : job?.status === 'succeeded' ? 'Ingestion complete' : 'Building your profile…'}</h3>
        <Badge tone={failed ? 'pink' : job?.status === 'succeeded' ? 'green' : 'gray'}>{job?.status ?? 'queued'}</Badge>
      </div>
      <div className="mb-4 h-2 overflow-hidden rounded-full bg-muted"><div className="h-full bg-primary transition-all" style={{ width: `${job?.percent ?? 0}%` }} /></div>
      <ul className="space-y-1.5 text-sm">
        {INGEST_STAGES.map((s) => (
          <li key={s} className="flex items-center gap-2">
            {done.includes(s) ? <CheckCircle2 className="h-4 w-4 text-green-600" /> : <span className="h-4 w-4 rounded-full border border-input" />}
            <span className={done.includes(s) ? '' : 'text-muted-foreground'}>{STAGE_LABEL[s]}</span>
          </li>
        ))}
      </ul>
      {failed && <p className="mt-3 text-sm text-destructive">{job.last_error}</p>}
      {job?.attempts > 1 && !failed && <p className="mt-3 text-xs text-muted-foreground">Retry {job.attempts}/{job.max_attempts}: {job.last_error}</p>}
    </Card>
  );
}

function Value({ name, v }: { name: string; v: any }) {
  if (v === null || v === undefined) return <span className="text-muted-foreground">—</span>;
  if (name === 'vibe') {
    const top = Object.entries(v as Record<string, number>).filter(([, x]) => x > 0).sort((a, b) => b[1] - a[1]);
    return top.length ? <div className="w-full max-w-sm space-y-1">{top.map(([k, x]) => (
      <div key={k} className="flex items-center gap-2 text-xs"><span className="w-32 shrink-0">{k}</span>
        <div className="h-1.5 flex-1 rounded-full bg-muted"><div className="h-full rounded-full bg-primary" style={{ width: `${x * 100}%` }} /></div><span className="w-8 text-right">{x.toFixed(2)}</span></div>))}</div>
      : <span className="text-muted-foreground">No clear vibe signal in the text</span>;
  }
  if (name === 'topics') {
    if (!(v as any[]).length) return <span className="text-muted-foreground">No topic has enough evidence yet (needs 2 episodes, or the description + 1 episode)</span>;
    return <div className="flex flex-wrap gap-1">{(v as any[]).map((t) => (
      <span key={t.id ?? t.name} title={`Basis: ${(t.basis ?? []).join(', ')}${t.episodes != null ? ` · ${t.episodes} supporting episode(s)` : ''}${t.in_description ? ' · in description' : ''}`}>
        <Badge>{t.name} · {Math.round(t.weight * 100)}%</Badge></span>))}</div>;
  }
  if (name === 'declared_topics') return <div className="flex flex-wrap gap-1">{(v as string[]).length ? (v as string[]).map((x) => <Badge key={x} tone="green">{x.replace(/_/g, ' ')}</Badge>) : <span className="text-muted-foreground">Categories do not map to a topic</span>}</div>;
  if (name === 'conversational_style' && v === 'unknown') return <span className="text-muted-foreground">Unknown: no rule was confident, so we do not guess</span>;
  if (name.startsWith('audience.')) {
    const d = v.data;
    return (
      <div className="text-sm">
        {Array.isArray(d) ? <table className="text-xs"><tbody>{d.slice(0, 8).map((r: any, i: number) => (
          <tr key={i}><td className="pr-4">{r.label}</td><td className="pr-4">{r.count ?? ''}</td><td>{r.percent != null ? `${r.percent}%` : ''}</td></tr>))}</tbody></table>
          : Object.entries(d ?? {}).map(([k, x]) => <div key={k}>{k.replace(/_/g, ' ')}: <b>{Number(x).toLocaleString()}</b></div>)}
        {v.plausibility_flags?.length > 0 && <p className="mt-1 text-xs text-amber-600">Flagged as possibly implausible: {v.plausibility_flags.join(', ')}</p>}
      </div>
    );
  }
  if (name === 'guests_present') return <span>{v.value ? 'Yes' : 'Not evident'} <span className="text-xs text-muted-foreground">({v.basis}; {v.guest_episodes ?? Math.round(v.share * (v.episodes_checked ?? 0))} of {v.episodes_checked ?? '?'} recent episodes, {Math.round(v.share * 100)}%)</span></span>;
  if (name === 'transcripts_available') return <span>{v.episodes_with_transcript} of {v.of} episodes</span>;
  if (name === 'guest_friendliness') return <span>{Math.round(v * 100)}% of recent episodes name a guest</span>;
  if (name === 'last_published') return <span>{new Date(v).toLocaleDateString()}</span>;
  if (typeof v === 'boolean') return <span>{v ? 'Yes' : 'No'}</span>;
  if (Array.isArray(v)) return <div className="flex flex-wrap gap-1">{v.length ? v.map((x) => <Badge key={String(x)}>{String(x).replace(/_/g, ' ')}</Badge>) : <span className="text-muted-foreground">None detected</span>}</div>;
  if (typeof v === 'string') return <span className="whitespace-pre-line">{v.replace(/_/g, name === 'conversational_style' ? ' ' : '_').slice(0, 400)}</span>;
  return <span>{String(v)}</span>;
}

export function FieldRow({ name, f }: { name: string; f: any }) {
  return (
    <div className="border-b border-border py-3 last:border-0">
      <div className="flex flex-wrap items-center gap-2">
        <span className="w-56 shrink-0 text-sm font-medium">{f.label}</span>
        <TierBadge field={f} />
        {f.freshness === 'stale' && <span title="Past its freshness window; a refresh has been queued" className="inline-flex items-center gap-1 text-xs text-amber-600"><AlertTriangle className="h-3 w-3" />stale</span>}
        {f.low_confidence && <span title="Low confidence" className="inline-flex items-center gap-1 text-xs text-muted-foreground"><ShieldQuestion className="h-3 w-3" />low confidence</span>}
        {f.conflict && <span title={`Other sources said: ${f.alternatives.map((a: any) => `${a.source}=${JSON.stringify(a.value)}`).join('; ')}`} className="text-xs text-amber-600">sources disagree</span>}
      </div>
      <div className="mt-1.5 pl-0 text-sm md:pl-56"><Value name={name} v={f.value} /></div>
      {f.evidence?.length > 0 && (
        <details className="mt-1 md:pl-56"><summary className="cursor-pointer text-xs text-muted-foreground">Evidence ({f.evidence.length})</summary>
          <ul className="mt-1 space-y-1">{f.evidence.map((e: any) => <li key={e.id} className="border-l-2 border-primary/40 pl-2 text-xs italic text-muted-foreground">“{e.snippet}”</li>)}</ul></details>
      )}
    </div>
  );
}

function AudienceUpload({ onDone }: { onDone: () => void }) {
  const [file, setFile] = useState<{ name: string; csv: string } | null>(null);
  const [probe, setProbe] = useState<any>(null);
  const [mapping, setMapping] = useState<any>(null);
  const [result, setResult] = useState<any>(null);
  const [err, setErr] = useState('');
  const step1 = useMutation({
    mutationFn: (f: { name: string; csv: string }) => api.post('/api/intel/my/audience-upload', { filename: f.name, csv: f.csv }),
    onSuccess: (r) => { setProbe(r); setMapping(r.suggested_mapping); setErr(''); },
    onError: (e: any) => setErr(e.message),
  });
  const step2 = useMutation({
    mutationFn: () => api.post('/api/intel/my/audience-upload', { filename: file!.name, csv: file!.csv, mapping }),
    onSuccess: (r) => { setResult(r); setErr(''); onDone(); toast('Audience data stored as creator-provided'); },
    onError: (e: any) => setErr(e.message),
  });
  const cols: string[] = probe?.columns ?? [];
  const colSel = (key: string, label: string) => (
    <Field label={label}><select className="w-full rounded-lg border border-input bg-card px-3 py-2 text-sm" value={mapping?.[key] ?? ''} onChange={(e) => setMapping({ ...mapping, [key]: e.target.value || null })}>
      <option value="">—</option>{cols.map((c) => <option key={c}>{c}</option>)}</select></Field>
  );
  return (
    <Card className="space-y-3">
      <h3 className="flex items-center gap-2 font-semibold"><FileUp className="h-4 w-4" />Upload audience analytics (CSV)</h3>
      <p className="text-sm text-muted-foreground">Export a countries, cities, age-band or totals report from your hosting or podcast platform. It is stored as <b>creator-provided</b>, with your file kept as evidence. Implausible numbers are flagged, not hidden.</p>
      <input type="file" accept=".csv,text/csv" onChange={async (e) => { const f = e.target.files?.[0]; if (!f) return; const csv = await f.text(); setFile({ name: f.name, csv }); setResult(null); step1.mutate({ name: f.name, csv }); }} />
      {step1.isPending && <Spinner />}
      {err && <p className="text-sm text-destructive">{err}</p>}
      {probe && !result && (
        <div className="space-y-3">
          <p className="text-sm font-medium">Map your columns</p>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="What is this report?"><select className="w-full rounded-lg border border-input bg-card px-3 py-2 text-sm" value={mapping?.kind ?? ''} onChange={(e) => setMapping({ ...mapping, kind: e.target.value })}>
              {['countries', 'cities', 'age_bands', 'totals'].map((k) => <option key={k} value={k}>{k.replace('_', ' ')}</option>)}</select></Field>
            {mapping?.kind !== 'totals' && colSel('label_col', 'Label column')}
            {mapping?.kind !== 'totals' && colSel('value_col', 'Count column (optional)')}
            {mapping?.kind !== 'totals' && colSel('percent_col', 'Percent column (optional)')}
          </div>
          {mapping?.kind === 'totals' && <p className="text-xs text-muted-foreground">Totals: map metrics below (JSON: {'{"downloads_30d": "Your Column"}'}).<Input className="mt-1" value={JSON.stringify(mapping?.columns ?? {})} onChange={(e) => { try { setMapping({ ...mapping, columns: JSON.parse(e.target.value) }); } catch { /* keep typing */ } }} /></p>}
          <div className="overflow-x-auto rounded border border-border text-xs"><table className="w-full"><thead><tr>{cols.map((c) => <th key={c} className="px-2 py-1 text-left">{c}</th>)}</tr></thead>
            <tbody>{probe.sample_rows.map((r: any, i: number) => <tr key={i}>{cols.map((c) => <td key={c} className="px-2 py-1">{r[c]}</td>)}</tr>)}</tbody></table></div>
          <Button size="sm" disabled={step2.isPending} onClick={() => step2.mutate()}>Import with this mapping</Button>
        </div>
      )}
      {result && (
        <div className="space-y-1 text-sm">
          <p className="font-medium text-green-700 dark:text-green-400">Imported {result.rows_read} rows as {result.field}.</p>
          {result.warnings.map((w: any, i: number) => <p key={i} className="text-amber-600">⚠ {w.message}</p>)}
        </div>
      )}
    </Card>
  );
}

const GOAL_LABEL: Record<string, string> = { cross_promo: 'Cross-promos', guest_swap: 'Guest swaps', feed_swap: 'Feed swaps',
  find_guests: 'Find guests', be_a_guest: 'Be a guest', grow_audience: 'Grow my audience' };
const FLAG_LABEL = (f: string) => f.replace(/_/g, ' ');

function Chips({ options, value, onChange, labelOf }: { options: string[]; value: string[]; onChange: (v: string[]) => void; labelOf?: (x: string) => string }) {
  return (
    <div className="flex flex-wrap gap-1.5">{options.map((o) => {
      const on = value.includes(o);
      return <button type="button" key={o} aria-pressed={on} onClick={() => onChange(on ? value.filter((x) => x !== o) : [...value, o])}
        className={`rounded-full border px-2.5 py-0.5 text-xs ${on ? 'border-primary bg-primary text-primary-foreground' : 'border-input bg-card hover:bg-secondary'}`}>{labelOf ? labelOf(o) : o}</button>;
    })}</div>
  );
}

/** The creator fields the Layer 4 engine uses. Stored as creator-provided (never inferred). */
function PartnerSettings({ fields, onDone }: { fields: Record<string, any>; onDone: () => void }) {
  const opts = useQuery({ queryKey: ['opp-options'], queryFn: () => api.get('/api/opportunities/options') });
  const [goals, setGoals] = useState<string[]>(fields['creator.goals']?.value ?? []);
  const [open, setOpen] = useState<string>(fields['creator.collaboration_openness']?.value ?? '');
  const [blocked, setBlocked] = useState<string[]>(fields['creator.blocked_categories']?.value ?? []);
  const [flags, setFlags] = useState<string[]>(fields['creator.blocked_brand_safety_flags']?.value ?? []);
  const [showTopics, setShowTopics] = useState(false);
  const save = useMutation({
    mutationFn: () => api.put('/api/intel/my/creator-profile', {
      goals, ...(open ? { collaboration_openness: open } : {}), blocked_categories: blocked, blocked_brand_safety_flags: flags,
    }),
    onSuccess: () => { toast('Saved as creator-provided. Your partner list will refresh.'); onDone(); },
    onError: (e: any) => toast(e.message),
  });
  const o = opts.data;
  const topics: any[] = o?.topics ?? [];
  const topicLabel = (id: string) => topics.find((x) => x.id === id)?.label ?? id;
  return (
    <Card className="space-y-4" >
      <div data-testid="partner-settings"><h3 className="font-semibold">Partner matching settings</h3>
        <p className="text-xs text-muted-foreground">Used by the podcast-partner engine. Blocked categories, topics and brand-safety flags remove a show
          before it is ever scored, however good the fit. Saved as <b>creator-provided</b>.</p></div>
      <Field label="Goals"><Chips options={o?.goals ?? Object.keys(GOAL_LABEL)} value={goals} onChange={setGoals} labelOf={(g) => GOAL_LABEL[g] ?? g} /></Field>
      <Field label="Collaboration openness" hint="(open or selective = shown to other members as Verified)">
        <select className="w-full rounded-lg border border-input bg-card px-3 py-2 text-sm" value={open} onChange={(e) => setOpen(e.target.value)}>
          <option value="">Not stated</option><option value="open">Open to most collaborations</option><option value="selective">Selective</option>
          <option value="closed">Not looking right now (you will not be suggested to others)</option></select></Field>
      <Field label="Blocked categories"><Chips options={o?.categoryGroups ?? []} value={blocked} onChange={setBlocked} /></Field>
      <div>
        <button type="button" className="text-xs font-medium text-purple-600" onClick={() => setShowTopics(!showTopics)}>{showTopics ? 'Hide' : 'Block specific topics'}</button>
        {showTopics && <div className="mt-2"><Chips options={topics.map((x) => x.id)} value={blocked} onChange={setBlocked} labelOf={topicLabel} /></div>}
      </div>
      <Field label="Blocked brand-safety flags"><Chips options={o?.brandSafetyFlags ?? []} value={flags} onChange={setFlags} labelOf={FLAG_LABEL} /></Field>
      <Button size="sm" onClick={() => save.mutate()} disabled={save.isPending}>Save settings</Button>
    </Card>
  );
}

export default function Intelligence() {
  const qc = useQueryClient();
  const [rss, setRss] = useState('');
  const [panel, setPanel] = useState<'' | 'upload'>('');
  const status = useQuery({
    queryKey: ['intel-status'], queryFn: () => api.get('/api/intel/my/status'),
    refetchInterval: (q) => { const s = q.state.data; return s?.job && ['queued', 'running'].includes(s.job.status) ? 1500 : false; },
  });
  const ready = status.data?.job?.status === 'succeeded' || (status.data?.show_id && !status.data?.job);
  const profile = useQuery({
    queryKey: ['intel-profile', status.data?.show_id], enabled: !!status.data?.linked && !!ready, retry: false,
    queryFn: () => api.get('/api/intel/my/profile'),
  });
  const refreshAll = () => { qc.invalidateQueries({ queryKey: ['intel-profile'] }); qc.invalidateQueries({ queryKey: ['intel-status'] }); };
  const connect = useMutation({
    mutationFn: () => api.post('/api/agent/ingest-rss', { rssUrl: rss }),
    onSuccess: (r) => { toast(r.ai_available ? 'Feed received. Building your profile…' : r.note ?? 'Saved; the AI service is down'); refreshAll(); },
    onError: (e: any) => toast(e.message),
  });
  const refresh = useMutation({
    mutationFn: () => api.post('/api/intel/my/refresh'), onSuccess: () => { toast('Refresh started'); refreshAll(); }, onError: (e: any) => toast(e.message),
  });

  const p = profile.data?.profile;
  const job = status.data?.job;
  return (
    <AppLayout>
      <div className="mx-auto max-w-4xl space-y-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div><h1 className="text-3xl font-extrabold">Podcast Intelligence</h1>
            <p className="text-sm text-muted-foreground">Everything below says where it came from, how sure we are, and when we last checked.</p></div>
          {p && <Button variant="outline" size="sm" onClick={() => refresh.mutate()} disabled={refresh.isPending}><RefreshCw className="mr-1.5 h-4 w-4" />Refresh from RSS</Button>}
        </div>

        {status.isLoading && <Spinner />}
        {status.error && <Empty>{(status.error as any).message}</Empty>}
        {status.data && !status.data.ai_up && <div className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900 dark:bg-amber-950/30 dark:text-amber-200">The intelligence service is unreachable right now.</div>}

        {status.data && !status.data.linked && (
          <Card className="space-y-3">
            <h3 className="font-semibold">Connect your show</h3>
            <p className="text-sm text-muted-foreground">Paste your public RSS feed URL. We only read what you already publish.</p>
            <div className="flex gap-2"><Input type="url" placeholder="https://feeds.example.com/your-show" value={rss} onChange={(e) => setRss(e.target.value)} />
              <Button disabled={!rss || connect.isPending} onClick={() => connect.mutate()}>Connect</Button></div>
          </Card>
        )}

        {job && job.status !== 'succeeded' && <JobProgress job={job} />}
        {job?.status === 'failed' && (
          <Card className="flex gap-2"><Input type="url" value={rss} placeholder="Try a different feed URL" onChange={(e) => setRss(e.target.value)} /><Button onClick={() => connect.mutate()} disabled={!rss}>Retry</Button></Card>
        )}

        {profile.data?.outdated && <div className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900 dark:bg-amber-950/30 dark:text-amber-200"><AlertTriangle className="mr-1 inline h-4 w-4" />{profile.data.message} Last saved {fmtDate(profile.data.cached_at)}.</div>}
        {profile.error && (profile.error as any).status === 503 && <Empty>The intelligence service is unreachable and there is no saved profile yet.</Empty>}

        {p && (
          <>
            <Card className="space-y-4">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div><h2 className="text-xl font-bold">{p.title}</h2><p className="break-all text-xs text-muted-foreground">{p.feed_url}</p></div>
                <Badge tone={p.status === 'complete' ? 'green' : p.status === 'preliminary' ? 'pink' : 'gray'}>{p.status}</Badge>
              </div>
              <div>
                <div className="mb-1 flex justify-between text-sm"><span className="font-medium">Profile completeness</span><b>{p.completeness.score}%</b></div>
                <div className="h-3 overflow-hidden rounded-full bg-muted"><div className="h-full rounded-full bg-primary transition-all" style={{ width: `${p.completeness.score}%` }} /></div>
                <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">{Object.entries(p.completeness.by_group).map(([g, n]) => <span key={g}>{g}: {String(n)}%</span>)}</div>
              </div>
              <div className="flex flex-wrap gap-2 text-xs">{(Object.keys(TIER_LABELS) as DataTier[]).map((t) => <span key={t} className={`rounded-full px-2 py-0.5 font-semibold ${TIER_STYLE[t]}`}>{TIER_LABELS[t]}</span>)}
                <span className="text-muted-foreground">Hover a badge for source and date.</span></div>
            </Card>

            {p.warnings.map((w: any) => (
              <div key={w.code} className={`rounded-lg border p-3 text-sm ${w.severity === 'warning' ? 'border-amber-300 bg-amber-50 text-amber-900 dark:bg-amber-950/30 dark:text-amber-200' : 'border-border bg-muted/40'}`}>
                <AlertTriangle className="mr-1 inline h-4 w-4" />{w.message}</div>
            ))}

            {p.improve.length > 0 && (
              <Card className="space-y-3">
                <h3 className="font-semibold">Improve your profile</h3>
                <ul className="space-y-2">{p.improve.map((i: any) => (
                  <li key={i.code} className="flex flex-wrap items-center justify-between gap-2 text-sm">
                    <span><b>{i.action}</b> <span className="text-muted-foreground">· +{i.gain_points} pts. {i.detail}</span></span>
                    {i.code === 'upload_audience' && <Button size="sm" variant="outline" onClick={() => setPanel('upload')}>Upload CSV</Button>}
                    {i.code === 'declare_goals' && <Button size="sm" variant="outline" onClick={() => document.querySelector('[data-testid=partner-settings]')?.scrollIntoView({ behavior: 'smooth' })}>Add</Button>}
                    {(i.code === 'refresh' || i.code === 'fix_feed') && <Button size="sm" variant="outline" onClick={() => refresh.mutate()}>Refresh</Button>}
                  </li>))}</ul>
              </Card>
            )}
            {(panel === 'upload' || !p.improve.some((i: any) => i.code === 'upload_audience')) && panel === 'upload' && <AudienceUpload onDone={refreshAll} />}
            <PartnerSettings key={p.generated_at} fields={p.fields} onDone={refreshAll} />
            {panel === '' && !p.improve.some((i: any) => i.code === 'upload_audience') && <Button variant="outline" size="sm" onClick={() => setPanel('upload')}>Upload more audience data</Button>}

            {GROUPS.map(([g, label]) => {
              const rows = Object.entries(p.fields).filter(([, f]: any) => f.group === g);
              const missing = p.missing.filter((m: any) => m.group === g);
              if (!rows.length && !missing.length) return null;
              return (
                <Card key={g}>
                  <h3 className="mb-1 font-semibold">{label}</h3>
                  {rows.map(([k, f]) => <FieldRow key={k} name={k} f={f} />)}
                  {missing.length > 0 && <p className="mt-2 text-xs text-muted-foreground"><b>Unknown (not available, never guessed):</b> {missing.map((m: any) => m.label).join(' · ')}</p>}
                </Card>
              );
            })}
            <p className="text-xs text-muted-foreground">{p.trust_note}</p>
          </>
        )}
      </div>
    </AppLayout>
  );
}
