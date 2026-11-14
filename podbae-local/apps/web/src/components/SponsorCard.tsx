// Layer 2 sponsor opportunity (type = sponsor, same engine as podcast partners). Four measures shown SEPARATELY:
// Fit (draft Vibe Logic) · Evidence confidence · Commercial status · Conversion (not enough data yet) + contact status.
// No outreach: "Mark as contacted" only logs that the member reached out themselves. No person / e-mail is ever shown.
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { AlertTriangle, Bookmark, CheckCircle2, ExternalLink, Lock, Megaphone, Sparkles, X } from 'lucide-react';
import { useState } from 'react';
import { useLocation } from 'wouter';
import { api } from '../lib/api';
import { Breakdown, Measure, ExplanationText } from './OpportunityCard';
import { Badge, Button, Card, Dialog, Empty, Spinner, toast } from './ui';

export const SPONSOR_DISMISS_REASONS: [string, string][] = [
  ['not_my_audience', 'Not my audience'], ['category_conflict', 'Category conflict'], ['too_big', 'Too big'],
  ['already_contacted', 'Already contacted'], ['other', 'Other'],
];
const LEVEL_TONE: Record<string, string> = { High: 'text-green-600', Medium: 'text-amber-600', Low: 'text-muted-foreground' };
const READY_TONE: Record<string, string> = { verified: 'text-green-600', potential_lead: 'text-blue-600', discovery_lead: 'text-muted-foreground' };
const CLASS_LABEL: Record<string, string> = { declared_sponsorship: 'declared', likely_sponsorship: 'likely (promo code / offer)' };

