// Layer 4 podcast-partner opportunity. Four measures are shown SEPARATELY and never merged:
// Fit (draft Vibe Logic) · Evidence confidence · Commercial status · Conversion (not enough data yet).
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { AlertTriangle, Bookmark, ExternalLink, MessageCircle, Send, Sparkles, X } from 'lucide-react';
import { useState } from 'react';
import { useLocation } from 'wouter';
import { api } from '../lib/api';
import { Badge, Button, Card, Dialog, Empty, Spinner, toast } from './ui';

const FACTOR_LABEL: Record<string, string> = {
  topicAlignment: 'Topic alignment', topic_alignment: 'Topic alignment', contentSimilarity: 'Content similarity', content_similarity: 'Content similarity',
  vibeCompatibility: 'Vibe compatibility', vibe_compatibility: 'Vibe compatibility', formatCompatibility: 'Format compatibility',
  format_compatibility: 'Format compatibility', activityMatch: 'Activity match', activity_match: 'Activity match',
  collaborationOpenness: 'Collaboration openness', collaboration_openness: 'Collaboration openness',
  audienceSizeParity: 'Audience size parity', audience_size_parity: 'Audience size parity', geoOverlap: 'Audience geography', geo_overlap: 'Audience geography',
  lookalike_affinity: 'Sponsors shows like yours', momentum: 'Momentum', category_fit: 'Category fit', recency: 'Recency', breadth: 'Breadth',
  audience_size_fit: 'Audience size fit', geo_fit: 'Audience geography fit',
};
const label = (n: string) => FACTOR_LABEL[n] ?? n.replace(/_/g, ' ');
export const DISMISS_REASONS: [string, string][] = [
  ['not_my_vibe', 'Not my vibe'], ['wrong_topic', 'Wrong topic'], ['too_big', 'Too big'], ['too_small', 'Too small'],
  ['already_know_them', 'Already know them'], ['other', 'Other'],
];
const LEVEL_TONE: Record<string, string> = {
  High: 'text-green-600', Medium: 'text-amber-600', Low: 'text-muted-foreground',
};
const READY_TONE: Record<string, string> = { verified: 'text-green-600', potential_lead: 'text-blue-600', potentialLead: 'text-blue-600', discovery_lead: 'text-muted-foreground' };

export function Measure({ title, value, sub, tone }: { title: string; value: string; sub?: string; tone?: string }) {
  return (
    <div className="rounded-lg border bg-background/50 p-2.5">
      <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">{title}</div>
      <div className={`text-lg font-bold leading-tight ${tone ?? ''}`}>{value}</div>
      {sub && <div className="mt-0.5 text-[11px] leading-snug text-muted-foreground">{sub}</div>}
    </div>
  );
}

