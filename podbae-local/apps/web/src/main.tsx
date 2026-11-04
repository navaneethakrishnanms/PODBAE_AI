import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import { ToastHost } from './components/ui';
import './index.css';

try {
  if (localStorage.getItem('theme') === 'dark') document.documentElement.classList.add('dark');
} catch {
  /* ignore */
}

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } },
});

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
      <ToastHost />
    </QueryClientProvider>
  </React.StrictMode>,
);
