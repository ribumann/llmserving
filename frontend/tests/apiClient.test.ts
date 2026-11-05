import { apiRequest } from '../src/services/apiClient';

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
    await apiRequest('/providers', { headers: { Authorization: 'Bearer fixture' } });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('http://127.0.0.1:8001/providers');
    expect(init.headers.get('Authorization')).toBe('Bearer fixture');
  });
});