export function Breakdown({ o }: { o: any }) {
  const f: any[] = o.breakdown?.factors ?? [];
  return (
    <div className="mt-3 space-y-3 rounded-lg bg-secondary/50 p-3 text-xs">
      <table className="w-full">
        <thead><tr className="text-left text-muted-foreground"><th className="pb-1 font-medium">Factor</th><th className="font-medium">Status</th>
          <th className="font-medium">Score</th><th className="text-right font-medium">Adds to Fit</th></tr></thead>
        <tbody>{f.map((x) => (
          <tr key={x.name} className="align-top">
            <td className="py-1 pr-2">{label(x.name)}</td>
            <td className="pr-2">{x.status === 'used' ? <Badge tone="green">used</Badge> : x.status === 'missing' ? <Badge tone="pink">missing</Badge> : <Badge tone="gray">disabled</Badge>}
              {x.reason && <div className="mt-0.5 max-w-[14rem] text-[11px] text-muted-foreground">{x.reason}</div>}</td>
            <td className="pr-2">{x.status === 'used' ? (
              <div className="flex items-center gap-1.5"><div className="h-1.5 w-16 rounded bg-border"><div className="h-1.5 rounded bg-primary" style={{ width: `${Math.round(x.value * 100)}%` }} /></div>
                <span>{Math.round(x.value * 100)}</span></div>) : '—'}</td>
            <td className="text-right">{x.status === 'used' ? `+${x.contribution.toFixed(1)}` : '0'}</td>
          </tr>))}</tbody>
      </table>
      <p className="text-muted-foreground">Fit = weighted average of the <b>used</b> factors only; missing and disabled factors are left out and the
        remaining weights are re-scaled (nothing is guessed). Missing factors lower the evidence confidence instead.</p>
      {o.confidence?.coverage != null && <p className="text-muted-foreground">Evidence confidence {o.confidence.value}: factor coverage {Math.round(o.confidence.coverage * 100)}%,
        input quality {Math.round((o.confidence.inputQuality ?? 0) * 100)}% (verified &gt; creator-provided &gt; estimated &gt; AI-inferred, and the Layer 1 field confidences).</p>}
      {(o.confidence?.adjustments ?? []).map((a: any) => <p key={a.code} className="text-amber-700 dark:text-amber-300">Confidence ×{a.factor}: {a.code === 'language_uncertain' ? 'language not confidently known' : a.code} ({a.detail})</p>)}
      {o.readiness?.reason && <p className="text-muted-foreground">Commercial status: {o.readiness.reason}</p>}
      <p className="text-muted-foreground">Scoring version <code>{o.fit?.scoringVersion}</code> · {o.typeReason}</p>
      <p className="text-muted-foreground" data-testid="text-source">Card text: {o.explanation?.textSource === 'ai_phrased'
        ? <>AI-phrased from the facts above (checked: every number and name comes from them). Original template: “{o.explanation?.templateText}”</>
        : <>template (written only from the facts above)</>}</p>
    </div>
  );
}

/** The card's explanation sentence, with a small marker when it was AI-phrased (Phase 4). */
export function ExplanationText({ o }: { o: any }) {
  return (
    <p className="mt-3 text-sm">{o.explanation?.text}
      {o.explanation?.textSource === 'ai_phrased' && (
        <span data-testid="ai-phrased" title="Reworded by AI from the facts in the breakdown; checked for faithfulness"
          className="ml-1.5 rounded bg-secondary px-1.5 py-0.5 align-middle text-[10px] font-medium text-muted-foreground">AI-phrased</span>)}
    </p>
  );
}

