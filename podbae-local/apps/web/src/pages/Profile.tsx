import { CATEGORIES, COLLAB_TYPES, TONE_TAGS, VIBE_TAGS } from '@podbae/contracts';
import { useQuery } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { useParams } from 'wouter';
import { AppLayout, PublicLayout } from '../components/Layout';
import { Badge, Button, Card, ChipSelect, Empty, Field, Input, Spinner, Textarea, toast } from '../components/ui';
import { api } from '../lib/api';

function useProfile(id: string | undefined) {
  return useQuery({ queryKey: ['pub', id], queryFn: () => api.get(`/api/member/public-profile/${id}`), enabled: !!id });
}

function Body({ d }: { d: any }) {
  const p = d.podcast;
  return (
    <div className="space-y-4">
      <div><h1 className="text-3xl font-extrabold">{p?.name ?? d.user.name}</h1>
        <p className="text-muted-foreground">{d.profile?.headline ?? `${d.user.name} · ${d.user.role}`}</p></div>
      {d.profile?.bio && <p>{d.profile.bio}</p>}
      {p && (
        <>
          <p className="text-sm">{p.description}</p>
          <div className="flex flex-wrap gap-1">{[...p.categories, ...p.vibeTags, ...p.toneTags].map((t: string) => <Badge key={t}>{t}</Badge>)}</div>
          <p className="text-xs text-muted-foreground">{p.location} · {p.episodeCount} episodes {p.demo && '· demo data'}</p>
        </>
      )}
      {d.episodes?.length > 0 && (
        <div><h3 className="mb-1 font-semibold">Recent episodes</h3>
          <ul className="list-disc pl-5 text-sm">{d.episodes.map((e: any) => <li key={e.id}>{e.title}</li>)}</ul></div>
      )}
    </div>
  );
}

export function PublicProfile() {
  const { userId } = useParams();
  const { data, isLoading, error } = useProfile(userId);
  return (
    <PublicLayout>
      <div className="mx-auto max-w-2xl px-4 py-12">
        {isLoading ? <Spinner /> : error || !data ? <Empty>Profile not found.</Empty> : <Card><Body d={data} /></Card>}
      </div>
    </PublicLayout>
  );
}

/** Minimal embeddable card (no site chrome). */
export function Embed() {
  const { userId } = useParams();
  const { data } = useProfile(userId);
  if (!data) return <div className="p-4 text-sm text-muted-foreground">…</div>;
  const p = data.podcast;
  return (
    <div className="m-2 rounded-xl border border-input bg-card p-4">
      <div className="text-xs font-bold text-primary">PodBae</div>
      <div className="font-bold">{p?.name ?? data.user.name}</div>
      <div className="text-xs text-muted-foreground">{(p?.categories ?? []).join(', ')} · {p?.location}</div>
      <a className="mt-2 inline-block text-xs font-semibold text-primary" href={`/p/${userId}`} target="_blank" rel="noreferrer">View on PodBae →</a>
    </div>
  );
}

export function ProfileEdit() {
  const { data, isLoading, refetch } = useQuery({ queryKey: ['profile'], queryFn: () => api.get('/api/member/profile') });
  const pub = useQuery({ queryKey: ['mypub'], queryFn: () => api.get('/api/member/public-profile') });
  const [name, setName] = useState('');
  const [pod, setPod] = useState<any>({});
  const [headline, setHeadline] = useState('');
  const [bio, setBio] = useState('');
  const [goals, setGoals] = useState('');
  useEffect(() => { if (data) { setName(data.user.name ?? ''); setPod(data.podcast ?? {}); } }, [data]);
  useEffect(() => { if (pub.data) { setHeadline(pub.data.profile.headline ?? ''); setBio(pub.data.profile.bio ?? ''); } }, [pub.data]);
  useEffect(() => { api.get('/api/member/goals').then((r) => setGoals((r.goals ?? []).join('\n'))); }, []);

  async function save() {
    try {
      await api.put('/api/member/profile', {
        name,
        ...(data?.podcast && { podcast: { name: pod.name, description: pod.description ?? undefined, categories: pod.categories, location: pod.location ?? undefined,
          vibeTags: pod.vibeTags, toneTags: pod.toneTags, collaborationTypes: pod.collaborationTypes } }),
      });
      await api.put('/api/member/public-profile', { headline, bio, enabled: true });
      await api.put('/api/member/goals', { goals: goals.split('\n').map((s) => s.trim()).filter(Boolean) });
      toast('Profile saved'); refetch();
    } catch (e: any) { toast(e.message); }
  }
  if (isLoading) return <AppLayout><Spinner /></AppLayout>;
  return (
    <AppLayout>
      <div className="mx-auto max-w-2xl space-y-6">
        <h1 className="text-3xl font-extrabold">Your profile</h1>
        <Card className="space-y-4">
          <Field label="Your name"><Input value={name} onChange={(e) => setName(e.target.value)} /></Field>
          <Field label="Headline"><Input value={headline} onChange={(e) => setHeadline(e.target.value)} /></Field>
          <Field label="Bio"><Textarea value={bio} onChange={(e) => setBio(e.target.value)} /></Field>
          <Field label="Goals" hint="(one per line)"><Textarea value={goals} onChange={(e) => setGoals(e.target.value)} /></Field>
        </Card>
        {data?.podcast && (
          <Card className="space-y-4">
            <h2 className="font-bold">Podcast</h2>
            <Field label="Show name"><Input value={pod.name ?? ''} onChange={(e) => setPod({ ...pod, name: e.target.value })} /></Field>
            <Field label="Description"><Textarea value={pod.description ?? ''} onChange={(e) => setPod({ ...pod, description: e.target.value })} /></Field>
            <Field label="Location"><Input value={pod.location ?? ''} onChange={(e) => setPod({ ...pod, location: e.target.value })} /></Field>
            <Field label="Categories"><ChipSelect options={CATEGORIES} value={pod.categories ?? []} onChange={(v) => setPod({ ...pod, categories: v })} /></Field>
            <Field label="Vibe"><ChipSelect options={VIBE_TAGS} value={pod.vibeTags ?? []} onChange={(v) => setPod({ ...pod, vibeTags: v })} /></Field>
            <Field label="Tone"><ChipSelect options={TONE_TAGS} value={pod.toneTags ?? []} onChange={(v) => setPod({ ...pod, toneTags: v })} /></Field>
            <Field label="Collaboration types"><ChipSelect options={COLLAB_TYPES} value={pod.collaborationTypes ?? []} onChange={(v) => setPod({ ...pod, collaborationTypes: v })} /></Field>
          </Card>
        )}
        <div className="flex items-center gap-3"><Button onClick={save}>Save changes</Button>
          {data && <a className="text-sm text-primary" href={`/p/${data.user.id}`}>View public profile</a>}</div>
      </div>
    </AppLayout>
  );
}
