import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Send } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { AppLayout } from '../components/Layout';
import { Badge, Button, Card, Empty, Input } from '../components/ui';
import { api } from '../lib/api';
import { useMe } from '../lib/auth';

export default function Messages() {
  const qc = useQueryClient();
  const { me } = useMe();
  const [active, setActive] = useState<number | null>(null);
  const [text, setText] = useState('');
  const endRef = useRef<HTMLDivElement>(null);

  const convos = useQuery({ queryKey: ['convos'], refetchInterval: 5000, queryFn: () => api.get('/api/chat/conversations') });
  const list: any[] = convos.data?.conversations ?? [];
  useEffect(() => { if (active === null && list.length) setActive(list[0].id); }, [list, active]);

  const msgs = useQuery({
    queryKey: ['msgs', active], enabled: active !== null, refetchInterval: 4000,
    queryFn: async () => {
      const r = await api.get(`/api/chat/conversations/${active}/messages`);
      await api.post(`/api/chat/conversations/${active}/read`);
      qc.invalidateQueries({ queryKey: ['unread'] });
      return r;
    },
  });
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [msgs.data]);

  const send = useMutation({
    mutationFn: () => api.post(`/api/chat/conversations/${active}/messages`, { body: text }),
    onSuccess: () => { setText(''); qc.invalidateQueries({ queryKey: ['msgs', active] }); qc.invalidateQueries({ queryKey: ['convos'] }); },
  });

  return (
    <AppLayout>
      <h1 className="mb-4 text-3xl font-extrabold">Messages</h1>
      {!list.length ? <Empty>No conversations yet. Mutual matches from the swipe deck show up here.</Empty> : (
        <div className="grid gap-4 md:grid-cols-[280px_1fr]">
          <Card className="p-2">
            {list.map((c) => (
              <button key={c.id} onClick={() => setActive(c.id)}
                className={`w-full rounded-lg p-3 text-left text-sm ${active === c.id ? 'bg-primary/10' : 'hover:bg-secondary'}`}>
                <div className="flex items-center justify-between"><b>{c.otherName}</b>{c.unread > 0 && <Badge tone="pink">{c.unread}</Badge>}</div>
                <div className="truncate text-xs text-muted-foreground">{c.lastMessage ?? 'Say hello 👋'}</div>
              </button>
            ))}
          </Card>
          <Card className="flex h-[480px] flex-col">
            <div className="flex-1 space-y-2 overflow-y-auto">
              {(msgs.data?.messages ?? []).map((m: any) => (
                <div key={m.id} className={`max-w-[75%] rounded-xl px-3 py-2 text-sm ${m.senderId === me?.id ? 'ml-auto bg-primary text-white' : 'bg-secondary'}`}>{m.body}</div>
              ))}
              <div ref={endRef} />
            </div>
            <form className="mt-3 flex gap-2" onSubmit={(e) => { e.preventDefault(); if (text.trim() && active) send.mutate(); }}>
              <Input value={text} onChange={(e) => setText(e.target.value)} placeholder="Write a message…" />
              <Button disabled={send.isPending}><Send className="h-4 w-4" /></Button>
            </form>
          </Card>
        </div>
      )}
    </AppLayout>
  );
}
