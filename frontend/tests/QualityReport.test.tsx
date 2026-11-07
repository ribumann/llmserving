import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import QualityReportPage from '../src/pages/QualityReport';
import { ApiError } from '../src/services/apiClient';
import { getEnvironment } from '../src/services/environmentsApi';
import { getQualityRunReport } from '../src/services/runsApi';

vi.mock('../src/services/runsApi', () => ({
  getQualityRunReport: vi.fn(),
}));

vi.mock('../src/services/environmentsApi', () => ({
  getEnvironment: vi.fn(),
}));

const mockedGetQualityRunReport = vi.mocked(getQualityRunReport);
const mockedGetEnvironment = vi.mocked(getEnvironment);

describe('QualityReportPage', () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it('renders aggregate quality summary, case outcomes, and benchmark regressions', async () => {
    mockedGetEnvironment.mockResolvedValue({
      environmentId: 'env-123',
      provider: 'azure',
      profileId: 'azure-gpu-a10',
      region: 'westus3',
      state: 'ready',
      activeRevisionId: 'rev-123',
      activeDeploymentRevisionId: 'rev-123',
      resources: [],
    });
    mockedGetQualityRunReport.mockResolvedValue({
      requestId: 'req-report',
      resultReportId: 'report-123',
      runId: 'run-123',
      completenessIndicator: 'partial',
      quality: {
        aggregate: {
          totalCases: 5,
          passed: 3,
          failed: 1,
          errored: 1,
          skipped: 0,
          incomplete: 0,
          passRate: 0.6,
        },
        cases: [
          {
            caseId: 'case-001',
            input: 'Summarize the GPU readiness note.',
            evaluationRule: 'Must mention GPU capacity.',
            observedOutcome: 'Mentions GPU capacity and the selected region.',
            status: 'passed',
          },
          {
            caseId: 'case-002',
            input: 'Return JSON only.',
            evaluationRule: 'Must be valid JSON.',
            observedOutcome: 'Returned prose instead of JSON.',
            status: 'failed',
          },
        ],
        benchmarks: [
          {
            benchmarkId: 'gsm8k',
            version: '2026.08',
            score: 0.61,
            baseline: 0.66,
            delta: -0.05,
            passFail: 'fail',
            regressionFlag: true,
          },
        ],
      },
      performance: null,
      referenceExecutionProfileRef: 'quality-short-v1',
    });

    render(
      <MemoryRouter initialEntries={['/quality/report/run-123?environmentId=env-123']}>
        <Routes>
          <Route path="/quality/report/:runId" element={<QualityReportPage />} />
        </Routes>
      </MemoryRouter>,
    );

    expect(await screen.findByText(/this report is partial/i)).toBeInTheDocument();
    expect(screen.getByText('5')).toBeInTheDocument();
    expect(screen.getByText('60.0%')).toBeInTheDocument();
    expect(screen.getByText(/return json only/i)).toBeInTheDocument();
    expect(screen.getByText(/returned prose instead of json/i)).toBeInTheDocument();
    expect(screen.getByText(/regression flagged/i)).toBeInTheDocument();
    expect(screen.getByText('report-123')).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText('Show cases'), 'attention');
    expect(screen.queryByText('case-001')).not.toBeInTheDocument();
    expect(screen.getByText('case-002')).toBeInTheDocument();
    await userEvent.click(screen.getByText('View case case-002'));
    expect(screen.getByText('Returned prose instead of JSON.')).toBeVisible();
  });

  it('shows a return-to-run message when the report is not ready yet', async () => {
    mockedGetEnvironment.mockResolvedValue({
      environmentId: 'env-123',
      provider: 'azure',
      profileId: 'azure-gpu-a10',
      region: 'westus3',
      state: 'ready',
      activeRevisionId: 'rev-123',
      activeDeploymentRevisionId: 'rev-123',
      resources: [],
    });
    mockedGetQualityRunReport.mockRejectedValue(
      new ApiError('Report not ready.', {
        requestId: 'req-not-ready',
        error: {
          code: 'report_not_ready',
          message: 'Report not ready.',
        },
      }),
    );

    render(
      <MemoryRouter initialEntries={['/quality/report/run-123?environmentId=env-123']}>
        <Routes>
          <Route path="/quality/report/:runId" element={<QualityReportPage />} />
        </Routes>
      </MemoryRouter>,
    );

    expect(await screen.findByText(/this report is not finished yet/i)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /return to run progress/i })).toHaveAttribute(
      'href',
      '/quality/run?environmentId=env-123&runId=run-123',
    );
  });
});
