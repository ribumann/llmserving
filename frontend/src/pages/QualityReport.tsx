import { useEffect, useMemo, useState } from 'react';
import { useLocation, useParams, useSearchParams } from 'react-router-dom';
import {
  Table,
  TableBody,
  TableCell,
  TableHeader,
  TableHeaderCell,
  TableRow,
  makeStyles,
  tokens,
} from '@fluentui/react-components';
import ComparabilityWarning from '../components/ComparabilityWarning';
import { ApiError } from '../services/apiClient';
import { getEnvironment } from '../services/environmentsApi';
import { getQualityRunReport } from '../services/runsApi';
import type { DemoEnvironment, QualityReportResponse } from '../services/types';
import {
  DataList,
  EmptyState,
  InfoGrid,
  InfoPanel,
  LoadingState,
  MetricCard,
  MetricGrid,
  PageHeader,
  RouterLink,
  SectionCard,
  StatusBadge,
  StatusMessage,
  statusTone,
} from '../components/kit';

const useStyles = makeStyles({
  stack: {
    display: 'flex',
    flexDirection: 'column',
    gap: tokens.spacingVerticalL,
  },
  actions: {
    display: 'flex',
    gap: tokens.spacingHorizontalS,
  },
});

function formatPercent(value: number) {
  return `${(value * 100).toFixed(1)}%`;
}

function getCompletenessMessage(indicator: QualityReportResponse['completenessIndicator']) {
  switch (indicator) {
    case 'partial':
      return 'This report is partial. Some cases or metrics were not fully recorded before the run stopped.';
    case 'unavailable-monitoring-data':
      return 'This report is missing some monitoring data. Interpret the quality summary with caution.';
    default:
      return '';
  }
}

