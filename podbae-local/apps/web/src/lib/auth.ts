import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from './api';

export interface Me {
  id: number;
  email: string;
  name: string | null;
  role: 'podcaster' | 'advertiser' | 'venue' | 'guest' | 'admin';
  tier: 'flirt' | 'date' | 'commit' | 'premium';
  onboarded: boolean;
}

export function useMe() {
  const qc = useQueryClient();
  const query = useQuery({
    queryKey: ['me'],
    queryFn: async () => {
      try {
        return (await api.get<{ user: Me }>('/api/auth/me')).user;
      } catch {
        return null;
      }
    },
    staleTime: 30_000,
  });
  return {
    me: query.data ?? null,
    loading: query.isLoading,
    refresh: () => qc.invalidateQueries({ queryKey: ['me'] }),
    logout: async () => {
      await api.post('/api/logout');
      qc.clear();
      window.location.href = '/';
    },
  };
}
