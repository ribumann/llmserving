import type { ApiErrorShape } from './types';

const DEFAULT_LOCAL_API_BASE_URL = 'http://localhost:8000';

function getApiBaseUrl() {
  const configured = import.meta.env.VITE_API_BASE_URL?.trim();
  const defaultBase = import.meta.env.PROD ? '/api' : DEFAULT_LOCAL_API_BASE_URL;
  return (configured && configured.length > 0 ? configured : defaultBase).replace(
    /\/$/,
    '',
  );
}

export class ApiError extends Error {
  requestId?: string;
  code?: string;
  details?: unknown;

  constructor(message: string, payload?: Partial<ApiErrorShape>) {
    super(message);
    this.name = 'ApiError';
    this.requestId = payload?.requestId;
    this.code = payload?.error?.code;
    this.details = payload?.error?.details;
  }
}

function getDemoAuthHeaders(): Record<string, string> {
  if (import.meta.env.PROD) return {};
  const demoUser = import.meta.env.VITE_DEMO_USER?.trim();
  return demoUser ? { 'X-Demo-User': demoUser } : {};
}

export async function apiRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers({
    'Content-Type': 'application/json',
    ...getDemoAuthHeaders(),
  });
  new Headers(init?.headers).forEach((value, key) => headers.set(key, value));
  const response = await fetch(`${getApiBaseUrl()}${path}`, {
    ...init,
    headers,
  });

  if (!response.ok) {
    let payload: Partial<ApiErrorShape> | undefined;

    try {
      payload = (await response.json()) as Partial<ApiErrorShape>;
    } catch {
      payload = undefined;
    }

    throw new ApiError(
      payload?.error?.message ?? `API request failed with status ${response.status}`,
      payload,
    );
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return (await response.json()) as T;
}
