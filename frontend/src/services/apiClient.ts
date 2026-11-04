import type { ApiErrorShape } from './types';

const DEFAULT_API_BASE_URL = 'http://localhost:8000';

function getApiBaseUrl() {
  const configured = import.meta.env.VITE_API_BASE_URL?.trim();
  return (configured && configured.length > 0 ? configured : DEFAULT_API_BASE_URL).replace(
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
  // Dev/demo-only convenience: production deployments should sit behind an
  // Entra ID reverse proxy that sets X-MS-CLIENT-PRINCIPAL-NAME instead.
  const demoUser = import.meta.env.VITE_DEMO_USER?.trim();
  return demoUser ? { 'X-Demo-User': demoUser } : {};
}

export async function apiRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${getApiBaseUrl()}${path}`, {
    headers: {
      'Content-Type': 'application/json',
      ...getDemoAuthHeaders(),
      ...init?.headers,
    },
    ...init,
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
