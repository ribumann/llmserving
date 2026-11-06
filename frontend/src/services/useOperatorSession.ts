import { useEffect, useState } from 'react';
import { ApiError, apiRequest, AUTH_REQUIRED_EVENT } from './apiClient';

export type OperatorSession =
  'checking' | 'authenticated' | 'signed-out' | 'forbidden' | 'unavailable';

export function useOperatorSession() {
  const [session, setSession] = useState<OperatorSession>('checking');
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    const onAuthRequired = (event: Event) => {
      if (event instanceof CustomEvent) {
        setSession(event.detail === 403 ? 'forbidden' : 'signed-out');
      }
    };
    window.addEventListener(AUTH_REQUIRED_EVENT, onAuthRequired);
    apiRequest<{ authenticated: boolean }>('/session', {
      signal: controller.signal,
    })
      .then((response) => {
        if (!controller.signal.aborted) {
          setSession(
            response.authenticated === true ? 'authenticated' : 'unavailable',
          );
        }
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        setSession(
          error instanceof ApiError && error.status === 401
            ? 'signed-out'
            : error instanceof ApiError && error.status === 403
              ? 'forbidden'
              : 'unavailable',
        );
      });
    return () => {
      controller.abort();
      window.removeEventListener(AUTH_REQUIRED_EVENT, onAuthRequired);
    };
  }, [attempt]);

  const retry = () => {
    setSession('checking');
    setAttempt((current) => current + 1);
  };
  return { session, retry };
}
