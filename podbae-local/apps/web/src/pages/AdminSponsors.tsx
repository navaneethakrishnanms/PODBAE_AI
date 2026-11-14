// Layer 2 admin: /admin/sponsors/review (human review of detections) and /admin/sponsors/brands (brand identity admin).
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { Link } from 'wouter';
import { AppLayout } from '../components/Layout';
import { Badge, Button, Card, Field, Input, Spinner, toast } from '../components/ui';
import { api } from '../lib/api';

const CLASS_HELP: Record<string, string> = {
  declared_sponsorship: 'Explicit sponsor phrase / ad section + brand', likely_sponsorship: 'Promo code / offer / vanity URL, no explicit phrase',
  affiliate: 'Affiliate link', podcast_promo: 'Promotes another podcast', self_promotion: "The show's own merch / Patreon / site",
  network_disclosure: 'Ad-choices / hosting / regulatory boilerplate', organic_mention: 'Named with no commercial cue', uncertain: 'Ambiguous',
};

function readReviewer() {
  try { return localStorage.getItem('podbae.labeler') ?? ''; } catch { return ''; }
}

function SponsorNav() {
  return (
    <div className="mb-4 flex flex-wrap gap-2 text-sm">
      <Link href="/admin/sponsors/review"><Button size="sm" variant="outline">Review queue</Button></Link>
      <Link href="/admin/sponsors/brands"><Button size="sm" variant="outline">Brands</Button></Link>
      <Link href="/admin"><Button size="sm" variant="ghost">Back to admin</Button></Link>
    </div>
  );
}

