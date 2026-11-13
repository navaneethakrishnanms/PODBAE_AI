import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Send } from 'lucide-react';
import { useState } from 'react';
import { useLocation } from 'wouter';
import { AppLayout } from '../components/Layout';
import { MatchCard, type MatchRow } from '../components/MatchCard';
import { OpportunitiesPanel } from '../components/OpportunityCard';
import { Badge, Button, Card, Dialog, Empty, Input, Spinner, Tabs, toast } from '../components/ui';
import { api, ApiError } from '../lib/api';
import { useMe } from '../lib/auth';

const TYPES = ['all', 'podcast', 'sponsor', 'guest', 'venue', 'collaborator'];
const PLAN_INFO: Record<string, { label: string; price: string; perks: string }> = {
  date: { label: 'Date', price: '$19/mo', perks: 'More daily recommendations, limited revenue recommendations, ad-free.' },
  commit: { label: 'Commit', price: '$29/mo', perks: 'All recommendations, Hey Bae AI agent, opportunity forecasting.' },
};

function TierBanner() {
  const { me } = useMe();
  const [, nav] = useLocation();
  const [plan, setPlan] = useState<'date' | 'commit' | null>(null);
  const cfg = useQuery({ queryKey: ['tier'], queryFn: () => api.get('/api/tier/config') });
  const checkout = useMutation({
    mutationFn: (tier: string) => api.post('/api/create-checkout', { tier }),
    onSuccess: (r: any) => nav(r.checkoutUrl),
    onError: (e: Error) => toast(e.message),
  });
  if (!me || me.role === 'admin') return null;
  const c = cfg.data;
  return (
    <Card className="mb-6 flex flex-wrap items-center justify-between gap-3">
      <div className="text-sm">
        Plan: <Badge tone="pink">{me.tier}</Badge>
        {c && <span className="ml-3 text-muted-foreground">Swipes today: {c.quotaUsed}/{c.quotaLimit < 0 ? '∞' : c.quotaLimit} · Matches/day: {c.matchesPerDay < 0 ? 'all' : c.matchesPerDay}</span>}
      </div>
      {(me.tier === 'flirt' || me.tier === 'date') && (
        <div className="flex gap-2">
          {me.tier === 'flirt' && <Button size="sm" variant="outline" onClick={() => setPlan('date')}>Upgrade to Date $19</Button>}
          <Button size="sm" onClick={() => setPlan('commit')}>Upgrade to Commit $29</Button>
        </div>
      )}
      <Dialog open={!!plan} onOpenChange={(o) => !o && setPlan(null)} title={plan ? `Upgrade to ${PLAN_INFO[plan].label}` : ''}>
        {plan && (
          <div className="space-y-4">
            <p className="text-sm text-muted-foreground">{PLAN_INFO[plan].perks}</p>
            <p className="text-2xl font-extrabold">{PLAN_INFO[plan].price}</p>
            <p className="text-xs text-muted-foreground">Local demo: you'll be sent to a mock checkout page. No real payment.</p>
            <Button className="w-full" disabled={checkout.isPending} onClick={() => checkout.mutate(plan)}>Continue to checkout</Button>
          </div>
        )}
      </Dialog>
    </Card>
  );
}