export function OpportunityCard({ o, readOnly }: { o: any; readOnly?: boolean }) {
  const qc = useQueryClient();
  const [, nav] = useLocation();
  const [open, setOpen] = useState(false);
  const [dismissing, setDismissing] = useState(false);
  const [reason, setReason] = useState('');
  const t = o.target ?? {};
  const why = (o.whyNow ?? [])[0];
  const act = useMutation({
    mutationFn: (b: { action: string; reason?: string }) => api.post(`/api/opportunities/${o.id}/action`, b),
    onSuccess: (r: any, b) => {
      if (b.action === 'message' && r.conversationId) { toast('Conversation opened'); nav('/messages'); return; }
      toast(b.action === 'save' ? 'Saved' : b.action === 'unsave' ? 'Removed from saved' : b.action === 'dismiss' ? 'Dismissed — we will not suggest them again for a while'
        : b.action === 'invite' ? 'Invite recorded (nothing was sent outside PodBae)' : 'Done');
      setDismissing(false);
      qc.invalidateQueries({ queryKey: ['opportunities'] }); qc.invalidateQueries({ queryKey: ['matches'] }); qc.invalidateQueries({ queryKey: ['predictions'] });
    },
    onError: (e: Error) => toast(e.message),
  });
  const ready = o.readiness ?? {};
  const route = ready.contactRoute === 'in_app' ? 'Message in PodBae' : ready.contactRoute === 'contact_page' ? `Declared ${String(ready.routeKind ?? 'contact').replace(/_/g, ' ')} route`
    : 'No declared contact route';
  return (
    <Card className="flex flex-col" >
      <div data-testid="opportunity-card" className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-1.5">
            <h3 className="truncate font-semibold">{t.title}</h3>
            {t.isMember ? <Badge tone="green">On PodBae</Badge> : <Badge tone="gray">Not on PodBae</Badge>}
            <Badge tone="pink">{o.typeLabel}</Badge>
            {t.demoMember && <Badge tone="gray">demo member</Badge>}
          </div>
          <p className="mt-0.5 text-xs text-muted-foreground">{(t.categoryGroup ?? []).join(' · ')}{t.language ? ` · ${String(t.language).toUpperCase()}` : ''}</p>
        </div>
        {o.saved && <Bookmark className="h-4 w-4 shrink-0 fill-primary text-primary" aria-label="Saved" />}
      </div>

      <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
        <Measure title="Fit" value={`${Math.round(o.fit?.value ?? 0)}`} sub={o.fit?.note} tone="text-primary" />
        <Measure title="Evidence confidence" value={o.confidence?.level ?? '—'} sub={`${Math.round((o.confidence?.value ?? 0) * 100)}% · how solid the data behind the Fit is`} tone={LEVEL_TONE[o.confidence?.level]} />
        <Measure title="Commercial status" value={ready.label ?? '—'} sub={route} tone={READY_TONE[ready.level]} />
        <Measure title="Conversion" value="Not enough data yet" sub="No partnership outcomes recorded yet" tone="text-muted-foreground text-sm" />
      </div>

      <ExplanationText o={o} />
      {why && (
        <div className="mt-2 flex gap-2 rounded-lg bg-primary/10 p-2 text-xs"><Sparkles className="mt-0.5 h-3.5 w-3.5 shrink-0 text-primary" />
          <div><b>Why now: {why.label}.</b>{why.evidence?.[0] && <> “{why.evidence[0].title}” ({why.evidence[0].date})</>}</div></div>
      )}
      {(o.evidence?.sharedTopics ?? []).length > 0 && (
        <div className="mt-2 flex flex-wrap items-center gap-1 text-xs"><span className="text-muted-foreground">Evidence · shared topics:</span>
          {o.evidence.sharedTopics.map((x: string) => <Badge key={x}>{x}</Badge>)}</div>
      )}
      <button className="mt-2 self-start text-xs font-medium text-purple-600" onClick={() => setOpen(!open)}>{open ? 'Hide' : 'Show'} breakdown</button>
      {open && <Breakdown o={o} />}

      {!readOnly && (
        <div className="mt-4 flex flex-wrap gap-2">
          <Button size="sm" variant="outline" onClick={() => act.mutate({ action: o.saved ? 'unsave' : 'save' })} disabled={act.isPending}>
            <Bookmark className="h-3.5 w-3.5" />{o.saved ? 'Saved' : 'Save'}</Button>
          <Button size="sm" variant="outline" onClick={() => setDismissing(true)}><X className="h-3.5 w-3.5" />Dismiss</Button>
          {t.isMember ? (
            <Button size="sm" onClick={() => act.mutate({ action: 'message' })} disabled={act.isPending}><MessageCircle className="h-3.5 w-3.5" />Message</Button>
          ) : (
            <Button size="sm" onClick={() => act.mutate({ action: 'invite' })} disabled={act.isPending}><Send className="h-3.5 w-3.5" />Invite to PodBae</Button>
          )}
          {!t.isMember && ready.contactUrl && (
            <a href={ready.contactUrl} target="_blank" rel="noopener noreferrer nofollow" onClick={() => api.post(`/api/opportunities/${o.id}/action`, { action: 'open' }).catch(() => undefined)}
              className="inline-flex h-9 items-center gap-1 rounded-[10px] px-3 text-xs text-muted-foreground hover:bg-secondary"><ExternalLink className="h-3.5 w-3.5" />Contact page</a>
          )}
          {!t.isMember && !ready.contactUrl && t.website && (
            <a href={t.website} target="_blank" rel="noopener noreferrer nofollow" onClick={() => api.post(`/api/opportunities/${o.id}/action`, { action: 'open' }).catch(() => undefined)}
              className="inline-flex h-9 items-center gap-1 rounded-[10px] px-3 text-xs text-muted-foreground hover:bg-secondary"><ExternalLink className="h-3.5 w-3.5" />Website</a>
          )}
        </div>
      )}
      <Dialog open={dismissing} onOpenChange={setDismissing} title={`Dismiss ${t.title}?`}>
        <p className="mb-3 text-sm text-muted-foreground">Tell us why. We will stop suggesting this show to you right away, and the reason helps tune Vibe Logic.</p>
        <div className="grid grid-cols-2 gap-2">{DISMISS_REASONS.map(([k, l]) => (
          <label key={k} className={`flex cursor-pointer items-center gap-2 rounded-lg border p-2 text-sm ${reason === k ? 'border-primary bg-primary/10' : ''}`}>
            <input type="radio" name={`dismiss-${o.id}`} checked={reason === k} onChange={() => setReason(k)} />{l}</label>))}</div>
        <Button className="mt-4 w-full" disabled={!reason || act.isPending} onClick={() => act.mutate({ action: 'dismiss', reason })}>Dismiss</Button>
      </Dialog>
    </Card>
  );
}