export function AdminSponsorReview() {
  const qc = useQueryClient();
  const [reviewer, setReviewer] = useState(readReviewer);
  const [name, setName] = useState(readReviewer);
  const [filter, setFilter] = useState('');
  const queue = useQuery({ queryKey: ['a-sp-queue', reviewer, filter], enabled: !!reviewer,
    queryFn: () => api.get(`/api/admin/sponsors/review/queue?reviewer=${encodeURIComponent(reviewer)}${filter ? `&filter=${filter}` : ''}`) });
  const stats = useQuery({ queryKey: ['a-sp-stats'], queryFn: () => api.get('/api/admin/sponsors/stats') });
  const items: any[] = queue.data?.items ?? [];
  const classes: string[] = queue.data?.classes ?? [];
  const review = async (id: number, verdict: string, correctClass?: string) => {
    try { await api.put(`/api/admin/sponsors/review/${id}`, { reviewer, verdict, correctClass }); qc.invalidateQueries({ queryKey: ['a-sp-queue'] }); qc.invalidateQueries({ queryKey: ['a-sp-stats'] }); }
    catch (e: any) { toast(e.message); }
  };
  const prec = stats.data?.review;
  return (
    <AppLayout admin>
      <h1 className="mb-1 text-3xl font-extrabold">Sponsor detections: review</h1>
      <p className="mb-3 max-w-3xl text-sm text-muted-foreground">Every <b>uncertain</b> detection (excluded until reviewed) plus a stratified random sample of
        auto-accepted ones per class. Your verdicts are the only ground truth for detection precision. Machine-written reviews are rejected.</p>
      <SponsorNav />
      <Card className="mb-4 flex flex-wrap items-end gap-3">
        <Field label="Reviewer name"><Input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Priya" className="w-60" /></Field>
        <Button size="sm" disabled={!name.trim()} onClick={() => { try { localStorage.setItem('podbae.labeler', name.trim()); } catch { /* private */ } setReviewer(name.trim()); }}>
          {reviewer ? 'Switch reviewer' : 'Start reviewing'}</Button>
        {reviewer && <span className="text-sm">Reviewing as <b>{reviewer}</b> · {queue.data?.done ?? 0} of {queue.data?.total ?? 0} done</span>}
        <div className="ml-auto flex gap-1">
          <Button size="sm" variant={!filter ? 'default' : 'outline'} onClick={() => setFilter('')}>Review sample</Button>
          <Button size="sm" data-testid="filter-disagree" variant={filter === 'disagree' ? 'default' : 'outline'} onClick={() => setFilter('disagree')}>Rules vs AI disagree</Button>
        </div>
      </Card>
      {filter === 'disagree' && <p className="mb-3 text-xs text-muted-foreground">{queue.data?.instructions} The AI is never a reviewer.</p>}
      {!reviewer ? <p className="text-sm text-muted-foreground">Enter your name to begin.</p> : queue.isLoading ? <Spinner /> : (
        <div className="space-y-2" data-testid="sponsor-review-queue">
          {items.map((it) => (
            <Card key={it.eventId} className="space-y-1.5 py-3">
              <div className="flex flex-wrap items-center gap-2 text-xs">
                <Badge tone={it.queue === 'uncertain' ? 'pink' : 'gray'}>{it.queue}</Badge>
                <Badge>{it.class}</Badge><span className="text-muted-foreground">{CLASS_HELP[it.class]} · rule <code>{it.rule}</code> · {it.method}</span>
              </div>
              <div className="text-sm"><b>{it.show}</b> · {it.episodeTitle} · {it.date} {it.source === 'transcript' && <Badge tone="gray">transcript</Badge>}</div>
              <div className="text-sm italic text-muted-foreground">“{it.snippet}”</div>
              <div className="text-xs">{it.domain && <>domain <b>{it.domain}</b> </>}{it.brandName && <>· name <b>{it.brandName}</b> </>}{it.promoCode && <>· code <b>{it.promoCode}</b></>}</div>
              {it.rulesVsAi && (
                <div data-testid="rules-vs-ai" className="grid gap-2 rounded-md bg-secondary/50 p-2 text-xs sm:grid-cols-2">
                  <div><div className="text-muted-foreground">Rules</div><b>{it.rulesVsAi.ruleClass}</b> <span className="text-muted-foreground">({it.rule})</span></div>
                  <div><div className="text-muted-foreground">AI second opinion {it.rulesVsAi.disagree && <Badge tone="pink">disagrees</Badge>}</div>
                    <b>{it.rulesVsAi.aiClass ?? 'no change'}</b>{it.rulesVsAi.aiSaid && it.rulesVsAi.aiSaid !== it.rulesVsAi.aiClass && <span className="text-muted-foreground"> (model said {it.rulesVsAi.aiSaid}; capped)</span>}
                    {it.rulesVsAi.aiReason && <div className="text-muted-foreground">{it.rulesVsAi.aiReason}</div>}
                    {it.rulesVsAi.aiQuote && <div className="italic">“{it.rulesVsAi.aiQuote}”</div>}</div>
                </div>)}
              <div className="flex flex-wrap items-center gap-1.5 pt-1">
                {it.class !== 'uncertain' && <Button size="sm" variant={it.myVerdict?.verdict === 'ok' && it.myVerdict?.correctClass === it.class ? 'default' : 'outline'} onClick={() => review(it.eventId, 'ok', it.class)}>Correct</Button>}
                <select className="h-9 rounded-md border border-input bg-card px-2 text-xs" value={it.myVerdict?.verdict === 'ok' && it.myVerdict?.correctClass !== it.class ? it.myVerdict.correctClass : ''}
                  onChange={(e) => e.target.value && review(it.eventId, 'ok', e.target.value)}>
                  <option value="">{it.class === 'uncertain' ? 'Pick the right class…' : 'Wrong class: it is…'}</option>
                  {classes.filter((c) => c !== 'uncertain' && c !== it.class).map((c) => <option key={c} value={c}>{c}</option>)}
                </select>
                <Button size="sm" variant={it.myVerdict?.verdict === 'reject' ? 'destructive' : 'ghost'} onClick={() => review(it.eventId, 'reject')}>Not evidence</Button>
                {it.myVerdict && <Badge tone="green">reviewed</Badge>}
              </div>
            </Card>))}
        </div>
      )}
      <Card className="mt-6 space-y-2">
        <h3 className="font-semibold">Precision per class (from reviews)</h3>
        {prec?.note ? <p className="text-sm text-muted-foreground">{prec.note}</p> : (
          <table className="w-full text-sm"><thead><tr className="text-left text-xs text-muted-foreground"><th>Class</th><th>Reviewed</th><th>Correct</th><th>Precision</th></tr></thead>
            <tbody>{Object.entries(prec?.perClass ?? {}).map(([k, v]: any) => <tr key={k}><td>{k}</td><td>{v.reviewed}</td><td>{v.correct}</td><td>{v.precision ?? '–'}</td></tr>)}</tbody></table>)}
        {(prec?.agreement ?? []).map((p: any) => <p key={`${p.a}${p.b}`} className="text-xs">{p.a} × {p.b}: {p.shared} shared, agreement {p.agreement}, κ {p.kappa}</p>)}
      </Card>
    </AppLayout>
  );
}

