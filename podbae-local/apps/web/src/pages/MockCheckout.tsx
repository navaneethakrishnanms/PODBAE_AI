import { CreditCard } from 'lucide-react';
import { useState } from 'react';
import { useLocation } from 'wouter';
import { AppLayout } from '../components/Layout';
import { Badge, Button, Card, toast } from '../components/ui';
import { api } from '../lib/api';
import { useMe } from '../lib/auth';

const PLANS: Record<string, { name: string; price: string }> = {
  date: { name: 'Date', price: '$19.00 / month' },
  commit: { name: 'Commit', price: '$29.00 / month' },
};

/** Stand-in for a hosted payment page (Stripe / Lemon Squeezy would live here). */
export default function MockCheckout() {
  const [, nav] = useLocation();
  const { refresh } = useMe();
  const tier = new URLSearchParams(window.location.search).get('tier') ?? '';
  const plan = PLANS[tier];
  const [busy, setBusy] = useState(false);

  async function pay() {
    setBusy(true);
    try {
      await api.post('/api/mock-checkout/complete', { tier });
      await refresh();
      toast(`Upgraded to ${plan.name} 🎉`);
      nav('/dashboard');
    } catch (e: any) {
      toast(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <AppLayout>
      <div className="mx-auto max-w-md">
        <Card className="space-y-4">
          <div className="flex items-center justify-between"><h1 className="text-2xl font-bold">Mock checkout</h1><Badge tone="gray">no real payment</Badge></div>
          {!plan ? <p className="text-sm text-muted-foreground">Unknown plan. Go back to the dashboard.</p> : (
            <>
              <div className="rounded-lg bg-secondary p-4"><div className="font-semibold">PodBae {plan.name}</div><div className="text-2xl font-extrabold">{plan.price}</div></div>
              <div className="flex items-center gap-2 rounded-lg border p-3 text-sm text-muted-foreground"><CreditCard className="h-4 w-4" /> •••• •••• •••• 4242 (fake card)</div>
              <Button size="lg" className="w-full" disabled={busy} onClick={pay}>{busy ? 'Processing…' : `Pay ${plan.price.split(' ')[0]} (mock)`}</Button>
              <Button variant="ghost" className="w-full" onClick={() => nav('/dashboard')}>Cancel</Button>
            </>
          )}
        </Card>
      </div>
    </AppLayout>
  );
}
