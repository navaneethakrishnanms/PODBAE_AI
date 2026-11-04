import { useQuery } from '@tanstack/react-query';
import { Search } from 'lucide-react';
import { useState } from 'react';
import { Link } from 'wouter';
import { PublicLayout } from '../components/Layout';
import { Badge, Button, Card, Empty, Input, Spinner } from '../components/ui';
import { api } from '../lib/api';

export default function Discover() {
  const [q, setQ] = useState('');
  const [category, setCategory] = useState('');
  const [vibe, setVibe] = useState('');
  const [page, setPage] = useState(1);
  const filters = useQuery({ queryKey: ['dir-filters'], queryFn: () => api.get('/api/public/directory/filters') });
  const qs = new URLSearchParams({ page: String(page), ...(q && { q }), ...(category && { category }), ...(vibe && { vibe }) }).toString();
  const { data, isLoading } = useQuery({ queryKey: ['dir', qs], queryFn: () => api.get(`/api/public/directory?${qs}`) });
  const sel = 'rounded-lg border border-input bg-card px-3 py-2 text-sm';
  const pages = Math.max(1, Math.ceil((data?.total ?? 0) / (data?.pageSize ?? 12)));
  return (
    <PublicLayout>
      <div className="mx-auto max-w-6xl px-4 py-12">
        <h1 className="text-4xl font-extrabold">Discover shows</h1>
        <div className="mt-6 flex flex-wrap gap-3">
          <div className="relative min-w-[220px] flex-1"><Search className="absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
            <Input className="pl-9" placeholder="Search shows…" value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} /></div>
          <select className={sel} value={category} onChange={(e) => { setCategory(e.target.value); setPage(1); }}>
            <option value="">All categories</option>{(filters.data?.categories ?? []).map((c: string) => <option key={c}>{c}</option>)}</select>
          <select className={sel} value={vibe} onChange={(e) => { setVibe(e.target.value); setPage(1); }}>
            <option value="">All vibes</option>{(filters.data?.vibes ?? []).map((c: string) => <option key={c}>{c}</option>)}</select>
        </div>
        {isLoading ? <Spinner /> : !data?.podcasts?.length ? <div className="mt-8"><Empty>No shows found.</Empty></div> : (
          <div className="mt-8 grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
            {data.podcasts.map((p: any) => (
              <Card key={p.id}>
                <div className="flex items-center gap-2"><h3 className="font-semibold">{p.name}</h3>
                  {p.verified && <Badge tone="green">verified</Badge>}{p.demo && <Badge tone="gray">demo</Badge>}</div>
                <p className="mt-1 text-xs text-muted-foreground">{p.author} · {p.location ?? '—'} · {p.episodeCount} eps</p>
                <p className="mt-2 line-clamp-3 text-sm">{p.description}</p>
                <div className="mt-3 flex flex-wrap gap-1">{[...p.categories, ...p.vibeTags].map((t: string) => <Badge key={t}>{t}</Badge>)}</div>
                {p.ownerUserId && <Link href={`/p/${p.ownerUserId}`} className="mt-3 inline-block text-sm font-medium text-primary">View profile →</Link>}
              </Card>
            ))}
          </div>
        )}
        <div className="mt-8 flex items-center justify-center gap-3 text-sm">
          <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => setPage(page - 1)}>Prev</Button>
          <span>Page {page} / {pages}</span>
          <Button variant="outline" size="sm" disabled={page >= pages} onClick={() => setPage(page + 1)}>Next</Button>
        </div>
      </div>
    </PublicLayout>
  );
}
