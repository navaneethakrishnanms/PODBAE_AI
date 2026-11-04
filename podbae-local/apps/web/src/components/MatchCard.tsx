import { Bookmark, Check, X } from 'lucide-react';
import { useState } from 'react';
import { Badge, Card } from './ui';

export interface MatchRow {
  id: number;
  targetType: string;
  targetId: number;
  targetUserId: number | null;
  targetSnapshot: { name: string; location?: string | null; categories?: string[]; demo?: boolean };
  totalScore: number;
  scoreBreakdown: Record<string, any> & { weights: Record<string, number> };
  explanation: { summary: string; reasons: string[]; whyNow?: string; evidence: { source: string; ref: string; fetchedAt: string }[] };
  status: string;
  saved?: boolean;
}

const LABELS: [string, string][] = [
  ['genreScore', 'Genre'], ['locationScore', 'Location'], ['toneScore', 'Tone'],
  ['keywordScore', 'Keywords'], ['vibeScore', 'Vibe'], ['performanceScore', 'Performance'],
];

export function ScoreBars({ b }: { b: MatchRow['scoreBreakdown'] }) {
  return (
    <div className="space-y-1.5">
      {LABELS.map(([k, label]) => (
        <div key={k} className="flex items-center gap-2 text-xs">
          <span className="w-20 text-muted-foreground">{label}</span>
          <div className="h-1.5 flex-1 rounded bg-border">
            <div className="h-1.5 rounded bg-primary" style={{ width: `${Math.round((b[k] ?? 0) * 100)}%` }} />
          </div>
          <span className="w-8 text-right">{Math.round((b[k] ?? 0) * 100)}</span>
        </div>
      ))}
    </div>
  );
}

export function MatchCard({ m, onSave, onDismiss, onOpenChat }: {
  m: MatchRow; onSave?: () => void; onDismiss?: () => void; onOpenChat?: () => void;
}) {
  const [open, setOpen] = useState(false);
  return (
    <Card>
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="font-semibold">{m.targetSnapshot.name}</h3>
            <Badge tone="pink">{m.targetType}</Badge>
            {m.targetSnapshot.demo && <Badge tone="gray">demo</Badge>}
          </div>
          <p className="text-xs text-muted-foreground">{m.targetSnapshot.location ?? '—'} · {(m.targetSnapshot.categories ?? []).join(', ')}</p>
        </div>
        <div className="text-right">
          <div className="text-2xl font-extrabold text-primary">{Math.round(m.totalScore)}%</div>
        </div>
      </div>
      <p className="mt-3 text-sm">{m.explanation.summary}</p>
      <ul className="mt-2 list-disc pl-5 text-xs text-muted-foreground">
        {m.explanation.reasons.map((r) => <li key={r}>{r}</li>)}
      </ul>
      <button className="mt-3 text-xs font-medium text-purple-600" onClick={() => setOpen(!open)}>
        {open ? 'Hide' : 'Show'} score breakdown
      </button>
      {open && (
        <div className="mt-2 space-y-3">
          <ScoreBars b={m.scoreBreakdown} />
          <p className="text-xs text-muted-foreground">
            Sources: {m.explanation.evidence.map((e) => `${e.source}#${e.ref}`).join(', ')}
          </p>
        </div>
      )}
      <div className="mt-4 flex gap-2">
        {onSave && (
          <button onClick={onSave} className="inline-flex items-center gap-1 rounded-lg border border-input px-3 py-1.5 text-xs hover:bg-secondary">
            <Bookmark className={`h-3.5 w-3.5 ${m.saved ? 'fill-primary text-primary' : ''}`} /> {m.saved ? 'Saved' : 'Save'}
          </button>
        )}
        {onDismiss && (
          <button onClick={onDismiss} className="inline-flex items-center gap-1 rounded-lg border border-input px-3 py-1.5 text-xs hover:bg-secondary">
            <X className="h-3.5 w-3.5" /> Dismiss
          </button>
        )}
        {onOpenChat && (
          <button onClick={onOpenChat} className="inline-flex items-center gap-1 rounded-lg border border-input px-3 py-1.5 text-xs hover:bg-secondary">
            <Check className="h-3.5 w-3.5" /> Message
          </button>
        )}
      </div>
    </Card>
  );
}
