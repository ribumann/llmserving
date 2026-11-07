import { useEffect, useMemo, useState } from 'react';
import { useLocation, useParams, useSearchParams } from 'react-router-dom';
import { Body1, makeStyles, tokens } from '@fluentui/react-components';
import ComparabilityWarning from '../components/ComparabilityWarning';
import { ApiError } from '../services/apiClient';
import { getEnvironment } from '../services/environmentsApi';
import {
  getPerformanceRun,
  getPerformanceRunReport,
} from '../services/runsApi';
import type {
  DemoEnvironment,
  PerformanceMetricDistribution,
  PerformanceReportResponse,
  PerformanceRunStatusResponse,
} from '../services/types';
import {
  DataList,
  InfoGrid,
  InfoPanel,
  LoadingState,
  MetricCard,
  MetricGrid,
  PageHeader,
  RouterLink,
  SectionCard,
  StatusMessage,
  formatMetricValue,
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
  preformatted: {
    whiteSpace: 'pre-wrap',
    fontFamily: tokens.fontFamilyMonospace,
  },
});

function formatPercent(value: number) {
  return `${(value * 100).toFixed(1)}%`;
}

function formatRecordValue(value: unknown) {
  if (value === null || value === undefined) {
    return 'n/a';
  }

  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
    return String(value);
  }

  return JSON.stringify(value, null, 2);
}

function getCompletenessMessage(indicator: PerformanceReportResponse['completenessIndicator']) {
  switch (indicator) {
    case 'partial':
      return 'Some metrics or monitoring signals were only partially captured before the run stopped. These metrics must not be treated as a successful result.';
    case 'unavailable-monitoring-data':
      return 'Monitoring data is missing for part of this run. The displayed metrics must not be treated as a successful result.';
    default:
      return '';
  }
}

function distributionMetric(
  label: string,
  metric: PerformanceMetricDistribution,
  unit: string | undefined,
) {
  return (
    <MetricCard
      key={label}
      label={label}
      value={`p50 ${formatMetricValue(metric.p50)} ${unit ?? ''}`}
      secondary={`p95 ${formatMetricValue(metric.p95)} ${unit ?? ''}`}
    />
  );
}

