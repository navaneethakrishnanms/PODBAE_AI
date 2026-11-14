// Human evaluation labels (Phase 1, Step 7). One show at a time; labels are stored per labeler in the AI service and
// are used ONLY for evaluation (never shown to creators, never fed into profiles).
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { AppLayout } from '../components/Layout';
import { Badge, Button, Card, Field, Input, Spinner, Textarea, toast } from '../components/ui';
import { api } from '../lib/api';

const STYLE_HELP: Record<string, string> = {
  solo_monologue: 'One host talking', co_hosted_banter: 'Two hosts in conversation', interview: 'Host(s) interview a guest',
  panel: 'Three or more regular voices', narrative_storytelling: 'Produced / scripted story or documentary', mixed_or_other: 'Mixed or none of these',
};

function readLabeler() {
  try { return localStorage.getItem('podbae.labeler') ?? ''; } catch { return ''; }
}

export default function AdminLabels() {
  const qc = useQueryClient();
  const [labeler, setLabeler] = useState(readLabeler);
  const [name, setName] = useState(readLabeler);
  const [idx, setIdx] = useState(0);
  const queue = useQuery({ queryKey: ['a-labels', labeler], enabled: !!labeler, queryFn: () => api.get(`/api/admin/intel/labels/queue?labeler=${encodeURIComponent(labeler)}`) });
  const agree = useQuery({ queryKey: ['a-agree'], queryFn: () => api.get('/api/admin/intel/labels/agreement') });
  // Phase 4: optional "Rules vs AI disagree" view. Off by default so labels stay blind; when on, shows with a disagreement
  // come first and the rule + AI answers are shown side by side. Human labels remain the only ground truth.
  const [disagree, setDisagree] = useState(false);
  const cmp = useQuery({ queryKey: ['a-labels-ai'], enabled: !!labeler && disagree, queryFn: () => api.get('/api/admin/llm/labels/disagreements') });
  const cmpBy = useMemo(() => Object.fromEntries((cmp.data?.items ?? []).map((x: any) => [x.showId ?? x.show_id, x])), [cmp.data]);
  const items: any[] = useMemo(() => {
    const base: any[] = queue.data?.items ?? [];
    if (!disagree) return base;
    return [...base].sort((a, b) => Number(!!cmpBy[b.show_id]?.anyDisagree) - Number(!!cmpBy[a.show_id]?.anyDisagree));
  }, [queue.data, disagree, cmpBy]);
  const item = items[idx];
  const ai = disagree && item ? cmpBy[item.show_id] : null;
  const [topics, setTopics] = useState<string[]>([]);
  const [vibes, setVibes] = useState<string[]>([]);
  const [style, setStyle] = useState('');
  const [guest, setGuest] = useState<boolean | null>(null);
  const [notes, setNotes] = useState('');
  const [tq, setTq] = useState('');

  useEffect(() => {   // load this labeler's existing answer for the current show
    const l = item?.label;
    setTopics(l?.topics ?? []); setVibes(l?.vibes ?? []); setStyle(l?.style ?? ''); setGuest(l ? l.guest_friendly : null); setNotes(l?.notes ?? ''); setTq('');
  }, [item?.show_id, item?.label?.updated_at]);

  const groups = useMemo(() => {
    const g: Record<string, any[]> = {};
    for (const t of queue.data?.taxonomy ?? []) if (!tq || `${t.label} ${t.group}`.toLowerCase().includes(tq.toLowerCase())) (g[t.group] ??= []).push(t);
    return g;
  }, [queue.data, tq]);

  const toggle = (arr: string[], set: (v: string[]) => void, v: string, max: number) =>
    set(arr.includes(v) ? arr.filter((x) => x !== v) : arr.length >= max ? arr : [...arr, v]);
  const complete = topics.length >= 1 && vibes.length === 3 && !!style && guest !== null;

  const save = async (next: boolean) => {
    try {
      await api.put(`/api/admin/intel/labels/${item.show_id}`, { labeler, topics, vibes, style, guest_friendly: guest, notes: notes || null });
      toast('Saved');
      await qc.invalidateQueries({ queryKey: ['a-labels'] });
      qc.invalidateQueries({ queryKey: ['a-agree'] });
      if (next && idx < items.length - 1) setIdx(idx + 1);
    } catch (e: any) { toast(e.message); }
  };

  return (
    <AppLayout admin>
      <h1 className="mb-1 text-3xl font-extrabold">Evaluation labels</h1>
      <p className="mb-4 max-w-3xl text-sm text-muted-foreground">
        Label 30 real shows from what is shown here. These human labels are the ground truth for measuring the profile pipeline;
        machine-written drafts are never counted. Two or more labelers make agreement measurable.
      </p>
      <Card className="mb-4 flex flex-wrap items-end gap-3">
        <Field label="Your labeler name"><Input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Priya" className="w-60" /></Field>
        <Button size="sm" disabled={!name.trim()} onClick={() => { try { localStorage.setItem('podbae.labeler', name.trim()); } catch { /* private mode */ } setLabeler(name.trim()); setIdx(0); }}>
          {labeler ? 'Switch labeler' : 'Start labelling'}</Button>
        {labeler && <span className="text-sm">Labelling as <b>{labeler}</b> · {queue.data?.done ?? 0} of {queue.data?.total ?? 0} done</span>}
        {labeler && (
          <label className="ml-auto flex items-center gap-2 text-sm" data-testid="labels-filter-disagree">
            <input type="checkbox" checked={disagree} onChange={(e) => { setDisagree(e.target.checked); setIdx(0); }} />
            Rules vs AI disagree first (shows both answers; labels are no longer blind)
          </label>)}
      </Card>

      {!labeler ? <p className="text-sm text-muted-foreground">Enter your name to begin.</p> : queue.isLoading ? <Spinner /> : queue.error ? (
        <Card className="text-sm text-destructive">Could not load the label set: {(queue.error as any).message}</Card>
      ) : !items.length ? <Card className="text-sm">No label set yet. Run <code>npm run intel:seed</code> (it picks 30 shows).</Card> : (
        <div className="grid gap-4 lg:grid-cols-[1fr_1.1fr]">
          <Card className="space-y-3">
            <div className="flex items-center justify-between">
              <Button size="sm" variant="outline" disabled={idx === 0} onClick={() => setIdx(idx - 1)}><ChevronLeft className="h-4 w-4" /></Button>
              <span className="text-sm text-muted-foreground">Show {idx + 1} of {items.length} · {item.category}</span>
              <Button size="sm" variant="outline" disabled={idx >= items.length - 1} onClick={() => setIdx(idx + 1)}><ChevronRight className="h-4 w-4" /></Button>
            </div>
            <div className="flex flex-wrap gap-1">{items.map((it, i) => (
              <button key={it.show_id} onClick={() => setIdx(i)} title={it.title}
                className={`h-6 w-6 rounded text-[10px] font-semibold ${i === idx ? 'bg-primary text-primary-foreground' : it.label ? 'bg-green-200 text-green-900 dark:bg-green-900/50 dark:text-green-200' : 'bg-muted'}`}>{i + 1}</button>))}</div>
            <h2 className="text-xl font-bold">{item.title}</h2>
            {ai && (
              <div data-testid="labels-rules-vs-ai" className="grid gap-1 rounded-md bg-secondary/50 p-2 text-xs sm:grid-cols-3">
                {[['Style', ai.style?.rule ?? '–', ai.style?.ai ?? '– (not refined)', ai.style?.disagree],
                  ['Topics', (ai.topics?.rule ?? []).join(', ') || '–', ai.topics?.ai ? `+ ${(ai.topics.aiAdded ?? []).join(', ') || 'none'}` : '– (not refined)', ai.topics?.disagree],
                  ['Guest-friendly', `${ai.guest?.rule ?? '–'} (${ai.guest?.ruleShare ?? '–'})`, ai.guest?.ai == null ? '– (not refined)' : `${ai.guest.ai} (${ai.guest.aiShare})`, ai.guest?.disagree]]
                  .map(([k, r, a, d]: any) => (
                    <div key={k}><div className="font-semibold">{k} {d && <Badge tone="pink">disagree</Badge>}</div>
                      <div>Rules: <b>{r}</b></div><div>AI: <b>{a}</b></div></div>))}
                <p className="text-muted-foreground sm:col-span-3">Label what YOU see in the show text. Your label is the ground truth; neither answer is.</p>
              </div>)}
            {item.categories?.length > 0 && <div className="flex flex-wrap gap-1">{item.categories.map((c: string) => <Badge key={c} tone="gray">{c}</Badge>)}</div>}
            <p className="whitespace-pre-line text-sm">{item.description || <i className="text-muted-foreground">No description</i>}</p>
            <div>
              <h3 className="mb-1 text-sm font-semibold">Latest episodes</h3>
              <ul className="space-y-1.5 text-sm">{item.episodes.map((e: any, i: number) => (
                <li key={i}><b>{e.title}</b>{e.description && <span className="block text-xs text-muted-foreground">{e.description}</span>}</li>))}</ul>
            </div>
          </Card>

          <Card className="space-y-4">
            <p className="text-xs text-muted-foreground">{queue.data?.instructions}</p>
            <div>
              <h3 className="mb-1 text-sm font-semibold">Topics <span className="font-normal text-muted-foreground">(1–5) · {topics.length} selected</span></h3>
              <Input placeholder="Filter topics…" value={tq} onChange={(e) => setTq(e.target.value)} className="mb-2" />
              <div className="max-h-56 space-y-2 overflow-y-auto pr-1">{Object.entries(groups).map(([g, ts]) => (
                <div key={g}><div className="text-[11px] font-semibold uppercase text-muted-foreground">{g}</div>
                  <div className="flex flex-wrap gap-1">{ts.map((t: any) => (
                    <button key={t.id} onClick={() => toggle(topics, setTopics, t.id, 5)}
                      className={`rounded-full border px-2 py-0.5 text-xs ${topics.includes(t.id) ? 'border-primary bg-primary text-primary-foreground' : 'border-input'}`}>{t.label}</button>))}</div></div>))}</div>
            </div>
            <div>
              <h3 className="mb-1 text-sm font-semibold">Top-3 vibes <span className="font-normal text-muted-foreground">(exactly 3) · {vibes.length}/3</span></h3>
              <div className="flex flex-wrap gap-1">{(queue.data?.vibes ?? []).map((v: string) => (
                <button key={v} onClick={() => toggle(vibes, setVibes, v, 3)}
                  className={`rounded-full border px-2 py-0.5 text-xs ${vibes.includes(v) ? 'border-primary bg-primary text-primary-foreground' : 'border-input'}`}>{v}</button>))}</div>
            </div>
            <div>
              <h3 className="mb-1 text-sm font-semibold">Conversational style</h3>
              <div className="grid gap-1 sm:grid-cols-2">{(queue.data?.styles ?? []).map((s: string) => (
                <label key={s} className="flex cursor-pointer items-start gap-2 text-sm"><input type="radio" name="style" checked={style === s} onChange={() => setStyle(s)} className="mt-1" />
                  <span>{s.replace(/_/g, ' ')}<span className="block text-xs text-muted-foreground">{STYLE_HELP[s]}</span></span></label>))}</div>
            </div>
            <div>
              <h3 className="mb-1 text-sm font-semibold">Guest-friendly?</h3>
              <div className="flex gap-4 text-sm">
                <label className="flex items-center gap-1"><input type="radio" name="guest" checked={guest === true} onChange={() => setGuest(true)} />Yes, guests appear regularly</label>
                <label className="flex items-center gap-1"><input type="radio" name="guest" checked={guest === false} onChange={() => setGuest(false)} />No</label>
              </div>
            </div>
            <Field label="Notes (optional)"><Textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={2} /></Field>
            <div className="flex gap-2">
              <Button disabled={!complete} onClick={() => save(true)}>Save & next</Button>
              <Button variant="outline" disabled={!complete} onClick={() => save(false)}>Save</Button>
              {item.label && <Badge tone="green">labelled</Badge>}
            </div>
          </Card>
        </div>
      )}

      <Card className="mt-6">
        <h3 className="mb-2 font-semibold">Agreement between labelers</h3>
        {agree.data?.status !== 'ok' ? <p className="text-sm text-muted-foreground">{agree.data?.message ?? 'Not available yet.'}</p> : (
          <table className="w-full text-sm"><thead><tr className="text-left text-xs text-muted-foreground">
            <th>Pair</th><th>Shared shows</th><th>Style κ</th><th>Guest κ</th><th>Topics Jaccard</th><th>Topic groups Jaccard</th><th>Vibes Jaccard</th></tr></thead>
            <tbody>{agree.data.pairs.map((p: any) => (
              <tr key={`${p.a}-${p.b}`}><td>{p.a} × {p.b}</td><td>{p.shared}</td><td>{p.style_kappa ?? '–'}</td><td>{p.guest_kappa ?? '–'}</td>
                <td>{p.topics_jaccard ?? '–'}</td><td>{p.topic_groups_jaccard ?? '–'}</td><td>{p.vibes_jaccard ?? '–'}</td></tr>))}</tbody></table>
        )}
        <div className="mt-2 text-xs text-muted-foreground">{(agree.data?.labelers ?? []).map((l: any) => `${l.labeler}: ${l.labelled}/${l.of}`).join(' · ')}</div>
      </Card>
    </AppLayout>
  );
}
