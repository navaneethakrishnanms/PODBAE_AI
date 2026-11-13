// Blind pair labels (Phase 2 evaluation): for 20 member shows, the UNION of the engine's and the legacy scorer's top 5, in a
// fixed random order. The labeler is never told which system suggested a pair. Ratings are stored per labeler.
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import { useState } from 'react';
import { AppLayout } from '../components/Layout';
import { Badge, Button, Card, Field, Input, Spinner, toast } from '../components/ui';
import { api } from '../lib/api';

function readLabeler() {
  try { return localStorage.getItem('podbae.labeler') ?? ''; } catch { return ''; }
}
const RATING_STYLE: Record<string, string> = { good: 'border-green-600 bg-green-600 text-white', ok: 'border-amber-500 bg-amber-500 text-white', bad: 'border-destructive bg-destructive text-white' };

function ShowBlock({ s, compact }: { s: any; compact?: boolean }) {
  return (
    <div className="space-y-1.5">
      <div className="flex flex-wrap items-center gap-1.5"><b>{s.title}</b>{s.language && <Badge tone="gray">{String(s.language).toUpperCase()}</Badge>}</div>
      {(s.categories ?? []).length > 0 && <div className="flex flex-wrap gap-1">{s.categories.slice(0, 5).map((c: string) => <Badge key={c}>{c}</Badge>)}</div>}
      <p className={`whitespace-pre-line text-xs text-muted-foreground ${compact ? 'line-clamp-3' : ''}`}>{s.description || 'No description'}</p>
      <ul className="list-disc pl-4 text-xs">{(s.episodes ?? []).slice(0, compact ? 3 : 6).map((e: string, i: number) => <li key={i}>{e}</li>)}</ul>
    </div>
  );
}

