import { CATEGORIES, MIN_CAMPAIGN_BUDGET, VIBE_TAGS } from '@podbae/contracts';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { AppLayout } from '../components/Layout';
import { Badge, Button, Card, ChipSelect, Empty, Field, Input, Textarea, toast } from '../components/ui';
import { api } from '../lib/api';

export default function CampaignBuilder() {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ['campaigns'], queryFn: () => api.get('/api/campaigns') });
  const [f, setF] = useState({ name: '', description: '', budgetMin: MIN_CAMPAIGN_BUDGET, budgetMax: '', categories: [] as string[], vibeTags: [] as string[], location: '' });
  const create = useMutation({
    mutationFn: () => api.post('/api/campaigns', { ...f, budgetMax: f.budgetMax ? Number(f.budgetMax) : undefined }),
    onSuccess: () => { toast('Campaign created'); qc.invalidateQueries({ queryKey: ['campaigns'] }); setF({ ...f, name: '', description: '' }); },
    onError: (e: Error) => toast(e.message),
  });
  return (
    <AppLayout>
      <h1 className="mb-6 text-3xl font-extrabold">Campaign builder</h1>
      <div className="grid gap-6 md:grid-cols-2">
        <Card className="space-y-4">
          <h2 className="font-bold">New campaign</h2>
          <Field label="Name"><Input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
          <Field label="Description"><Textarea value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} /></Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Min budget" hint={`(≥ $${MIN_CAMPAIGN_BUDGET})`}><Input type="number" min={MIN_CAMPAIGN_BUDGET} value={f.budgetMin} onChange={(e) => setF({ ...f, budgetMin: Number(e.target.value) })} /></Field>
            <Field label="Max budget"><Input type="number" value={f.budgetMax} onChange={(e) => setF({ ...f, budgetMax: e.target.value })} /></Field>
          </div>
          <Field label="Location"><Input value={f.location} onChange={(e) => setF({ ...f, location: e.target.value })} /></Field>
          <Field label="Categories"><ChipSelect options={CATEGORIES} value={f.categories} onChange={(categories) => setF({ ...f, categories })} /></Field>
          <Field label="Vibe"><ChipSelect options={VIBE_TAGS} value={f.vibeTags} onChange={(vibeTags) => setF({ ...f, vibeTags })} /></Field>
          <Button disabled={!f.name || f.budgetMin < MIN_CAMPAIGN_BUDGET || create.isPending} onClick={() => create.mutate()}>Create campaign</Button>
        </Card>
        <div className="space-y-3">
          <h2 className="font-bold">Your campaigns</h2>
          {!(data?.campaigns ?? []).length ? <Empty>No campaigns yet.</Empty> : data.campaigns.map((c: any) => (
            <Card key={c.id}><div className="flex justify-between"><b>{c.name}</b><Badge tone="green">{c.status}</Badge></div>
              <p className="text-sm text-muted-foreground">${c.budgetMin}{c.budgetMax ? `–$${c.budgetMax}` : '+'} · {(c.categories ?? []).join(', ')}</p></Card>
          ))}
        </div>
      </div>
    </AppLayout>
  );
}
