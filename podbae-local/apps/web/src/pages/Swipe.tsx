import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Heart, X } from 'lucide-react';
import { useState } from 'react';
import { Link } from 'wouter';
import { AppLayout } from '../components/Layout';
import { MatchCard, type MatchRow } from '../components/MatchCard';
import { Button, Empty, Spinner, toast } from '../components/ui';
import { api, ApiError } from '../lib/api';

export default function Swipe() {
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({ queryKey: ['deck'], queryFn: () => api.get('/api/member/matches?unswiped=1') });
  const [idx, setIdx] = useState(0);
  const [fly, setFly] = useState<'left' | 'right' | null>(null);
  const deck: MatchRow[] = data?.matches ?? [];
  const current = deck[idx];

  const swipe = useMutation({
    mutationFn: (direction: 'left' | 'right') => api.post('/api/member/swipe', { targetUserId: current.targetUserId, direction }),
    onSuccess: (r: any) => {
      if (r.mutualMatch) toast("It's a Match! 💕");
      qc.invalidateQueries({ queryKey: ['unread'] });
      qc.invalidateQueries({ queryKey: ['tier'] });
    },
    onError: (e: unknown) => {
      if (e instanceof ApiError && e.data?.code === 'quota_exceeded') toast('Daily swipe limit reached — upgrade for more');
      else toast((e as Error).message);
    },
    onSettled: () => { setFly(null); setIdx((i) => i + 1); },
  });
  const go = (d: 'left' | 'right') => { if (!current || swipe.isPending) return; setFly(d); setTimeout(() => swipe.mutate(d), 180); };

  return (
    <AppLayout>
      <div className="mx-auto max-w-md">
        <h1 className="mb-6 text-center text-3xl font-extrabold">Swipe</h1>
        {isLoading ? <Spinner /> : !current ? (
          <Empty>No more matches in your deck today. <Link href="/messages" className="text-primary">Check messages</Link></Empty>
        ) : (
          <>
            <div className={`transition-all duration-200 ${fly === 'right' ? 'translate-x-24 rotate-6 opacity-0' : fly === 'left' ? '-translate-x-24 -rotate-6 opacity-0' : ''}`}>
              <MatchCard m={current} />
            </div>
            <div className="mt-6 flex justify-center gap-6">
              <Button variant="outline" size="lg" className="h-16 w-16 rounded-full p-0" onClick={() => go('left')} aria-label="Pass"><X className="h-7 w-7" /></Button>
              <Button size="lg" className="h-16 w-16 rounded-full p-0" onClick={() => go('right')} aria-label="Like"><Heart className="h-7 w-7" /></Button>
            </div>
            <p className="mt-3 text-center text-xs text-muted-foreground">{deck.length - idx} left in deck</p>
          </>
        )}
      </div>
    </AppLayout>
  );
}