export default function QualityReportPage() {
  const { runId = '' } = useParams();
  const [searchParams] = useSearchParams();
  const location = useLocation();
  const styles = useStyles();
  const locationState = location.state as { environmentId?: string } | null;
  const environmentId = searchParams.get('environmentId') ?? locationState?.environmentId ?? '';
  const [report, setReport] = useState<QualityReportResponse>();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>();
  const [reportNotReady, setReportNotReady] = useState(false);
  const [environment, setEnvironment] = useState<DemoEnvironment>();

  useEffect(() => {
    if (!runId || !environmentId) {
      setLoading(false);
      return;
    }

    let cancelled = false;

    async function loadReport() {
      setLoading(true);
      setError(undefined);
      setReportNotReady(false);

      try {
        const [response, environmentResponse] = await Promise.all([
          getQualityRunReport(environmentId, runId),
          getEnvironment(environmentId),
        ]);

        if (!cancelled) {
          setReport(response);
          setEnvironment(environmentResponse);
        }
      } catch (nextError) {
        if (cancelled) {
          return;
        }

        if (nextError instanceof ApiError && nextError.code === 'report_not_ready') {
          setReportNotReady(true);
          setReport(undefined);
        } else {
          setError(
            nextError instanceof Error ? nextError.message : 'Failed to load the quality report.',
          );
          setReport(undefined);
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    void loadReport();

    return () => {
      cancelled = true;
    };
  }, [environmentId, runId]);

  const backToRunLink = useMemo(() => {
    if (!environmentId) {
      return '/quality/run';
    }

    return `/quality/run?environmentId=${encodeURIComponent(environmentId)}${runId ? `&runId=${encodeURIComponent(runId)}` : ''}`;
  }, [environmentId, runId]);

  if (!environmentId) {
    return (
      <div className={styles.stack}>
        <PageHeader
          title="Quality report"
          description="Open this report from the quality run page so the environment context is preserved."
        />
        <StatusMessage intent="warning">
          This report URL is missing the environment id query parameter required by the API
          contract.
        </StatusMessage>
        <RouterLink to="/quality/run">Go to quality run</RouterLink>
      </div>
    );
  }

  return (
    <div className={styles.stack}>
      <PageHeader
        eyebrow="Evaluate"
        title="Quality report"
        description={
          <>
            Review aggregate pass/fail results, deterministic case outcomes, benchmark deltas, and
            incomplete-report signals for run <code>{runId}</code>.
          </>
        }
        actions={<RouterLink to={backToRunLink}>Back to quality run</RouterLink>}
      />

      {loading ? <LoadingState label="Loading quality report…" /> : null}
      {error ? <StatusMessage intent="error">{error}</StatusMessage> : null}
      {reportNotReady ? (
        <SectionCard title="Report not ready yet">
          <StatusMessage intent="warning">
            This report is not finished yet. Return to the run page to monitor completion, then
            reopen the report.
          </StatusMessage>
          <div className={styles.actions}>
            <RouterLink to={backToRunLink}>Return to run progress</RouterLink>
          </div>
        </SectionCard>
      ) : null}

      {report ? (
        <>
          <ComparabilityWarning provider={environment?.provider} />
          {report.completenessIndicator !== 'complete' ? (
            <StatusMessage intent="warning" title={report.completenessIndicator}>
              {getCompletenessMessage(report.completenessIndicator)}
            </StatusMessage>
          ) : null}

          <SectionCard title="1. Aggregate summary">
            <MetricGrid>
              <MetricCard label="Total cases" value={report.quality.aggregate.totalCases} />
              <MetricCard label="Passed" value={report.quality.aggregate.passed} />
              <MetricCard label="Failed" value={report.quality.aggregate.failed} />
              <MetricCard label="Errored" value={report.quality.aggregate.errored} />
              <MetricCard label="Skipped" value={report.quality.aggregate.skipped} />
              <MetricCard label="Incomplete" value={report.quality.aggregate.incomplete} />
              <MetricCard label="Pass rate" value={formatPercent(report.quality.aggregate.passRate)} />
            </MetricGrid>

            <InfoGrid>
              <InfoPanel title="Report metadata">
                <DataList
                  items={[
                    { label: 'Result report id', value: report.resultReportId },
                    { label: 'Reference execution profile', value: report.referenceExecutionProfileRef ?? 'n/a' },
                    {
                      label: 'Model checkpoint',
                      value: report.configuration?.resolvedCheckpointRef ?? 'n/a',
                    },
                    { label: 'Engine', value: report.configuration?.engineId ?? 'n/a' },
                  ]}
                />
              </InfoPanel>
            </InfoGrid>
          </SectionCard>

          <SectionCard title="2. Deterministic case outcomes">
            {report.quality.cases.length ? (
              <Table aria-label="Deterministic case outcomes" size="small">
                <TableHeader>
                  <TableRow>
                    <TableHeaderCell>Case id</TableHeaderCell>
                    <TableHeaderCell>Input</TableHeaderCell>
                    <TableHeaderCell>Evaluation rule</TableHeaderCell>
                    <TableHeaderCell>Observed outcome</TableHeaderCell>
                    <TableHeaderCell>Status</TableHeaderCell>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {report.quality.cases.map((qualityCase) => (
                    <TableRow key={qualityCase.caseId}>
                      <TableCell>{qualityCase.caseId}</TableCell>
                      <TableCell>{qualityCase.input}</TableCell>
                      <TableCell>{qualityCase.evaluationRule}</TableCell>
                      <TableCell>{qualityCase.observedOutcome}</TableCell>
                      <TableCell>
                        <StatusBadge tone={statusTone(qualityCase.status)}>{qualityCase.status}</StatusBadge>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            ) : (
              <EmptyState title="No deterministic case outcomes recorded">
                This run type may not use deterministic cases, or the run stopped before any
                completed.
              </EmptyState>
            )}
          </SectionCard>

          <SectionCard title="3. Benchmark results">
            {report.quality.benchmarks.length ? (
              <Table aria-label="Benchmark results" size="small">
                <TableHeader>
                  <TableRow>
                    <TableHeaderCell>Benchmark</TableHeaderCell>
                    <TableHeaderCell>Version</TableHeaderCell>
                    <TableHeaderCell>Score</TableHeaderCell>
                    <TableHeaderCell>Baseline</TableHeaderCell>
                    <TableHeaderCell>Delta</TableHeaderCell>
                    <TableHeaderCell>Pass / fail</TableHeaderCell>
                    <TableHeaderCell>Regression</TableHeaderCell>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {report.quality.benchmarks.map((benchmark) => (
                    <TableRow key={`${benchmark.benchmarkId}-${benchmark.version}`}>
                      <TableCell>{benchmark.benchmarkId}</TableCell>
                      <TableCell>{benchmark.version}</TableCell>
                      <TableCell>{benchmark.score}</TableCell>
                      <TableCell>{benchmark.baseline}</TableCell>
                      <TableCell>{benchmark.delta}</TableCell>
                      <TableCell>
                        <StatusBadge tone={benchmark.passFail === 'pass' ? 'success' : 'error'}>
                          {benchmark.passFail}
                        </StatusBadge>
                      </TableCell>
                      <TableCell>
                        {benchmark.regressionFlag ? (
                          <StatusBadge tone="warning">Regression flagged</StatusBadge>
                        ) : (
                          <StatusBadge tone="success">No regression</StatusBadge>
                        )}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            ) : (
              <EmptyState title="No benchmark outcomes recorded">
                This run may have used a golden dataset only, or stopped before any benchmark
                scored.
              </EmptyState>
            )}
          </SectionCard>
        </>
      ) : null}
    </div>
  );
}
