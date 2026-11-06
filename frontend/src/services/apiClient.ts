import type { ApiErrorShape } from './types';

const DEFAULT_LOCAL_API_BASE_URL = 'http://localhost:8000';
export const AUTH_REQUIRED_EVENT = 'llmserving:auth-required';

function getApiBaseUrl() {
  const configured = import.meta.env.VITE_API_BASE_URL?.trim();
  const defaultBase = import.meta.env.PROD
    ? '/api'
    : DEFAULT_LOCAL_API_BASE_URL;
  return (
    configured && configured.length > 0 ? configured : defaultBase
  ).replace(/\/$/, '');
}

export class ApiError extends Error {
  status?: number;
  requestId?: string;
  code?: string;
  details?: unknown;

  constructor(
    message: string,
    payload?: Partial<ApiErrorShape>,
    status?: number,
  ) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
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

export async function apiRequest<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const headers = new Headers({
    'Content-Type': 'application/json',
    ...getDemoAuthHeaders(),
  });
  new Headers(init?.headers).forEach((value, key) => headers.set(key, value));
  const response = await fetch(`${getApiBaseUrl()}${path}`, {
    ...init,
    headers,
    cache: 'no-store',
  });

  if (!response.ok) {
    let payload: Partial<ApiErrorShape> | undefined;

    try {
      payload = (await response.json()) as Partial<ApiErrorShape>;
    } catch {
      payload = undefined;
    }

    if (
      response.status === 401 ||
      (response.status === 403 &&
        (!payload?.error?.code || payload.error.code === 'forbidden_domain'))
    ) {
      window.dispatchEvent(
        new CustomEvent(AUTH_REQUIRED_EVENT, { detail: response.status }),
      );
    }

    throw new ApiError(
      payload?.error?.message ??
        `API request failed with status ${response.status}`,
      payload,
      response.status,
    );
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return (await response.json()) as T;
}