export default function AdminPairLabels() {
  const qc = useQueryClient();
  const [labeler, setLabeler] = useState(readLabeler);
  const [name, setName] = useState(readLabeler);
  const [idx, setIdx] = useState(0);
  const queue = useQuery({ queryKey: ['a-pairs', labeler], enabled: !!labeler, queryFn: () => api.get(`/api/admin/engine/pairs/queue?labeler=${encodeURIComponent(labeler)}`) });
  const agree = useQuery({ queryKey: ['a-pairs-agree'], queryFn: () => api.get('/api/admin/engine/pairs/agreement') });
  const items: any[] = queue.data?.items ?? [];
  const item = items[idx];
  const rate = async (cand: string, rating: string) => {
    try {
      await api.put('/api/admin/engine/pairs/rate', { memberShowId: item.member.showId, candidateShowId: cand, labeler, rating });
      await qc.invalidateQueries({ queryKey: ['a-pairs'] }); qc.invalidateQueries({ queryKey: ['a-pairs-agree'] });
    } catch (e: any) { toast(e.message); }
  };
  const pick = async () => {
    try { const r = await api.post('/api/admin/engine/pairs/items', { n: 20 }); toast(`${r.count} member shows in the label set`); qc.invalidateQueries({ queryKey: ['a-pairs'] }); }
    catch (e: any) { toast(e.message); }
  };
  const m = agree.data?.metrics;
  return (
    <AppLayout admin>
      <h1 className="mb-1 text-3xl font-extrabold">Pair labels: is this a good partner?</h1>
      <p className="mb-4 max-w-3xl text-sm text-muted-foreground">Each member show is listed with candidate partners suggested by two different systems, mixed together.
        You are not told which system suggested which pair. Rate each pair good / ok / bad. These ratings are the only ground truth for engine-vs-legacy
        quality; machine-written labels are never accepted.</p>
      <Card className="mb-4 flex flex-wrap items-end gap-3">
        <Field label="Your labeler name"><Input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Priya" className="w-60" /></Field>
        <Button size="sm" disabled={!name.trim()} onClick={() => { try { localStorage.setItem('podbae.labeler', name.trim()); } catch { /* private mode */ } setLabeler(name.trim()); setIdx(0); }}>
          {labeler ? 'Switch labeler' : 'Start labelling'}</Button>
        {labeler && <span className="text-sm">Labelling as <b>{labeler}</b> · {queue.data?.done ?? 0} of {queue.data?.total ?? 0} pairs rated</span>}
      </Card>
      {!labeler ? <p className="text-sm text-muted-foreground">Enter your name to begin.</p> : queue.isLoading ? <Spinner /> : queue.error ? (
        <Card className="text-sm text-destructive">Could not load the label set: {(queue.error as any).message}</Card>
      ) : !items.length ? (
        <Card className="space-y-2 text-sm"><p>No label set yet. It freezes the engine's and the legacy scorer's top 5 for 20 member shows.</p>
          <Button size="sm" onClick={pick}>Pick 20 member shows</Button></Card>
      ) : (
        <div className="grid gap-4 lg:grid-cols-[1fr_1.4fr]">
          <Card className="space-y-3 self-start">
            <div className="flex items-center justify-between">
              <Button size="sm" variant="outline" disabled={idx === 0} onClick={() => setIdx(idx - 1)}><ChevronLeft className="h-4 w-4" /></Button>
              <span className="text-sm text-muted-foreground">Member show {idx + 1} of {items.length}</span>
              <Button size="sm" variant="outline" disabled={idx >= items.length - 1} onClick={() => setIdx(idx + 1)}><ChevronRight className="h-4 w-4" /></Button>
            </div>
            <div className="flex flex-wrap gap-1">{items.map((it, i) => {
              const done = it.pairs.every((p: any) => p.rating);
              return <button key={it.member.showId} onClick={() => setIdx(i)} title={it.member.title}
                className={`h-6 w-6 rounded text-[10px] font-semibold ${i === idx ? 'bg-primary text-primary-foreground' : done ? 'bg-green-200 text-green-900 dark:bg-green-900/50 dark:text-green-200' : 'bg-muted'}`}>{i + 1}</button>;
            })}</div>
            <ShowBlock s={item.member} />
          </Card>
          <div className="space-y-3">
            <p className="text-xs text-muted-foreground">{queue.data?.instructions}</p>
            {item.pairs.map((p: any, i: number) => (
              <Card key={p.candidate.showId} className="space-y-2">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0 flex-1"><span className="text-xs text-muted-foreground">Candidate {i + 1}</span><ShowBlock s={p.candidate} compact /></div>
                  <div className="flex shrink-0 gap-1">{['good', 'ok', 'bad'].map((r) => (
                    <button key={r} onClick={() => rate(p.candidate.showId, r)}
                      className={`rounded-md border px-2.5 py-1 text-xs font-medium ${p.rating === r ? RATING_STYLE[r] : 'border-input hover:bg-secondary'}`}>{r}</button>))}</div>
                </div>
              </Card>))}
          </div>
        </div>
      )}
      <Card className="mt-6 space-y-2">
        <h3 className="font-semibold">Agreement and metrics</h3>
        {agree.data?.status !== 'ok' ? <p className="text-sm text-muted-foreground">{agree.data?.message ?? 'Not available yet.'}</p> : (
          <table className="w-full text-sm"><thead><tr className="text-left text-xs text-muted-foreground"><th>Pair</th><th>Shared pairs</th><th>Exact agreement</th><th>Cohen's κ</th></tr></thead>
            <tbody>{agree.data.pairs.map((p: any) => <tr key={`${p.a}-${p.b}`}><td>{p.a} × {p.b}</td><td>{p.shared}</td><td>{p.exactAgreement}</td><td>{p.kappa ?? '–'}</td></tr>)}</tbody></table>)}
        {m?.note ? <p className="text-sm text-muted-foreground">{m.note}</p> : m && (
          <table className="w-full text-sm"><thead><tr className="text-left text-xs text-muted-foreground"><th>System</th><th>Member shows</th><th>Precision@3</th><th>nDCG@5</th><th>Coverage@3</th></tr></thead>
            <tbody>{Object.entries(m.systems ?? {}).map(([k, v]: any) => <tr key={k}><td>{k}</td><td>{v.memberShowsLabelled}</td><td>{v.precisionAt3 ?? '–'}</td><td>{v.ndcgAt5 ?? '–'}</td><td>{v.coverageAt3 ?? '–'}</td></tr>)}</tbody></table>)}
        <p className="text-xs text-muted-foreground">{(agree.data?.labelers ?? []).map((l: any) => `${l.labeler}: ${l.labelled} pairs`).join(' · ')}</p>
      </Card>
    </AppLayout>
  );
}