export function AdminSponsorBrands() {
  const qc = useQueryClient();
  const [q, setQ] = useState('');
  const [status, setStatus] = useState('');
  const [sel, setSel] = useState<string | null>(null);
  const [mergeTarget, setMergeTarget] = useState('');
  const [filter, setFilter] = useState('');
  const list = useQuery({ queryKey: ['a-sp-brands', q, status, filter],
    queryFn: () => api.get(`/api/admin/sponsors/brands?q=${encodeURIComponent(q)}&status=${status}&limit=100${filter ? `&filter=${filter}` : ''}`) });
  const detail = useQuery({ queryKey: ['a-sp-brand', sel], enabled: !!sel, queryFn: () => api.get(`/api/admin/sponsors/brands/${sel}`) });
  const stats = useQuery({ queryKey: ['a-sp-stats'], queryFn: () => api.get('/api/admin/sponsors/stats') });
  const opts: any[] = list.data?.categoryOptions ?? [];
  const refresh = () => { qc.invalidateQueries({ queryKey: ['a-sp-brands'] }); qc.invalidateQueries({ queryKey: ['a-sp-brand'] }); };
  const run = (fn: () => Promise<any>, msg: string) => async () => { try { await fn(); toast(msg); refresh(); } catch (e: any) { toast(e.message); } };
  const b = detail.data;
  const st = stats.data;
  return (
    <AppLayout admin>
      <h1 className="mb-1 text-3xl font-extrabold">Brands</h1>
      <p className="mb-3 max-w-3xl text-sm text-muted-foreground">Brands are identified by registrable domain; a name joins a brand only via the same sentence or a manual mapping, never by name
        similarity. Domains are not verified (no fetching in this phase). Merges, splits and category corrections are audited.</p>
      <SponsorNav />
      {st && (
        <div className="mb-4 flex flex-wrap gap-3">
          {[['Brands', st.brands?.total], ['Active', st.brands?.byStatus?.active], ['Active on ≥2 shows', st.brands?.activeOn2plusShows],
            ['Shows with sponsorship', `${st.coverageSponsorshipHistory?.shows} (${Math.round((st.coverageSponsorshipHistory?.share ?? 0) * 100)}%)`],
            ['Ads exist, no brand visible', `${st.networkDisclosureOnly?.shows} (${Math.round((st.networkDisclosureOnly?.share ?? 0) * 100)}%)`]].map(([l, v]) => (
            <Card key={l as string} className="px-4 py-3"><div className="text-xl font-extrabold text-primary">{v ?? '–'}</div><div className="text-xs text-muted-foreground">{l}</div></Card>))}
        </div>
      )}
      <div className="grid gap-4 lg:grid-cols-[1fr_1.2fr]">
        <Card className="space-y-2" >
          <div className="flex gap-2"><Input placeholder="Search name or domain" value={q} onChange={(e) => setQ(e.target.value)} />
            <select className="h-10 rounded-md border border-input bg-card px-2 text-sm" value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="">all</option><option value="active">active</option><option value="inactive">inactive</option></select></div>
          <div className="flex gap-1">
            <Button size="sm" variant={!filter ? 'default' : 'outline'} onClick={() => setFilter('')}>All brands</Button>
            <Button size="sm" data-testid="brands-filter-disagree" variant={filter === 'disagree' ? 'default' : 'outline'} onClick={() => setFilter('disagree')}>Rules vs AI disagree</Button>
          </div>
          {list.isLoading ? <Spinner /> : (
            <div className="max-h-[70vh] space-y-1 overflow-y-auto" data-testid="brand-list">{(list.data?.brands ?? []).map((x: any) => (
              <button key={x.id} onClick={() => setSel(x.id)} className={`block w-full rounded-md px-2 py-1.5 text-left text-sm hover:bg-secondary ${sel === x.id ? 'bg-secondary' : ''}`}>
                <b>{x.displayName ?? x.name}</b>{x.displayName && x.displayName !== x.name && <span className="text-xs text-muted-foreground"> ({x.name})</span>}
                {' '}<span className="text-xs text-muted-foreground">{x.primaryDomain ?? 'name only'} · {x.nShows} shows · {x.nEvents} events</span>
                {' '}<Badge tone={x.status === 'active' ? 'green' : 'gray'}>{x.status}</Badge>
                {(x.rulesVsAi?.categoriesDisagree || x.rulesVsAi?.namePending) && <>{' '}<Badge tone="pink">AI differs</Badge></>}
              </button>))}</div>)}
          <p className="text-xs text-muted-foreground">{list.data?.total ?? 0} brands with sponsorship evidence</p>
        </Card>
        <Card className="space-y-3">
          {!b ? <p className="text-sm text-muted-foreground">Select a brand.</p> : (
            <>
              <div><h2 className="text-xl font-bold">{b.name}</h2>
                <p className="text-xs text-muted-foreground">{b.identity} · {b.status} · first {b.firstSeen?.slice(0, 10) ?? '–'} · last {b.lastSeen?.slice(0, 10) ?? '–'} · domain verified: {String(b.domainVerified)}{b.registered ? ' · registered PodBae advertiser' : ''}</p></div>
              <div className="text-sm"><b>Domains:</b> {(b.domains ?? []).map((d: any) => (
                <span key={d.domain} className="mr-2">{d.domain} <span className="text-xs text-muted-foreground">({d.source})</span>
                  {b.domains.length > 1 && <button className="ml-1 text-xs text-primary" onClick={run(() => api.post(`/api/admin/sponsors/brands/${b.id}/split`, { domain: d.domain }), 'Split')}>split</button>}</span>))}
                {!b.domains?.length && <span className="text-muted-foreground">none (name-only brand)</span>}</div>
              <div className="text-sm"><b>Aliases:</b> {(b.aliases ?? []).join(', ') || '–'}</div>
              {b.rulesVsAi?.nameSuggestion && (
                <div data-testid="name-suggestion" className="flex flex-wrap items-center gap-2 rounded-md bg-secondary/50 p-2 text-sm">
                  <span>Display name: <b>{b.name}</b> → AI suggests <b>{b.rulesVsAi.nameSuggestion}</b>
                    <span className="text-xs text-muted-foreground"> (exact text in {b.rulesVsAi.nameSupport} snippet{b.rulesVsAi.nameSupport === 1 ? '' : 's'} · {b.rulesVsAi.nameStatus})</span></span>
                  {b.rulesVsAi.nameStatus !== 'approved' && <Button size="sm" onClick={run(() => api.post(`/api/admin/sponsors/brands/${b.id}/name`, { action: 'approve' }), 'Name approved')}>Approve</Button>}
                  {b.rulesVsAi.nameStatus !== 'rejected' && <Button size="sm" variant="ghost" onClick={run(() => api.post(`/api/admin/sponsors/brands/${b.id}/name`, { action: 'reject' }), 'Name rejected')}>Reject</Button>}
                </div>)}
              <div className="text-sm"><b>Categories ({b.categoryMethod}):</b> {(b.categories ?? []).map((c: any) => <Badge key={c.id} tone={c.sensitive ? 'pink' : 'default'} className="mr-1">{c.label}</Badge>)}</div>
              {b.rulesVsAi?.aiCategories && (
                <div data-testid="brand-rules-vs-ai" className="space-y-1 rounded-md bg-secondary/50 p-2 text-xs">
                  <div>AI categories {b.rulesVsAi.categoriesDisagree && <Badge tone="pink">differ from rules</Badge>}
                    {' '}<span className="text-muted-foreground">(used while the AI is on, unless you set categories by hand)</span></div>
                  {(b.rulesVsAi.aiCategories ?? []).length === 0 ? <div className="text-muted-foreground">No category supported by a verbatim quote.</div> :
                    b.rulesVsAi.aiCategories.map((c: any) => <div key={c.id}><Badge tone={c.sensitive ? 'pink' : 'default'}>{c.label}</Badge> <span className="italic">“{c.quote}”</span></div>)}
                  {(b.rulesVsAi.aiCategories ?? []).length > 0 && b.categoryMethod !== 'manual' && (
                    <Button size="sm" variant="outline" onClick={run(() => api.put(`/api/admin/sponsors/brands/${b.id}/categories`, { categories: b.rulesVsAi.aiCategories.map((c: any) => c.id) }), 'AI categories accepted (now manual)')}>Accept AI categories</Button>)}
                </div>)}
              <div className="flex flex-wrap gap-1">{opts.map((c) => {
                const on = (b.categories ?? []).some((x: any) => x.id === c.id);
                return <button key={c.id} className={`rounded-full border px-2 py-0.5 text-xs ${on ? 'border-primary bg-primary text-primary-foreground' : 'border-input'}`}
                  onClick={run(() => api.put(`/api/admin/sponsors/brands/${b.id}/categories`, { categories: on ? b.categories.filter((x: any) => x.id !== c.id).map((x: any) => x.id) : [...(b.categories ?? []).map((x: any) => x.id), c.id] }), 'Categories corrected')}>
                  {c.label}{c.sensitive ? ' *' : ''}</button>;
              })}</div>
              <div className="flex gap-2"><Input placeholder="Merge INTO brand id (brd_…)" value={mergeTarget} onChange={(e) => setMergeTarget(e.target.value)} />
                <Button size="sm" variant="outline" disabled={!mergeTarget} onClick={run(() => api.post('/api/admin/sponsors/brands/merge', { sourceId: b.id, targetId: mergeTarget.trim() }), 'Merged')}>Merge</Button></div>
              <h3 className="pt-2 text-sm font-semibold">Recent events</h3>
              <ul className="max-h-80 space-y-1 overflow-y-auto text-xs">{(b.events ?? []).map((e: any) => (
                <li key={e.eventId} className="border-l-2 border-primary/40 pl-2"><Badge>{e.class}</Badge> <b>{e.show}</b> · {e.episodeTitle} · {e.date}
                  <div className="italic text-muted-foreground">“{e.snippet}”</div></li>))}</ul>
            </>)}
        </Card>
      </div>
    </AppLayout>
  );
}
