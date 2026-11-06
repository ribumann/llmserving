import { act, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import App from '../src/App';
import { AUTH_REQUIRED_EVENT } from '../src/services/apiClient';

describe('App shell', () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    window.history.replaceState({}, '', '/');
    vi.stubGlobal('fetch', fetchMock);
    fetchMock.mockImplementation(() =>
      Promise.resolve(new Response('', { status: 401 })),
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.clearAllMocks();
  });

  it('renders a public workflow guide without loading live environments', async () => {
    render(<App />);

    expect(
      screen.getByRole('heading', {
        name: /azure llm serving demo/i,
      }),
    ).toBeInTheDocument();

    const nav = screen.getByRole('navigation', { name: /primary/i });
    expect(
      within(nav).getByRole('link', { name: /provision/i }),
    ).toBeInTheDocument();
    expect(
      await screen.findByRole('heading', { name: /explore the workflow/i }),
    ).toBeInTheDocument();
    expect(screen.queryByText('Your environments')).not.toBeInTheDocument();
    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      'http://localhost:8000/session',
    ]);
  });

  it.each([
    '/provision',
    '/deploy',
    '/exercise',
    '/retune',
    '/quality/run',
    '/performance/run',
    '/compare',
    '/history',
    '/teardown',
    '/environments/private-id',
    '/quality/report/private-run',
    '/performance/report/private-run',
  ])('keeps %s private even when opened directly', async (path) => {
    window.history.replaceState({}, '', path);
    render(<App />);
    expect(
      await screen.findByRole('heading', {
        name: 'Sign in to use the operator workspace',
      }),
    ).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(fetchMock.mock.calls).toHaveLength(1);
    const main = screen.getByRole('main');
    expect(
      within(main).getByRole('link', { name: /sign in with microsoft/i }),
    ).toHaveAttribute(
      'href',
      `/.auth/login/aad?post_login_redirect_uri=${encodeURIComponent(path)}`,
    );
  });

  it('keeps navigation available without calling protected page APIs', async () => {
    render(<App />);
    await userEvent.click(screen.getByRole('link', { name: /^provision$/i }));
    expect(
      await screen.findByRole('heading', { name: /sign in to use/i }),
    ).toBeInTheDocument();
    expect(screen.getByText(/review quota and capacity/i)).toBeInTheDocument();
    expect(fetchMock.mock.calls).toHaveLength(1);
  });

  it('distinguishes a forbidden account from a signed-out visitor', async () => {
    window.history.replaceState({}, '', '/history');
    fetchMock.mockResolvedValue(new Response('', { status: 403 }));
    render(<App />);
    expect(
      await screen.findByRole('heading', {
        name: /does not have operator access/i,
      }),
    ).toBeInTheDocument();
    expect(fetchMock.mock.calls).toHaveLength(1);
  });

  it('reports an unavailable identity check and supports retry', async () => {
    window.history.replaceState({}, '', '/deploy');
    fetchMock.mockResolvedValueOnce(new Response('', { status: 503 }));
    render(<App />);
    expect(
      await screen.findByRole('heading', { name: /could not be verified/i }),
    ).toBeInTheDocument();
    await userEvent.click(
      within(screen.getByRole('main')).getByRole('button', {
        name: /check access again/i,
      }),
    );
    expect(
      await screen.findByRole('heading', { name: /sign in to use/i }),
    ).toBeInTheDocument();
    expect(fetchMock.mock.calls).toHaveLength(2);
  });

  it('loads real data only after the backend verifies the session', async () => {
    fetchMock.mockImplementation((url: string) =>
      Promise.resolve(
        new Response(
          JSON.stringify(
            url.endsWith('/session')
              ? { authenticated: true }
              : { environments: [] },
          ),
          { status: 200 },
        ),
      ),
    );
    render(<App />);
    expect(await screen.findByText('Your environments')).toBeInTheDocument();
    expect(
      await screen.findByRole('heading', { name: 'No environments yet' }),
    ).toBeInTheDocument();
    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      'http://localhost:8000/session',
      'http://localhost:8000/environments',
    ]);
    expect(screen.getByRole('link', { name: 'Sign out' })).toBeInTheDocument();
  });

  it('removes private views when a subsequent API call reports expired access', async () => {
    fetchMock.mockImplementation((url: string) =>
      Promise.resolve(
        new Response(
          JSON.stringify(
            url.endsWith('/session')
              ? { authenticated: true }
              : { environments: [] },
          ),
          { status: 200 },
        ),
      ),
    );
    render(<App />);
    expect(await screen.findByText('Your environments')).toBeInTheDocument();
    act(() => {
      window.dispatchEvent(
        new CustomEvent(AUTH_REQUIRED_EVENT, { detail: 401 }),
      );
    });
    expect(
      await screen.findByRole('heading', { name: 'Explore the workflow' }),
    ).toBeInTheDocument();
    expect(screen.queryByText('Your environments')).not.toBeInTheDocument();
  });

  it('fails closed on a malformed successful session response', async () => {
    window.history.replaceState({}, '', '/exercise');
    fetchMock.mockResolvedValue(new Response('{}', { status: 200 }));
    render(<App />);
    expect(
      await screen.findByRole('heading', { name: /could not be verified/i }),
    ).toBeInTheDocument();
    expect(fetchMock.mock.calls).toHaveLength(1);
  });
});