export function SponsorCard({ o, readOnly }: { o: any; readOnly?: boolean }) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [dismissing, setDismissing] = useState(false);
  const [reason, setReason] = useState('');
  const t = o.target ?? {};
  const cs = o.contactStatus ?? {};
  const ready = o.readiness ?? {};
  const why = (o.whyNow ?? [])[0];
  const events: any[] = o.evidence?.events ?? [];
  const act = useMutation({
    mutationFn: (b: { action: string; reason?: string }) => api.post(`/api/opportunities/${o.id}/action`, b),
    onSuccess: (_r, b) => {
      toast(b.action === 'save' ? 'Saved' : b.action === 'unsave' ? 'Removed from saved' : b.action === 'dismiss'
        ? 'Dismissed. We will not suggest this brand again for a while.' : 'Marked as contacted. PodBae did not contact the brand.');
      setDismissing(false);
      for (const k of ['sponsors', 'matches', 'predictions']) qc.invalidateQueries({ queryKey: [k] });
    },
    onError: (e: Error) => toast(e.message),
  });
  return (
    <Card className="flex flex-col">
      <div data-testid="sponsor-card" className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-1.5">
            <Megaphone className="h-4 w-4 text-primary" />
            <h3 className="truncate font-semibold">{t.name}</h3>
            <Badge tone="pink">sponsor</Badge>
            {(t.categories ?? []).slice(0, 2).map((c: string) => <Badge key={c} tone="gray">{c}</Badge>)}
          </div>
          <p className="mt-0.5 text-xs text-muted-foreground">{t.domain ?? 'no website on record'} · {o.evidence?.nShows ?? 0} show(s), {o.evidence?.nEvents ?? 0} sponsored episode(s) seen</p>
        </div>
        {o.saved && <Bookmark className="h-4 w-4 shrink-0 fill-primary text-primary" aria-label="Saved" />}
      </div>

      <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
        <Measure title="Fit" value={`${Math.round(o.fit?.value ?? 0)}`} sub={o.fit?.note} tone="text-primary" />
        <Measure title="Evidence confidence" value={o.confidence?.level ?? '—'} sub={`${Math.round((o.confidence?.value ?? 0) * 100)}% · how solid the sponsorship evidence is`} tone={LEVEL_TONE[o.confidence?.level]} />
        <Measure title="Commercial status" value={ready.label ?? '—'} sub={ready.reason} tone={READY_TONE[ready.level]} />
        <Measure title="Conversion" value="Not enough data yet" sub="No sponsorship outcomes recorded yet" tone="text-muted-foreground text-sm" />
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
        <span className="text-muted-foreground">Contact status:</span>
        {cs.status === 'registered' ? <Badge tone="green">{cs.label}</Badge> : <Badge tone="gray">{cs.label ?? 'No contact known'}</Badge>}
        {cs.website && <a className="inline-flex items-center gap-1 text-primary hover:underline" href={cs.website} target="_blank" rel="noopener noreferrer nofollow"><ExternalLink className="h-3 w-3" />{t.domain}</a>}
      </div>

      <ExplanationText o={o} />
      {why && (
        <div className="mt-2 flex gap-2 rounded-lg bg-primary/10 p-2 text-xs"><Sparkles className="mt-0.5 h-3.5 w-3.5 shrink-0 text-primary" />
          <div><b>Why now: {why.label}.</b>{why.evidence?.[0]?.show && <> {why.evidence[0].show}: “{why.evidence[0].title}” ({why.evidence[0].date})</>}</div></div>
      )}
      {events.length > 0 && (
        <details className="mt-2 text-xs" open>
          <summary className="cursor-pointer font-medium">Evidence ({events.length} of {o.evidence?.nEvents})</summary>
          <ul className="mt-1 space-y-1.5">{events.slice(0, 4).map((e: any) => (
            <li key={e.eventId} className="border-l-2 border-primary/40 pl-2">
              <div><b>{e.show}</b> · {e.episodeTitle || 'episode'} · {e.date} · <Badge tone={e.class === 'declared_sponsorship' ? 'green' : 'gray'}>{CLASS_LABEL[e.class] ?? e.class}{e.reviewed ? ', reviewed' : ''}</Badge></div>
              <div className="italic text-muted-foreground">“{e.snippet}”</div>
              {e.url && <a className="text-primary hover:underline" href={e.url} target="_blank" rel="noopener noreferrer nofollow">ad link</a>}
            </li>))}</ul>
        </details>
      )}
      <button className="mt-2 self-start text-xs font-medium text-purple-600" onClick={() => setOpen(!open)}>{open ? 'Hide' : 'Show'} breakdown</button>
      {open && <Breakdown o={o} />}

      {!readOnly && (
        <div className="mt-4 flex flex-wrap gap-2">
          <Button size="sm" variant="outline" disabled={act.isPending} onClick={() => act.mutate({ action: o.saved ? 'unsave' : 'save' })}>
            <Bookmark className="h-3.5 w-3.5" />{o.saved ? 'Saved' : 'Save'}</Button>
          <Button size="sm" variant="outline" onClick={() => setDismissing(true)}><X className="h-3.5 w-3.5" />Dismiss</Button>
          <Button size="sm" disabled={act.isPending} onClick={() => act.mutate({ action: 'contacted' })}><CheckCircle2 className="h-3.5 w-3.5" />Mark as contacted</Button>
        </div>
      )}
      <Dialog open={dismissing} onOpenChange={setDismissing} title={`Dismiss ${t.name}?`}>
        <p className="mb-3 text-sm text-muted-foreground">Tell us why. We stop suggesting this brand to you right away.</p>
        <div className="grid grid-cols-2 gap-2">{SPONSOR_DISMISS_REASONS.map(([k, l]) => (
          <label key={k} className={`flex cursor-pointer items-center gap-2 rounded-lg border p-2 text-sm ${reason === k ? 'border-primary bg-primary/10' : ''}`}>
            <input type="radio" name={`sdismiss-${o.id}`} checked={reason === k} onChange={() => setReason(k)} />{l}</label>))}</div>
        <Button className="mt-4 w-full" disabled={!reason || act.isPending} onClick={() => act.mutate({ action: 'dismiss', reason })}>Dismiss</Button>
      </Dialog>
    </Card>
  );
}

