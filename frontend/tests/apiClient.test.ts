import {
  ApiError,
  apiRequest,
  AUTH_REQUIRED_EVENT,
} from '../src/services/apiClient';

describe('API authentication transport', () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    vi.stubGlobal('fetch', fetchMock);
    fetchMock.mockResolvedValue(new Response('{}', { status: 200 }));
    vi.stubEnv('VITE_API_BASE_URL', '');
    vi.stubEnv('VITE_DEMO_USER', 'presenter@example.com');
  });

  afterEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
    vi.clearAllMocks();
  });

  it('uses the same-origin signed proxy in production, without demo identity', async () => {
    vi.stubEnv('PROD', true);
    await apiRequest('/providers');
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('/api/providers');
    expect(init.headers.get('X-Demo-User')).toBeNull();
    expect(init.headers.get('Content-Type')).toBe('application/json');
    expect(init.cache).toBe('no-store');
  });

  it('preserves explicit local demo auth with caller Headers', async () => {
    vi.stubEnv('PROD', false);
    await apiRequest('/providers', {
      headers: new Headers({ 'X-Request-ID': 'local-validation' }),
    });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('http://localhost:8000/providers');
    expect(init.headers.get('X-Demo-User')).toBe('presenter@example.com');
    expect(init.headers.get('X-Request-ID')).toBe('local-validation');
    expect(init.headers.get('Content-Type')).toBe('application/json');
  });

  it('retains explicit bearer headers and configured local API bases', async () => {
    vi.stubEnv('VITE_API_BASE_URL', 'http://127.0.0.1:8001/');
    await apiRequest('/providers', {
      headers: { Authorization: 'Bearer fixture' },
    });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('http://127.0.0.1:8001/providers');
    expect(init.headers.get('Authorization')).toBe('Bearer fixture');
  });

  it.each([401, 403])(
    'notifies the shell about HTTP %s, including an empty proxy response',
    async (status) => {
      const listener = vi.fn();
      window.addEventListener(AUTH_REQUIRED_EVENT, listener);
      fetchMock.mockResolvedValueOnce(new Response('', { status }));
      await expect(apiRequest('/session')).rejects.toMatchObject({
        name: 'ApiError',
        status,
      });
      expect(listener).toHaveBeenCalledOnce();
      expect(listener.mock.calls[0][0].detail).toBe(status);
      window.removeEventListener(AUTH_REQUIRED_EVENT, listener);
    },
  );

  it('preserves structured API errors with their HTTP status', async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          requestId: 'request-id',
          error: { code: 'unavailable', message: 'Unavailable' },
        }),
        { status: 503 },
      ),
    );
    const error = await apiRequest('/session').catch((error: unknown) => error);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({
      status: 503,
      code: 'unavailable',
      requestId: 'request-id',
    });
  });

  it('does not sign an operator out for a resource ownership denial', async () => {
    const listener = vi.fn();
    window.addEventListener(AUTH_REQUIRED_EVENT, listener);
    fetchMock.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          error: {
            code: 'configuration_not_owned',
            message: 'Only its creator can delete it.',
          },
        }),
        { status: 403 },
      ),
    );
    await expect(
      apiRequest('/environments/example/model-configurations/other', {
        method: 'DELETE',
      }),
    ).rejects.toMatchObject({ status: 403, code: 'configuration_not_owned' });
    expect(listener).not.toHaveBeenCalled();
    window.removeEventListener(AUTH_REQUIRED_EVENT, listener);
  });
});
