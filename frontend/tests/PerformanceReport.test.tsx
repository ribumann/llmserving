import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import PerformanceReportPage from '../src/pages/PerformanceReport';
import { getEnvironment } from '../src/services/environmentsApi';
import { getPerformanceRun, getPerformanceRunReport } from '../src/services/runsApi';

vi.mock('../src/services/environmentsApi', () => ({ getEnvironment: vi.fn() }));
vi.mock('../src/services/runsApi', () => ({
  getPerformanceRun: vi.fn(),
  getPerformanceRunReport: vi.fn(),
}));

it('renders a partial report without unavailable metrics and retains test conditions', async () => {
  vi.mocked(getEnvironment).mockResolvedValue({
    environmentId: 'env-1', provider: 'azure', profileId: 'gpu', region: 'westus',
    state: 'ready', resources: [],
  });
  vi.mocked(getPerformanceRun).mockResolvedValue(JSON.parse('{"testDefinitionRef":"workload"}'));
  vi.mocked(getPerformanceRunReport).mockResolvedValue(JSON.parse(JSON.stringify({
    resultReportId: 'report-1',
    runId: 'run-1',
    completenessIndicator: 'partial',
    performance: {
      metrics: { timeToFirstTokenMs: { p50: 200, p95: 400 } },
      units: { timeToFirstTokenMs: 'ms' },
      requestFailures: { count: 1, total: 3 },
      testConditions: { warmup: { requestCount: 2 } },
    },
  })));
  render(
    <MemoryRouter initialEntries={['/performance/report/run-1?environmentId=env-1']}>
      <Routes><Route path="/performance/report/:runId" element={<PerformanceReportPage />} /></Routes>
    </MemoryRouter>,
  );
  expect(await screen.findByText('p50 200 ms')).toBeInTheDocument();
  expect(screen.getByText('1 / 3')).toBeInTheDocument();
  expect(screen.queryByText('Throughput')).not.toBeInTheDocument();
  expect(screen.getByText(/must not be treated as a successful result/i)).toBeInTheDocument();
  expect(screen.getByText(/"requestCount": 2/)).toBeInTheDocument();
});