const SUGGEST_LINK: Record<string, string> = { add_goals: '/intelligence', set_openness: '/intelligence', upload_audience: '/intelligence', clarify_topics: '/profile' };

/** The podcast-partner section: handles ok / few / no_match / generating / not connected / outdated (AI down). */
export function OpportunitiesPanel({ data, loading }: { data: any; loading?: boolean }) {
  const [, nav] = useLocation();
  if (loading) return <Spinner />;
  if (!data) return null;
  const items: any[] = data.items ?? [];
  return (
    <section className="space-y-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-lg font-semibold">Podcast partners <span className="text-sm font-normal text-muted-foreground">cross-promo · guest swap · feed swap</span></h2>
        {data.scoringVersion && <span className="text-xs text-muted-foreground">Vibe Logic draft {data.scoringVersion} — pending founder approval</span>}
      </div>
      {data.outdated && (
        <p className="flex items-center gap-2 rounded-lg bg-amber-500/15 p-3 text-sm text-amber-700 dark:text-amber-300">
          <AlertTriangle className="h-4 w-4 shrink-0" />{data.message ?? 'Showing your last saved opportunities; they may be outdated.'}</p>
      )}
      {data.state === 'not_connected' && <Empty>{data.message} <button className="text-primary underline" onClick={() => nav('/intelligence')}>Connect now</button></Empty>}
      {data.state === 'generating' && <Empty>Finding partners for your show… refresh in a moment.</Empty>}
      {data.state === 'ai_unavailable' && <Empty>{data.message}</Empty>}
      {(data.state === 'few' || data.state === 'no_match') && !data.outdated && (
        <Card className="space-y-2 bg-secondary/40">
          <p className="text-sm">{data.message}</p>
          {(data.suggestions ?? []).length > 0 && (
            <ul className="space-y-1 text-sm">{data.suggestions.map((s: any) => (
              <li key={s.code}><button className="font-medium text-primary hover:underline" onClick={() => nav(SUGGEST_LINK[s.code] ?? '/intelligence')}>{s.action}</button>
                <span className="text-muted-foreground"> — {s.detail}</span></li>))}</ul>
          )}
        </Card>
      )}
      {data.limited && <p className="rounded-lg bg-primary/10 p-3 text-sm">Your plan shows up to {data.dailyLimit} new partner opportunities per day ({data.totalQualified} qualify). Upgrade to see all.</p>}
      {items.length > 0 && <div className="grid gap-4 lg:grid-cols-2">{items.map((o) => <OpportunityCard key={o.id} o={o} readOnly={data.outdated} />)}</div>}
    </section>
  );
}