function Predictions() {
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({ queryKey: ['predictions'], queryFn: () => api.get('/api/predictions?status=new') });
  const act = useMutation({
    mutationFn: ({ id, action }: { id: number; action: string }) => api.post(`/api/predictions/${id}/action`, { action }),
    onSuccess: (_r, v) => { toast(v.action === 'act' ? 'Marked as acted ✅' : v.action === 'save' ? 'Saved' : 'Dismissed'); qc.invalidateQueries({ queryKey: ['predictions'] }); },
  });
  if (isLoading) return <Spinner />;
  const rows: any[] = data?.predictions ?? [];
  return (
    <div className="space-y-4">
      {data?.partnerOpportunities && <OpportunitiesPanel data={data.partnerOpportunities} />}
      {data?.partnerOpportunities && <h2 className="pt-2 text-lg font-semibold">Other opportunities</h2>}
      {data?.forecast && (
        <Card className="bg-gradient-to-r from-primary/10 to-purple-500/10">
          <h3 className="font-semibold">📈 Opportunity forecast</h3>
          <p className="text-sm text-muted-foreground">{data.forecast.openOpportunities} open opportunities · sponsor budget floor across matched campaigns: <b className="text-foreground">${data.forecast.sponsorBudgetFloor}</b></p>
        </Card>
      )}
      {data?.forecastLocked && <p className="rounded-lg bg-primary/10 p-3 text-sm">🔒 Opportunity forecasting is part of the Commit plan.</p>}
      {data?.lockedRevenue > 0 && <p className="rounded-lg bg-primary/10 p-3 text-sm">💸 {data.lockedRevenue} sponsor (revenue) recommendation(s) hidden on your plan. Upgrade to unlock.</p>}
      {!rows.length ? <Empty>No new predictions. Run matching from the Matches tab.</Empty> : (
        <div className="grid gap-4 md:grid-cols-2">
          {rows.map((p) => (
            <Card key={p.id}>
              <div className="flex justify-between gap-2"><h3 className="font-semibold">{p.title}</h3><span className="font-bold text-primary">{Math.round(p.score)}</span></div>
              <p className="mt-2 text-sm">{p.why}</p>
              <p className="mt-1 text-xs text-muted-foreground"><b>Why now:</b> {p.whyNow}</p>
              <p className="mt-1 text-xs text-muted-foreground">Evidence: {(p.evidence ?? []).map((e: any) => `${e.source}#${e.ref}`).join(', ')}</p>
              <div className="mt-3 flex gap-2">
                <Button size="sm" variant="outline" onClick={() => act.mutate({ id: p.id, action: 'save' })}>Save</Button>
                <Button size="sm" onClick={() => act.mutate({ id: p.id, action: 'act' })}>Act</Button>
                <Button size="sm" variant="ghost" onClick={() => act.mutate({ id: p.id, action: 'dismiss' })}>Dismiss</Button>
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}

function Matches({ saved }: { saved?: boolean }) {
  const qc = useQueryClient();
  const [, nav] = useLocation();
  const [type, setType] = useState('all');
  const { data, isLoading } = useQuery({
    queryKey: saved ? ['saved'] : ['matches', type],
    queryFn: () => api.get(saved ? '/api/member/saved-matches' : `/api/member/matches${type === 'all' ? '' : `?type=${type}`}`),
  });
  const refetchAll = () => { qc.invalidateQueries({ queryKey: ['matches'] }); qc.invalidateQueries({ queryKey: ['saved'] }); };
  const act = useMutation({
    mutationFn: ({ matchId, action }: { matchId: number; action: string }) => api.post('/api/matches/action', { matchId, action }),
    onSuccess: refetchAll,
  });
  const rerun = useMutation({
    mutationFn: () => api.post('/api/run-enhanced-matching'),
    onSuccess: (r: any) => { toast(`Matching done: ${r.count} scored`); refetchAll(); qc.invalidateQueries({ queryKey: ['predictions'] }); },
    onError: (e: Error) => toast(e.message),
  });
  if (isLoading) return <Spinner />;
  const rows: MatchRow[] = data?.matches ?? [];
  return (
    <div className="space-y-4">
      {!saved && (
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex flex-wrap gap-1">
            {TYPES.map((t) => (
              <button key={t} onClick={() => setType(t)} className={`rounded-full border px-3 py-1 text-xs font-medium capitalize ${type === t ? 'border-primary bg-primary text-primary-foreground' : 'bg-card'}`}>{t}</button>
            ))}
          </div>
          <Button size="sm" variant="outline" onClick={() => rerun.mutate()} disabled={rerun.isPending}>Run matching</Button>
        </div>
      )}
      {!saved && data?.opportunities && <OpportunitiesPanel data={data.opportunities} />}
      {!saved && data?.opportunities && type !== 'podcast' && <h2 className="pt-2 text-lg font-semibold">Sponsors, guests, venues &amp; collaborators</h2>}
      {!saved && data?.limited && (
        <p className="rounded-lg bg-primary/10 p-3 text-sm">Your plan shows {data.matchesPerDay} matches per day ({data.total} found). Upgrade to see more.</p>
      )}
      {!rows.length ? (type === 'podcast' && data?.opportunities ? null : <Empty>No matches here yet.</Empty>) : (
        <div className="grid gap-4 md:grid-cols-2">
          {rows.map((m) => (
            <MatchCard key={m.id} m={{ ...m, saved: saved || m.saved }}
              onSave={() => act.mutate({ matchId: m.id, action: m.saved || saved ? 'unsave' : 'save' })}
              onDismiss={saved ? undefined : () => act.mutate({ matchId: m.id, action: 'dismiss' })}
              onOpenChat={m.targetUserId ? () => nav('/messages') : undefined} />
          ))}
        </div>
      )}
    </div>
  );
}

function Insights() {
  const ins = useQuery({ queryKey: ['insights'], queryFn: () => api.get('/api/member/insights') });
  if (ins.isLoading) return <Spinner />;
  const i = ins.data;
  return (
    <div className="grid gap-4 md:grid-cols-2">
      <Card><h3 className="mb-2 font-semibold">Matches by type</h3>
        {(i?.byType ?? []).map((t: any) => <div key={t.targetType} className="flex justify-between text-sm"><span className="capitalize">{t.targetType}</span><span>{t.n} · avg {t.avgScore}</span></div>)}
        <p className="mt-3 text-sm text-muted-foreground">Saved: {i?.savedCount} · Mutual: {i?.mutualCount}</p></Card>
      <Card><h3 className="mb-2 font-semibold">Top matches</h3>
        {(i?.topMatches ?? []).map((t: any) => <div key={t.id} className="flex justify-between text-sm"><span>{t.name}</span><b>{Math.round(t.totalScore)}%</b></div>)}</Card>
    </div>
  );
}

function Reach() {
  const reach = useQuery({ queryKey: ['reach'], queryFn: () => api.get('/api/member/reach-estimate') });
  if (reach.isLoading) return <Spinner />;
  const r = reach.data;
  return (
    <Card><h3 className="mb-1 font-semibold">Reach estimate</h3>
      <p className="mb-4 text-xs text-muted-foreground">Derived from real rows only ({r?.basis}); no invented audience numbers.</p>
      <div className="grid grid-cols-2 gap-3 text-center sm:grid-cols-5">
        {[['Partner shows', r?.partnerShows], ['Sponsors', r?.sponsors], ['Guests', r?.guests], ['Venues', r?.venues], ['Sponsor budget floor', `$${r?.sponsorBudgetFloor ?? 0}`]].map(([l, v]) => (
          <div key={l as string}><div className="text-2xl font-bold text-primary">{v}</div><div className="text-xs text-muted-foreground">{l}</div></div>
        ))}
      </div></Card>
  );
}

function HeyBae() {
  const qc = useQueryClient();
  const { me } = useMe();
  const [msg, setMsg] = useState('');
  const hist = useQuery({ queryKey: ['heybae'], queryFn: () => api.get('/api/hey-bae/messages') });
  const send = useMutation({
    mutationFn: (m: string) => api.post('/api/hey-bae/chat', { message: m }),
    onSuccess: () => { setMsg(''); qc.invalidateQueries({ queryKey: ['heybae'] }); },
    onError: (e: unknown) => toast(e instanceof ApiError && e.data?.code === 'upgrade_required' ? 'Hey Bae needs the Commit plan' : (e as Error).message),
  });
  const locked = me && !['commit', 'premium'].includes(me.tier);
  return (
    <Card>
      <h3 className="mb-3 font-semibold">Hey Bae 💬</h3>
      {locked && <p className="mb-3 rounded-lg bg-primary/10 p-3 text-sm">🔒 Hey Bae is a Commit-plan feature. Use “Upgrade to Commit” above to unlock.</p>}
      <div className="mb-3 max-h-80 min-h-[120px] space-y-2 overflow-y-auto">
        {(hist.data?.messages ?? []).map((m: any) => (
          <div key={m.id} className={`max-w-[85%] whitespace-pre-wrap rounded-xl px-3 py-2 text-sm ${m.role === 'user' ? 'ml-auto bg-primary text-primary-foreground' : 'bg-secondary'}`}>{m.content}</div>
        ))}
        {send.isPending && <div className="text-xs text-muted-foreground">Hey Bae is typing…</div>}
      </div>
      <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); if (msg.trim()) send.mutate(msg); }}>
        <Input value={msg} onChange={(e) => setMsg(e.target.value)} placeholder="Ask about your matches…" />
        <Button disabled={send.isPending} aria-label="Send"><Send className="h-4 w-4" /></Button>
      </form>
    </Card>
  );
}

function Notifications() {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ['notifications'], queryFn: () => api.get('/api/notifications') });
  const list: any[] = data?.notifications ?? [];
  if (!list.length) return null;
  const read = async (id: number) => { await api.post(`/api/notifications/${id}/read`); qc.invalidateQueries({ queryKey: ['notifications'] }); };
  return (
    <Card className="mb-6">
      <div className="mb-2 flex justify-between"><h3 className="text-sm font-semibold">Notifications</h3>
        <button className="text-xs text-primary" onClick={async () => { await api.post('/api/notifications/read-all'); qc.invalidateQueries({ queryKey: ['notifications'] }); }}>Mark all read</button></div>
      {list.slice(0, 5).map((n) => (
        <button key={n.id} onClick={() => !n.read && read(n.id)} className={`block w-full text-left text-sm ${n.read ? 'text-muted-foreground' : 'font-medium'}`}>
          {!n.read && <span className="mr-2 inline-block h-2 w-2 rounded-full bg-primary" />}{n.title}
        </button>
      ))}
    </Card>
  );
}

export default function Dashboard() {
  const [tab, setTab] = useState('predictions');
  const { me } = useMe();
  return (
    <AppLayout>
      <h1 className="mb-1 text-3xl font-bold">Hi{me?.name ? `, ${me.name.split(' ')[0]}` : ''} 👋</h1>
      <p className="mb-6 text-muted-foreground">Your matchmaking command center.</p>
      <TierBanner />
      <Notifications />
      <Tabs value={tab} onChange={setTab} tabs={[
        { id: 'predictions', label: 'Predictions' }, { id: 'matches', label: 'Matches' }, { id: 'saved', label: 'Saved' },
        { id: 'insights', label: 'Insights' }, { id: 'reach', label: 'Reach Estimate' }, { id: 'heybae', label: 'Hey Bae' },
      ]} />
      <div className="pt-6">
        {tab === 'predictions' && <Predictions />}
        {tab === 'matches' && <Matches />}
        {tab === 'saved' && <Matches saved />}
        {tab === 'insights' && <Insights />}
        {tab === 'reach' && <Reach />}
        {tab === 'heybae' && <HeyBae />}
      </div>
    </AppLayout>
  );
}
