export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public data: any = {},
  ) {
    super(message);
  }
}

async function req<T = any>(method: string, url: string, body?: unknown): Promise<T> {
  const res = await fetch(url, {
    method,
    credentials: 'include',
    headers: body !== undefined ? { 'content-type': 'application/json' } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError(res.status, data.error ?? res.statusText, data);
  return data as T;
}

export const api = {
  get: <T = any>(url: string) => req<T>('GET', url),
  post: <T = any>(url: string, body: unknown = {}) => req<T>('POST', url, body),
  put: <T = any>(url: string, body: unknown = {}) => req<T>('PUT', url, body),
  delete: <T = any>(url: string) => req<T>('DELETE', url),
};