export default function PerformanceReportPage() {
  const { runId = '' } = useParams();
  const [searchParams] = useSearchParams();
  const location = useLocation();
  const styles = useStyles();
  const locationState = location.state as { environmentId?: string } | null;
  const environmentId = searchParams.get('environmentId') ?? locationState?.environmentId ?? '';
  const [report, setReport] = useState<PerformanceReportResponse>();
  const [runStatus, setRunStatus] = useState<PerformanceRunStatusResponse>();
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
        const [reportResponse, statusResponse, environmentResponse] = await Promise.all([
          getPerformanceRunReport(environmentId, runId),
          getPerformanceRun(environmentId, runId),
          getEnvironment(environmentId),
        ]);

        if (!cancelled) {
          setReport(reportResponse);
          setRunStatus(statusResponse);
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
            nextError instanceof Error ? nextError.message : 'Failed to load the performance report.',
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
      return '/performance/run';
    }

    return `/performance/run?environmentId=${encodeURIComponent(environmentId)}${runId ? `&runId=${encodeURIComponent(runId)}` : ''}`;
  }, [environmentId, runId]);

  if (!environmentId) {
    return (
      <div className={styles.stack}>
        <PageHeader
          title="Performance report"
          description="Open this report from the performance run page so the environment context is preserved."
        />
        <StatusMessage intent="warning">
          This report URL is missing the environment id query parameter required by the API
          contract.
        </StatusMessage>
        <RouterLink to="/performance/run">Go to performance run</RouterLink>
      </div>
    );
  }

  const performance = report?.performance;
  const units = performance?.units ?? {};
  const testConditions = performance?.testConditions ?? {};

  return (
    <div className={styles.stack}>
      <PageHeader
        eyebrow="Evaluate"
        title="Performance report"
        description={
          <>
            Review latency, throughput, failure, and accelerator-utilization outcomes for run{' '}
            <code>{runId}</code>.
          </>
        }
        actions={<RouterLink to={backToRunLink}>Back to performance run</RouterLink>}
      />

      {loading ? <LoadingState label="Loading performance report…" /> : null}
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
            <StatusMessage intent="error" title={report.completenessIndicator}>
              {getCompletenessMessage(report.completenessIndicator)}
            </StatusMessage>
          ) : null}

          <SectionCard title="1. Test conditions">
            <InfoGrid>
              <InfoPanel>
                <DataList
                  items={[
                    { label: 'Result report id', value: report.resultReportId },
                    { label: 'Workload id', value: runStatus?.testDefinitionRef ?? 'n/a' },
                    { label: 'Reference execution profile', value: report.referenceExecutionProfileRef ?? 'n/a' },
                    { label: 'Model checkpoint', value: report.configuration?.resolvedCheckpointRef ?? 'n/a' },
                    { label: 'Engine', value: report.configuration?.engineId ?? 'n/a' },
                    { label: 'Runner', value: performance?.runner ?? 'n/a' },
                    {
                      label: 'Warm-up',
                      value: <span className={styles.preformatted}>{formatRecordValue(testConditions.warmup)}</span>,
                    },
                    {
                      label: 'Input profile',
                      value: (
                        <span className={styles.preformatted}>{formatRecordValue(testConditions.inputProfile)}</span>
                      ),
                    },
                  ]}
                />
              </InfoPanel>
              <InfoPanel>
                <DataList
                  items={[
                    { label: 'Concurrency', value: formatRecordValue(testConditions.concurrency) },
                    {
                      label: 'Duration or request count',
                      value: (
                        <span className={styles.preformatted}>
                          {formatRecordValue(testConditions.durationOrRequestCount)}
                        </span>
                      ),
                    },
                    {
                      label: 'Safety limits',
                      value: <span className={styles.preformatted}>{formatRecordValue(testConditions.safetyLimits)}</span>,
                    },
                    {
                      label: 'Completion criteria',
                      value: (
                        <span className={styles.preformatted}>
                          {formatRecordValue(testConditions.completionCriteria)}
                        </span>
                      ),
                    },
                  ]}
                />
              </InfoPanel>
            </InfoGrid>
          </SectionCard>

          <SectionCard title="2. Metrics">
            {performance ? (
              <MetricGrid>
                {distributionMetric('Time to first token', performance.metrics.timeToFirstTokenMs, units.timeToFirstTokenMs)}
                {distributionMetric('Inter-token latency', performance.metrics.interTokenLatencyMs, units.interTokenLatencyMs)}
                {distributionMetric('End-to-end latency', performance.metrics.endToEndLatencyMs, units.endToEndLatencyMs)}
                <MetricCard
                  label="Throughput"
                  value={`${formatMetricValue(performance.metrics.throughputTokensPerSec)} ${units.throughputTokensPerSec ?? ''}`}
                />
                <MetricCard
                  label="Request failures"
                  value={`${performance.requestFailures.count} / ${performance.requestFailures.total}`}
                  secondary={`${formatPercent(performance.requestFailures.rate)} failure rate`}
                />
              </MetricGrid>
            ) : (
              <StatusMessage intent="warning">
                Performance metrics are not available yet for this run, or the run failed before any
                reportable measurements were produced.
              </StatusMessage>
            )}
          </SectionCard>

          <SectionCard title="3. Accelerator utilization">
            {performance ? (
              performance.acceleratorUtilization.available ? (
                <InfoGrid>
                  <InfoPanel>
                    <DataList
                      items={[
                        { label: 'Availability', value: 'Available' },
                        {
                          label: 'Details',
                          value: (
                            <span className={styles.preformatted}>
                              {formatRecordValue(performance.acceleratorUtilization.details ?? {})}
                            </span>
                          ),
                        },
                      ]}
                    />
                  </InfoPanel>
                </InfoGrid>
              ) : (
                <StatusMessage intent="warning">Not available for this run.</StatusMessage>
              )
            ) : (
              <Body1>No accelerator utilization data is available because the run did not produce a performance payload.</Body1>
            )}
          </SectionCard>
        </>
      ) : null}
    </div>
  );
}
