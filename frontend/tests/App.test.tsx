import { act, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import App from '../src/App';
import { AUTH_REQUIRED_EVENT } from '../src/services/apiClient';

const environment = {
  environmentId: 'env-public',
  profileId: 'profile-public',
  provider: 'azure',
  region: 'eastus',
  lifecycleState: 'ready',
  state: 'ready',
  resources: [],
};
const model = {
  modelConfigId: 'model-public',
  catalogEntryId: 'catalog-public',
  resolvedCheckpointRef: 'public/checkpoint',
  modelSettings: { dtype: 'float16' },
  version: 2,
};
const inference = {
  inferenceConfigId: 'inference-public',
  engineId: 'vllm',
  version: 3,
  servingSettings: { maxModelLen: 2048 },
  generationSettings: { temperature: 0.4 },
};
const run = {
  runId: 'run-public',
  runType: 'quality-golden',
  testDefinitionRef: 'dataset-public',
  status: 'completed',
  startedAt: '2026-11-07T10:00:00Z',
  configuration: { deploymentRevisionId: 'revision-public' },
};
const report = {
  resultReportId: 'report-public',
  runId: 'run-public',
  completenessIndicator: 'complete',
  quality: {
    cases: [],
    aggregate: { totalCases: 10, passed: 9, passRate: 0.9 },
    benchmarks: [],
  },
  performance: null,
};
const comparison = {
  comparisonId: 'comparison-public',
  comparabilityStatus: 'comparable',
  reports: [{ reportId: 'report-public' }],
  reasons: [],
  sections: [{ title: 'Quality', items: [{ passRate: 0.9 }] }],
};

function publicResponse(path: string) {
  if (path === '/public/environments') return { environments: [environment] };
  if (path === '/public/environments/env-public') return environment;
  if (path.endsWith('/model-configurations')) return { items: [model] };
  if (path.endsWith('/inference-configurations')) return { items: [inference] };
  if (path.endsWith('/runs')) return { runs: [run] };
  if (path.endsWith('/report')) return report;
  if (path === '/public/profiles')
    return {
      profiles: [
        {
          profileId: 'profile-public',
          provider: 'azure',
          modelSizeClass: '3b',
          eligibleRegions: ['eastus'],
          vmSku: 'Standard_GPU',
        },
      ],
    };
  if (path === '/public/catalog')
    return {
      catalog: [
        {
          catalogEntryId: 'catalog-public',
          family: 'public-family',
          sizeClass: '3b',
          checkpointRef: 'public/checkpoint',
          license: 'MIT',
          isGated: false,
          compatibleProfileIds: ['profile-public'],
        },
      ],
    };
  if (path === '/public/golden-datasets')
    return {
      goldenDatasets: [
        {
          goldenDatasetId: 'dataset-public',
          version: 1,
          provenance: 'curated',
          reviewStatus: 'reviewed',
          caseCount: 10,
        },
      ],
    };
  if (path === '/public/benchmark-definitions')
    return {
      benchmarkDefinitions: [{ benchmarkId: 'benchmark-public', version: '1' }],
    };
  if (path === '/public/performance-workloads')
    return {
      performanceWorkloads: [
        { workloadId: 'workload-public', version: 1, concurrency: 4 },
      ],
    };
  if (path === '/public/comparisons') return { comparisons: [comparison] };
  if (path === '/public/comparisons/comparison-public') return comparison;
  throw new Error(`Unexpected public request: ${path}`);
}

describe('App public and operator shell', () => {
  const fetchMock = vi.fn();
  let sessionStatus: number;

  beforeEach(() => {
    sessionStatus = 401;
    window.history.replaceState({}, '', '/');
    vi.stubGlobal('fetch', fetchMock);
    fetchMock.mockImplementation((url: string) => {
      const path = new URL(url).pathname;
      if (path === '/session') {
        return Promise.resolve(
          new Response(
            sessionStatus === 200
              ? JSON.stringify({ authenticated: true })
              : '',
            { status: sessionStatus },
          ),
        );
      }
      if (path === '/environments')
        return Promise.resolve(Response.json({ environments: [] }));
      return Promise.resolve(Response.json(publicResponse(path)));
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.clearAllMocks();
  });

  it('shows persisted public environments without operator authentication', async () => {
    render(<App />);
    expect(await screen.findByText('env-public')).toBeInTheDocument();
    expect(screen.getByText('Public read-only workspace')).toBeInTheDocument();
    expect(
      screen.getByRole('link', { name: 'View experiments' }),
    ).toHaveAttribute('href', '/history?environmentId=env-public');
    expect(
      fetchMock.mock.calls.map(([url]) => new URL(url).pathname).sort(),
    ).toEqual(['/public/environments', '/session']);
    expect(screen.queryByText('Learning environment')).not.toBeInTheDocument();
  });

  it.each([
    ['/provision', 'Available profiles'],
    ['/deploy', 'Model configurations'],
    ['/exercise', 'Inference configurations'],
    ['/retune', 'Model configurations'],
    ['/quality/run', 'Golden datasets'],
    ['/performance/run', 'Performance workloads'],
    ['/compare', 'Saved comparisons'],
    ['/history', 'Experiments and saved reports'],
    ['/teardown', 'Environment state'],
    ['/environments/env-public', 'Environment state'],
    [
      '/quality/report/run-public?environmentId=env-public',
      'Saved report summary',
    ],
    [
      '/performance/report/run-public?environmentId=env-public',
      'Saved report summary',
    ],
  ])(
    'renders actual read-only data on direct %s navigation',
    async (path, section) => {
      window.history.replaceState({}, '', path);
      render(<App />);
      expect(
        await screen.findByRole('heading', { name: section }),
      ).toBeInTheDocument();
      const main = screen.getByRole('main');
      expect(
        within(main).getByRole('link', { name: /sign in with microsoft/i }),
      ).toHaveAttribute(
        'href',
        `/.auth/login/aad?post_login_redirect_uri=${encodeURIComponent(path)}`,
      );
      expect(
        fetchMock.mock.calls.every(
          ([url, init]) =>
            (new URL(url).pathname === '/session' ||
              new URL(url).pathname.startsWith('/public/')) &&
            (!init?.method || init.method === 'GET'),
        ),
      ).toBe(true);
    },
  );

  it('keeps actions disabled and cannot submit them from the keyboard', async () => {
    window.history.replaceState({}, '', '/exercise');
    render(<App />);
    expect(await screen.findByText('inference-public')).toBeInTheDocument();
    const send = screen.getByRole('button', { name: 'Send prompt' });
    expect(send).toBeDisabled();
    await userEvent.click(send);
    await userEvent.keyboard('{Enter}');
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
    expect(
      fetchMock.mock.calls.every(
        ([, init]) => !init?.method || init.method === 'GET',
      ),
    ).toBe(true);
  });

  it('opens retained report aggregates and saved comparison data', async () => {
    window.history.replaceState({}, '', '/history');
    render(<App />);
    await userEvent.click(
      await screen.findByRole('link', { name: 'Open report summary' }),
    );
    expect(await screen.findByText('report-public')).toBeInTheDocument();
    expect(screen.getByText('0.9')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('link', { name: 'Compare' }));
    await userEvent.click(
      await screen.findByRole('link', { name: 'Open saved comparison' }),
    );
    expect(
      await screen.findByRole('heading', { name: 'Saved comparison' }),
    ).toBeInTheDocument();
    expect(screen.getByText('Quality')).toBeInTheDocument();
  });

  it('shows real performance metric distributions and safe test conditions', async () => {
    window.history.replaceState(
      {},
      '',
      '/performance/report/run-public?environmentId=env-public',
    );
    fetchMock.mockImplementation((url: string) => {
      const path = new URL(url).pathname;
      if (path === '/session') {
        return Promise.resolve(new Response('', { status: 401 }));
      }
      return Promise.resolve(
        Response.json(
          path.endsWith('/report')
            ? {
                ...report,
                quality: null,
                performance: {
                  metrics: {
                    timeToFirstTokenMs: {
                      p50: 346.1906768998233,
                      p95: 512.4852340587241,
                    },
                    interTokenLatencyMs: { p50: 4, p95: 7 },
                    throughputTokensPerSec: 167.31852946603055,
                  },
                  units: {
                    timeToFirstTokenMs: 'ms',
                    interTokenLatencyMs: 'ms',
                    throughputTokensPerSec: 'tokens/sec',
                  },
                  requestFailures: { count: 1, total: 20, rate: 0.05 },
                  testConditions: { concurrency: 4, requestCount: 20 },
                },
              }
            : publicResponse(path),
        ),
      );
    });
    render(<App />);
    expect(await screen.findByText('p50 346.2 ms · p95 512.5 ms')).toBeInTheDocument();
    expect(screen.getByText('p50 4 ms · p95 7 ms')).toBeInTheDocument();
    expect(screen.queryByText('End-to-end latency')).not.toBeInTheDocument();
    expect(screen.getByText('167.3 tokens/sec')).toBeInTheDocument();
    expect(screen.queryByText('167.31852946603055')).not.toBeInTheDocument();
    expect(screen.getByText('0.05')).toBeInTheDocument();
    expect(screen.getByText('requestCount')).toBeInTheDocument();
  });

  it('changes the environment detail route when selecting another environment', async () => {
    window.history.replaceState({}, '', '/environments/env-public');
    fetchMock.mockImplementation((url: string) => {
      const path = new URL(url).pathname;
      if (path === '/session') {
        return Promise.resolve(new Response('', { status: 401 }));
      }
      return Promise.resolve(
        Response.json(
          path === '/public/environments'
            ? {
                environments: [
                  environment,
                  { ...environment, environmentId: 'env-second' },
                ],
              }
            : path === '/public/environments/env-second'
              ? { ...environment, environmentId: 'env-second' }
              : publicResponse(path),
        ),
      );
    });
    render(<App />);
    await userEvent.selectOptions(
      await screen.findByRole('combobox', { name: 'Environment' }),
      'env-second',
    );
    expect(window.location.pathname).toBe('/environments/env-second');
    expect(
      await screen.findByRole('heading', { name: 'Environment state' }),
    ).toBeInTheDocument();
  });

  it('does not block public reads when identity verification is unavailable', async () => {
    sessionStatus = 503;
    window.history.replaceState({}, '', '/deploy');
    render(<App />);
    expect(
      await screen.findByText(/operator sign-in is unavailable/i),
    ).toBeInTheDocument();
    expect(await screen.findByText('model-public')).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: 'Save configurations and deploy' }),
    ).toBeDisabled();
    sessionStatus = 401;
    await userEvent.click(
      within(screen.getByRole('main')).getByRole('button', {
        name: 'Check access again',
      }),
    );
    expect(
      await screen.findByText(/sign in with an approved microsoft account/i),
    ).toBeInTheDocument();
  });

  it('distinguishes a public API outage from an authentication failure and retries reads', async () => {
    fetchMock.mockImplementation((url: string) =>
      Promise.resolve(
        new URL(url).pathname === '/session'
          ? new Response('', { status: 401 })
          : Response.json(
              {
                error: {
                  code: 'database_unavailable',
                  message: 'Database temporarily unavailable.',
                },
              },
              { status: 503 },
            ),
      ),
    );
    render(<App />);
    expect(
      await screen.findByText('Database temporarily unavailable.'),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: 'Retry public data' }),
    ).toBeEnabled();
    expect(
      screen.queryByText(/operator sign-in is unavailable/i),
    ).not.toBeInTheDocument();
  });

  it('allows a forbidden account to browse public data without actions', async () => {
    sessionStatus = 403;
    render(<App />);
    expect(
      await screen.findByText(/not an approved operator/i),
    ).toBeInTheDocument();
    expect(await screen.findByText('env-public')).toBeInTheDocument();
  });

  it('preserves verified operator views and protected API transport', async () => {
    sessionStatus = 200;
    render(<App />);
    expect(await screen.findByText('Your environments')).toBeInTheDocument();
    expect(
      await screen.findByRole('heading', { name: 'No environments yet' }),
    ).toBeInTheDocument();
    expect(
      fetchMock.mock.calls.map(([url]) => new URL(url).pathname),
    ).toContain('/environments');
    expect(screen.getByRole('link', { name: 'Sign out' })).toBeInTheDocument();
    expect(screen.queryByText('Operator workspace')).not.toBeInTheDocument();
    expect(screen.queryByText('Public workflow guide')).not.toBeInTheDocument();
    expect(screen.queryByText('Learning environment')).not.toBeInTheDocument();
  });

  it('removes private operator data immediately when access expires', async () => {
    sessionStatus = 200;
    render(<App />);
    expect(await screen.findByText('Your environments')).toBeInTheDocument();
    act(() =>
      window.dispatchEvent(
        new CustomEvent(AUTH_REQUIRED_EVENT, { detail: 401 }),
      ),
    );
    expect(screen.queryByText('Your environments')).not.toBeInTheDocument();
    expect(await screen.findByText('env-public')).toBeInTheDocument();
  });

  it('fails closed on a malformed session but still loads public data', async () => {
    fetchMock.mockImplementation((url: string) =>
      Promise.resolve(
        Response.json(
          new URL(url).pathname === '/session'
            ? {}
            : publicResponse(new URL(url).pathname),
        ),
      ),
    );
    render(<App />);
    expect(
      await screen.findByText(/operator sign-in is unavailable/i),
    ).toBeInTheDocument();
    expect(await screen.findByText('env-public')).toBeInTheDocument();
    expect(screen.queryByText('Your environments')).not.toBeInTheDocument();
  });
});
