// Admin → Engine: Layer 4 opportunity engine metrics, gate rejections, factor coverage, regenerate, demo setup.
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { Link } from 'wouter';
import { api } from '../lib/api';
import { Badge, Button, Card, Input, Spinner, toast } from './ui';

function Bars({ rows, fmt }: { rows: { from: number; to: number; n: number }[]; fmt: (x: number) => string }) {
  const max = Math.max(1, ...rows.map((r) => r.n));
  return (
    <div className="space-y-1">{rows.map((r) => (
      <div key={r.from} className="flex items-center gap-2 text-xs">
        <span className="w-20 shrink-0 text-muted-foreground">{fmt(r.from)}–{fmt(r.to)}</span>
        <div className="h-2 flex-1 rounded bg-muted"><div className="h-2 rounded bg-primary" style={{ width: `${(100 * r.n) / max}%` }} /></div>
        <span className="w-10 text-right">{r.n}</span>
      </div>))}</div>
  );
}

export function EngineTab() {
  const qc = useQueryClient();
  const m = useQuery({ queryKey: ['a-engine'], queryFn: () => api.get('/api/admin/engine/metrics') });
  const sm = useQuery({ queryKey: ['a-engine-sponsor'], queryFn: () => api.get('/api/admin/engine/sponsor-metrics') });
  const [showId, setShowId] = useState('');
  const [busy, setBusy] = useState(false);
  const regen = async (id: string) => {
    try { const r = await api.post('/api/admin/engine/regenerate', { showId: id }); toast(`Regeneration queued (${r.jobId})`); setTimeout(() => qc.invalidateQueries({ queryKey: ['a-engine'] }), 2500); }
    catch (e: any) { toast(e.message); }
  };
  const demo = async () => {
    setBusy(true);
    try { const r = await api.post('/api/admin/engine/demo-setup'); toast(`Demo ready: ${r.members.length} members, demo show "${r.demoPodcaster.show}"`); qc.invalidateQueries({ queryKey: ['a-engine'] }); }
    catch (e: any) { toast(e.message); } finally { setBusy(false); }
  };
  if (m.isLoading) return <Spinner />;
  if (m.error) return <Card className="text-sm text-destructive">Engine metrics unavailable: {(m.error as any).message}</Card>;
  const d = m.data;
  const c = d.counts ?? {};
  return (
    <div className="space-y-4">
      <Card className="space-y-2">
        <div className="flex flex-wrap items-center gap-2">
          <h3 className="font-semibold">Opportunity engine · podcast partners</h3>
          <Badge tone="pink">{d.scoringVersion}</Badge><Badge tone="gray">{d.status}</Badge><span className="text-xs text-muted-foreground">config {d.configHash}</span>
        </div>
        <p className="text-sm text-muted-foreground">Shown only if Fit ≥ {d.thresholds?.minFit} and evidence confidence ≥ {d.thresholds?.minConfidence}. No LLM. Weights are a draft pending founder approval.</p>
        <div className="flex flex-wrap gap-2 text-xs">{Object.entries(d.weights ?? {}).map(([k, v]) => <Badge key={k}>{k.replace(/([A-Z])/g, ' $1').toLowerCase()}: {String(v)}</Badge>)}</div>
        <div className="flex flex-wrap gap-2 pt-2">
          <Button size="sm" variant="outline" disabled={busy} onClick={demo}>{busy ? 'Setting up…' : 'Set up demo members'}</Button>
          <Link href="/admin/labels/pairs"><Button size="sm" variant="outline">Pair labels (engine vs legacy)</Button></Link>
        </div>
      </Card>
      <div className="flex flex-wrap gap-3">
        {[['Member shows run', c.memberShowsWithRuns], ['Qualified opportunities', c.opportunitiesQualified], ['Members with ≥1', c.membersWith1Plus],
          ['Members with ≥3', c.membersWith3Plus], ['No-match members', c.membersNoMatch], ['Median latency (ms)', d.latencyMs?.median ?? '–']].map(([l, v]) => (
          <Card key={l as string} className="px-4 py-3"><div className="text-2xl font-extrabold text-primary">{v ?? 0}</div><div className="text-xs text-muted-foreground">{l}</div></Card>))}
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        <Card><h3 className="mb-2 font-semibold">Gate rejections (latest run per member)</h3>
          {Object.keys(d.gateRejections ?? {}).length ? <table className="w-full text-sm"><tbody>{Object.entries(d.gateRejections).map(([k, v]) => (
            <tr key={k}><td className="py-0.5">{k.replace(/([A-Z])/g, '_$1').toLowerCase()}</td><td className="text-right">{String(v)}</td></tr>))}</tbody></table>
            : <p className="text-sm text-muted-foreground">None yet.</p>}</Card>
        <Card><h3 className="mb-2 font-semibold">Factor coverage (active opportunities)</h3>
          <table className="w-full text-sm"><thead><tr className="text-left text-xs text-muted-foreground"><th>Factor</th><th>used</th><th>missing</th><th>disabled</th></tr></thead>
            <tbody>{Object.entries(d.factorCoverage ?? {}).map(([k, v]: any) => (
              <tr key={k}><td className="py-0.5">{k.replace(/([A-Z])/g, ' $1').toLowerCase()}</td><td>{Math.round(100 * (v.used ?? 0))}%</td>
                <td>{Math.round(100 * (v.missing ?? 0))}%</td><td>{Math.round(100 * (v.disabled ?? 0))}%</td></tr>))}</tbody></table></Card>
        <Card><h3 className="mb-2 font-semibold">Fit distribution</h3><Bars rows={d.fitDistribution ?? []} fmt={(x) => String(x)} /></Card>
        <Card><h3 className="mb-2 font-semibold">Evidence confidence distribution</h3><Bars rows={d.confidenceDistribution ?? []} fmt={(x) => x.toFixed(1)} /></Card>
        <Card><h3 className="mb-2 font-semibold">Qualified, by readiness / confidence / type</h3>
          <p className="text-sm">{Object.entries(c.byReadiness ?? {}).map(([k, v]) => `${k}: ${v}`).join(' · ') || '–'}</p>
          <p className="text-sm">{Object.entries(c.byConfidenceLevel ?? {}).map(([k, v]) => `${k}: ${v}`).join(' · ') || '–'}</p>
          <p className="text-sm">{Object.entries(c.byType ?? {}).map(([k, v]) => `${k}: ${v}`).join(' · ') || '–'}</p>
          <p className="mt-2 text-xs text-muted-foreground">Events: {Object.entries(c.events ?? {}).map(([k, v]) => `${k} ${v}`).join(' · ') || 'none yet'}</p></Card>
        <Card><h3 className="mb-2 font-semibold">Engine vs legacy (blind pair labels)</h3>
          {d.pairLabels?.note ? <p className="text-sm text-muted-foreground">{d.pairLabels.note}</p> : (
            <table className="w-full text-sm"><thead><tr className="text-left text-xs text-muted-foreground"><th>System</th><th>P@3</th><th>nDCG@5</th><th>Cov@3</th></tr></thead>
              <tbody>{Object.entries(d.pairLabels?.systems ?? {}).map(([k, v]: any) => (
                <tr key={k}><td>{k}</td><td>{v.precisionAt3 ?? '–'}</td><td>{v.ndcgAt5 ?? '–'}</td><td>{v.coverageAt3 ?? '–'}</td></tr>))}</tbody></table>)}</Card>
      </div>
      <SponsorEngine d={sm.data} />
      <LlmPanel />
      <Card className="space-y-3">
        <h3 className="font-semibold">Runs per show</h3>
        <div className="flex gap-2"><Input placeholder="Show id (shw_…) to regenerate" value={showId} onChange={(e) => setShowId(e.target.value)} />
          <Button size="sm" disabled={!showId} onClick={() => regen(showId.trim())}>Regenerate</Button></div>
        <table className="w-full text-sm"><thead><tr className="text-left text-xs text-muted-foreground"><th>Show</th><th>Qualified</th><th>Scored</th><th>Rejected</th><th>ms</th><th /></tr></thead>
          <tbody>{(d.runs ?? []).map((r: any) => (
            <tr key={r.memberShowId}><td className="py-1">{r.title} {r.isMember && <Badge tone="green">member</Badge>}</td><td>{r.qualified}</td><td>{r.scored}</td><td>{r.rejected}</td>
              <td>{r.durationMs}</td><td className="text-right"><Button size="sm" variant="ghost" onClick={() => regen(r.memberShowId)}>Regenerate</Button></td></tr>))}</tbody></table>
        {!(d.runs ?? []).length && <p className="text-sm text-muted-foreground">No runs yet. Use "Set up demo members" or open a member's dashboard.</p>}
      </Card>
    </div>
  );
}

/** Phase 4: what the LLM does, measured (calls, tokens, latency, cache, pauses) + the kill-switch state. */
function LlmPanel() {
  const m = useQuery({ queryKey: ['a-llm-metrics'], queryFn: () => api.get('/api/admin/llm/metrics') });
  const d = m.data;
  const run = async () => { try { const r: any = await api.post('/api/admin/llm/run', {}); toast(`LLM refine job ${r.job_id ?? r.jobId} queued`); } catch (e: any) { toast(e.message); } };
  return (
    <Card className="space-y-3" data-testid="llm-panel">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="font-semibold">LLM refinement (Phase 4)</h3>
        {d && <Badge tone={d.llm_active ?? d.llmActive ? 'green' : 'gray'}>{(d.llm_active ?? d.llmActive) ? `on · ${d.model ?? d.provider}` : 'off (Phase 3 behaviour)'}</Badge>}
      </div>
      {m.isLoading ? <Spinner /> : !d ? <p className="text-sm text-muted-foreground">Metrics unavailable.</p> : (
        <>
          <p className="text-xs text-muted-foreground">Used only where rules are weak; every value cites verbatim evidence and is stored next to the rule value.
            Kill switches: {d.kill_switches ?? d.killSwitches}. Only public podcast content is sent.</p>
          <table className="w-full text-sm"><thead><tr className="text-left text-xs text-muted-foreground"><th>Task</th><th>Calls</th><th>Cache hits</th><th>Tokens in/out</th><th>Avg / p95 ms</th><th>Pauses</th></tr></thead>
            <tbody>{Object.entries(d.calls?.by_task ?? d.calls?.byTask ?? {}).map(([k, v]: any) => (
              <tr key={k}><td>{k}</td><td>{v.provider_calls ?? v.providerCalls}</td><td>{v.cache_hits ?? v.cacheHits}</td>
                <td>{v.tokens_in ?? v.tokensIn} / {v.tokens_out ?? v.tokensOut}</td><td>{v.latency_ms_avg ?? v.latencyMsAvg ?? '–'} / {v.latency_ms_p95 ?? v.latencyMsP95 ?? '–'}</td>
                <td>{v.rate_limit_pauses ?? v.rateLimitPauses}</td></tr>))}</tbody></table>
          {d.layer1?.style && <p className="text-xs">Conversational style unknown: {Math.round(100 * (d.layer1.style.rule_unknown_share ?? d.layer1.style.ruleUnknownShare ?? 0))}% (rules)
            → {Math.round(100 * (d.layer1.style.after_ai_unknown_share ?? d.layer1.style.afterAiUnknownShare ?? 0))}% (with AI evidence)</p>}
          <Button size="sm" variant="outline" disabled={!(d.llm_active ?? d.llmActive)} onClick={run}>Run refiners (background job)</Button>
        </>)}
    </Card>
  );
}

function SponsorEngine({ d }: { d: any }) {
  if (!d) return null;
  const c = d.counts ?? {};
  return (
    <Card className="space-y-3" >
      <div className="flex flex-wrap items-center gap-2" data-testid="engine-sponsor-metrics">
        <h3 className="font-semibold">Sponsor opportunities (Layer 2)</h3><Badge tone="pink">{d.scoringVersion}</Badge><Badge tone="gray">{d.status}</Badge>
        <Link href="/admin/sponsors/review"><Button size="sm" variant="outline">Review queue</Button></Link>
        <Link href="/admin/sponsors/brands"><Button size="sm" variant="outline">Brands</Button></Link>
      </div>
      <p className="text-sm text-muted-foreground">Members run: {c.memberShowsWithRuns ?? 0} · qualified: {c.opportunitiesQualified ?? 0} · ≥1: {c.membersWith1Plus ?? 0} · ≥3: {c.membersWith3Plus ?? 0} · no-match: {c.membersNoMatch ?? 0}</p>
      <div className="grid gap-4 md:grid-cols-3 text-sm">
        <div><b className="text-xs">Gate reasons</b>{Object.entries(d.gateRejections ?? {}).map(([k, v]) => <div key={k} className="flex justify-between"><span>{k.replace(/([A-Z])/g, '_$1').toLowerCase()}</span><span>{String(v)}</span></div>)}</div>
        <div><b className="text-xs">Factor coverage (used)</b>{Object.entries(d.factorCoverage ?? {}).map(([k, v]: any) => <div key={k} className="flex justify-between"><span>{k.replace(/([A-Z])/g, ' $1').toLowerCase()}</span><span>{Math.round(100 * (v.used ?? 0))}%{v.disabled ? ' (disabled)' : ''}</span></div>)}</div>
        <div><b className="text-xs">Readiness / contact</b>{Object.entries(c.byReadiness ?? {}).map(([k, v]) => <div key={k} className="flex justify-between"><span>{k}</span><span>{String(v)}</span></div>)}
          {Object.entries(c.byContactStatus ?? {}).map(([k, v]) => <div key={k} className="flex justify-between text-muted-foreground"><span>{k}</span><span>{String(v)}</span></div>)}</div>
      </div>
    </Card>
  );
}
