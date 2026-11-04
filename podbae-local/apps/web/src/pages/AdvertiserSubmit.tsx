import { CATEGORIES, MIN_CAMPAIGN_BUDGET, ORG_TYPES, VIBE_TAGS } from '@podbae/contracts';
import { useState } from 'react';
import { useLocation } from 'wouter';
import { PublicLayout } from '../components/Layout';
import { Button, Card, ChipSelect, Field, Input, Textarea, toast } from '../components/ui';
import { api } from '../lib/api';
import { useMe } from '../lib/auth';

const GOALS = ['Brand awareness', 'Sales', 'Lead gen', 'Local reach', 'Donations', 'App installs'];
const VALUES = ['Sustainable', 'Local', 'Inclusive', 'Health', 'Education', 'Community', 'Innovation'];
const STEP_TITLES = ['Organization type', 'Budget', 'Audience & vibe', 'Categories', 'Goals', 'Contact'];

export default function AdvertiserSubmit() {
  const [, nav] = useLocation();
  const { refresh } = useMe();
  const [step, setStep] = useState(0);
  const [f, setF] = useState({
    orgType: '' as string, orgName: '', budgetMin: 150, audience: '', vibeTags: [] as string[], brandValues: [] as string[],
    categories: [] as string[], goals: [] as string[], contactName: '', email: '', password: '', location: '',
  });
  const [busy, setBusy] = useState(false);

  const valid = [
    !!f.orgType, f.budgetMin >= MIN_CAMPAIGN_BUDGET, true, f.categories.length > 0, f.goals.length > 0,
    !!(f.orgName && f.email && f.password.length >= 8),
  ][step];

  async function finish() {
    setBusy(true);
    try {
      await api.post('/api/advertiser/register', f);
      await refresh();
      nav('/dashboard/campaign-builder');
    } catch (err: any) { toast(err.message); } finally { setBusy(false); }
  }

  return (
    <PublicLayout>
      <div className="mx-auto max-w-2xl px-4 py-12">
        <div className="mb-6 flex gap-1">{STEP_TITLES.map((_, i) => (<div key={i} className={`h-1.5 flex-1 rounded ${i <= step ? 'bg-primary' : 'bg-border'}`} />))}</div>
        <p className="text-sm text-muted-foreground">Step {step + 1} of 6</p>
        <h1 className="mb-6 text-3xl font-extrabold">{STEP_TITLES[step]}</h1>
        <Card className="space-y-5">
          {step === 0 && (
            <div className="grid gap-2 sm:grid-cols-2">
              {ORG_TYPES.map((o) => (
                <button key={o} onClick={() => setF({ ...f, orgType: o })}
                  className={`rounded-lg border p-3 text-left text-sm font-medium ${f.orgType === o ? 'border-primary bg-primary/10' : 'border-input hover:bg-secondary'}`}>{o}</button>
              ))}
            </div>
          )}
          {step === 1 && (
            <Field label="Minimum campaign budget (USD)" hint={`min $${MIN_CAMPAIGN_BUDGET}`}>
              <Input type="number" min={MIN_CAMPAIGN_BUDGET} value={f.budgetMin} onChange={(e) => setF({ ...f, budgetMin: Number(e.target.value) })} />
            </Field>
          )}
          {step === 2 && (
            <>
              <Field label="Target audience"><Textarea value={f.audience} onChange={(e) => setF({ ...f, audience: e.target.value })} /></Field>
              <Field label="Vibe"><ChipSelect options={VIBE_TAGS} value={f.vibeTags} onChange={(vibeTags) => setF({ ...f, vibeTags })} /></Field>
              <Field label="Brand values"><ChipSelect options={VALUES} value={f.brandValues} onChange={(brandValues) => setF({ ...f, brandValues })} /></Field>
            </>
          )}
          {step === 3 && <ChipSelect options={CATEGORIES} value={f.categories} onChange={(categories) => setF({ ...f, categories })} />}
          {step === 4 && <ChipSelect options={GOALS} value={f.goals} onChange={(goals) => setF({ ...f, goals })} />}
          {step === 5 && (
            <>
              <Field label="Organization name"><Input value={f.orgName} onChange={(e) => setF({ ...f, orgName: e.target.value })} /></Field>
              <Field label="Contact name"><Input value={f.contactName} onChange={(e) => setF({ ...f, contactName: e.target.value })} /></Field>
              <Field label="Location"><Input value={f.location} onChange={(e) => setF({ ...f, location: e.target.value })} placeholder="City, ST" /></Field>
              <Field label="Email"><Input type="email" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} /></Field>
              <Field label="Password" hint="(min 8)"><Input type="password" value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} /></Field>
            </>
          )}
          <div className="flex justify-between pt-2">
            <Button variant="outline" disabled={step === 0} onClick={() => setStep(step - 1)}>Back</Button>
            {step < 5 ? <Button disabled={!valid} onClick={() => setStep(step + 1)}>Next</Button>
              : <Button disabled={!valid || busy} onClick={finish}>{busy ? 'Creating…' : 'Create account'}</Button>}
          </div>
        </Card>
      </div>
    </PublicLayout>
  );
}