/** Sponsor section: locked (Flirt) / ok / few / no-match / generating / not connected / outdated (AI down). Never padded. */
export function SponsorPanel({ data, loading }: { data: any; loading?: boolean }) {
  const [, nav] = useLocation();
  if (loading) return <Spinner />;
  if (!data) return null;
  const items: any[] = data.items ?? [];
  return (
    <section className="space-y-3" data-testid="sponsor-panel">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-lg font-semibold">Sponsors <span className="text-sm font-normal text-muted-foreground">brands that sponsor shows like yours</span></h2>
        {data.scoringVersion && <span className="text-xs text-muted-foreground">{data.scoringVersion} — pending founder approval</span>}
      </div>
      {data.state === 'locked' && (
        <Card className="flex items-start gap-3 bg-secondary/40"><Lock className="mt-0.5 h-4 w-4 text-primary" />
          <div className="text-sm"><b>Sponsor recommendations are locked on your plan.</b> <span className="text-muted-foreground">{data.message}</span></div></Card>
      )}
      {data.outdated && (
        <p className="flex items-center gap-2 rounded-lg bg-amber-500/15 p-3 text-sm text-amber-700 dark:text-amber-300">
          <AlertTriangle className="h-4 w-4 shrink-0" />{data.message ?? 'Showing your last saved sponsor cards; they may be outdated.'}</p>
      )}
      {data.state === 'not_connected' && <Empty>Connect your RSS feed on the Intelligence page to see sponsor opportunities. <button className="text-primary underline" onClick={() => nav('/intelligence')}>Connect</button></Empty>}
      {data.state === 'generating' && <Empty>Looking for sponsors seen on shows like yours… refresh in a moment.</Empty>}
      {data.state === 'ai_unavailable' && <Empty>{data.message}</Empty>}
      {(data.state === 'few' || data.state === 'no_match') && !data.outdated && (
        <Card className="space-y-2 bg-secondary/40">
          <p className="text-sm">{data.message}</p>
          {(data.suggestions ?? []).length > 0 && <ul className="space-y-1 text-sm">{data.suggestions.map((s: any) => (
            <li key={s.code}><b>{s.action}</b> <span className="text-muted-foreground">— {s.detail}</span></li>))}</ul>}
        </Card>
      )}
      {data.limited && <p className="rounded-lg bg-primary/10 p-3 text-sm">Your plan shows up to {data.dailyLimit} sponsor opportunities per day ({data.totalQualified} qualify). Upgrade to Commit to see all.</p>}
      {items.length > 0 && <div className="grid gap-4 lg:grid-cols-2">{items.map((o) => <SponsorCard key={o.id} o={o} readOnly={data.outdated} />)}</div>}
    </section>
  );
}

/** Public "Sponsors seen": declared or human-reviewed sponsorships only. */
export function SponsorsSeen({ data }: { data: any }) {
  const list: any[] = data?.sponsors ?? [];
  return (
    <div data-testid="sponsors-seen">
      <h4 className="text-sm font-semibold">Sponsors seen</h4>
      {!list.length ? <p className="text-xs text-muted-foreground">No declared sponsors in this show's notes. Dynamic ads inserted by hosting networks are not visible to us.</p> : (
        <ul className="mt-1 space-y-1 text-xs">{list.slice(0, 8).map((x) => (
          <li key={x.brandId}><b>{x.name}</b>{x.domain && <span className="text-muted-foreground"> · {x.domain}</span>} · {x.episodes} episode(s), last {x.lastSeen}{x.reviewed && <Badge tone="green" className="ml-1">reviewed</Badge>}</li>))}</ul>
      )}
      {data?.basis && <p className="mt-1 text-[11px] text-muted-foreground">{data.basis}</p>}
    </div>
  );
}
