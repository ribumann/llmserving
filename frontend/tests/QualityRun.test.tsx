import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import QualityRunPage from '../src/pages/QualityRun';
import { ApiError } from '../src/services/apiClient';
import { getEnvironment, listEnvironments } from '../src/services/environmentsApi';
import {
  createQualityRun,
  getQualityRun,
  listBenchmarkDefinitions,
  listGoldenDatasets,
  listRuns,
} from '../src/services/runsApi';

vi.mock('../src/services/environmentsApi', () => ({
  getEnvironment: vi.fn(),
  listEnvironments: vi.fn(),
}));

vi.mock('../src/services/runsApi', () => ({
  createQualityRun: vi.fn(),
  getQualityRun: vi.fn(),
  cancelQualityRun: vi.fn(),
  listRuns: vi.fn(),
  listGoldenDatasets: vi.fn(),
  listBenchmarkDefinitions: vi.fn(),
}));

const mockedGetEnvironment = vi.mocked(getEnvironment);
const mockedListEnvironments = vi.mocked(listEnvironments);
const mockedCreateQualityRun = vi.mocked(createQualityRun);
const mockedGetQualityRun = vi.mocked(getQualityRun);
const mockedListRuns = vi.mocked(listRuns);
const mockedListGoldenDatasets = vi.mocked(listGoldenDatasets);
const mockedListBenchmarkDefinitions = vi.mocked(listBenchmarkDefinitions);

describe('QualityRunPage', () => {
  beforeEach(() => {
    mockedGetEnvironment.mockResolvedValue({
      environmentId: 'env-123',
      name: 'demo-ready',
      provider: 'azure',
      profileId: 'azure-single-gpu-7b',
      region: 'southcentralus',
      state: 'ready',
      activeOperationId: null,
      activeDeploymentRevisionId: 'rev-001',
      resources: [],
      updatedAt: '2026-08-19T09:45:00Z',
    });

    mockedListEnvironments.mockResolvedValue({
      requestId: 'req-environments',
      environments: [
        {
          environmentId: 'env-123',
          profileId: 'azure-single-gpu-7b',
          provider: 'azure',
          region: 'southcentralus',
          lifecycleState: 'ready',
          activeOperationId: null,
        },
      ],
    });

    mockedListRuns.mockResolvedValue({
      requestId: 'req-runs',
      runs: [],
    });

    mockedListGoldenDatasets.mockResolvedValue({
      requestId: 'req-golden-datasets',
      goldenDatasets: [],
    });

    mockedListBenchmarkDefinitions.mockResolvedValue({
      requestId: 'req-benchmark-definitions',
      benchmarkDefinitions: [],
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.clearAllMocks();
  });

  it('starts a golden dataset run, polls progress, and exposes the report link', async () => {
    const user = userEvent.setup();
    const setTimeoutSpy = vi
      .spyOn(window, 'setTimeout')
      .mockImplementation((handler: TimerHandler) => {
      if (typeof handler === 'function') {
        queueMicrotask(() => handler());
      }

      return 0 as unknown as ReturnType<typeof window.setTimeout>;
    });

    mockedCreateQualityRun.mockResolvedValue({
      requestId: 'req-start',
      runId: 'run-123',
      runType: 'quality-golden',
      status: 'queued',
      deploymentRevisionId: 'rev-001',
    });

    mockedGetQualityRun
      .mockResolvedValueOnce({
        requestId: 'req-run-1',
        runId: 'run-123',
        environmentId: 'env-123',
        deploymentRevisionId: 'rev-001',
        runType: 'quality-golden',
        testDefinitionRef: 'golden-demo-v1',
        status: 'running',
        startedAt: '2026-08-19T10:00:00Z',
        endedAt: null,
        diagnostics: [
          {
            timestamp: '2026-08-19T10:00:01Z',
            severity: 'info',
            message: 'Case execution started.',
          },
        ],
        progress: {
          totalCases: 5,
          completedCases: 2,
        },
      })
      .mockResolvedValueOnce({
        requestId: 'req-run-2',
        runId: 'run-123',
        environmentId: 'env-123',
        deploymentRevisionId: 'rev-001',
        runType: 'quality-golden',
        testDefinitionRef: 'golden-demo-v1',
        status: 'completed',
        startedAt: '2026-08-19T10:00:00Z',
        endedAt: '2026-08-19T10:00:10Z',
        diagnostics: [
          {
            timestamp: '2026-08-19T10:00:10Z',
            severity: 'info',
            message: 'Run completed.',
          },
        ],
        progress: {
          totalCases: 5,
          completedCases: 5,
        },
      });

    render(
      <MemoryRouter initialEntries={['/quality/run?environmentId=env-123']}>
        <QualityRunPage />
      </MemoryRouter>,
    );

    // The environment auto-loads from the ?environmentId= deep link on mount.
    await waitFor(() => {
      expect(mockedGetEnvironment).toHaveBeenCalledWith('env-123');
    });

    await user.type(screen.getByRole('combobox', { name: /golden dataset/i }), 'golden-demo-v1');
    await user.click(screen.getByRole('button', { name: /start run/i }));

    await waitFor(() => {
      expect(mockedCreateQualityRun).toHaveBeenCalledWith('env-123', {
        runType: 'quality-golden',
        testDefinitionRef: 'golden-demo-v1',
      });
      expect(mockedGetQualityRun).toHaveBeenCalledWith('env-123', 'run-123');
    });

    await waitFor(() => {
      expect(mockedGetQualityRun.mock.calls.length).toBeGreaterThanOrEqual(2);
    });

    expect(await screen.findByText('5 / 5 cases complete')).toBeInTheDocument();
    expect(screen.getByText(/run completed/i)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /open quality report/i })).toHaveAttribute(
      'href',
      '/quality/report/run-123?environmentId=env-123',
    );

    setTimeoutSpy.mockRestore();
  });

  it('maps unreviewed datasets to a blocking guidance message', async () => {
    const user = userEvent.setup();

    mockedCreateQualityRun.mockRejectedValue(
      new ApiError('Unreviewed dataset rejected.', {
        requestId: 'req-error',
        error: {
          code: 'unreviewed_dataset_rejected',
          message: 'Unreviewed dataset rejected.',
        },
      }),
    );

    render(
      <MemoryRouter initialEntries={['/quality/run?environmentId=env-123']}>
        <QualityRunPage />
      </MemoryRouter>,
    );

    await user.type(screen.getByRole('combobox', { name: /golden dataset/i }), 'golden-ai-v2');
    await user.click(screen.getByRole('button', { name: /start run/i }));

    expect(
      await screen.findByText(/this dataset hasn't been reviewed yet and can't be used/i),
    ).toBeInTheDocument();
  });
});
