import { useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
  Body1,
  Button,
  Table,
  TableBody,
  TableCell,
  TableHeader,
  TableHeaderCell,
  TableRow,
  makeStyles,
  tokens,
} from '@fluentui/react-components';
import EnvironmentPicker from '../components/EnvironmentPicker';
import { ApiError } from '../services/apiClient';
import { getEnvironment } from '../services/environmentsApi';
import {
  getPerformanceRunReport,
  getQualityRunReport,
  listRuns,
} from '../services/runsApi';
import type {
  DemoEnvironment,
  PerformanceReportResponse,
  QualityReportResponse,
  RunSummary,
} from '../services/types';
import {
  DataList,
  EmptyState,
  InfoGrid,
  InfoPanel,
  LoadingState,
  PageHeader,
  RouterLink,
  SectionCard,
  StatusBadge,
  StatusMessage,
  formatStateLabel,
  statusTone,
} from '../components/kit';

const useStyles = makeStyles({
  stack: {
    display: 'flex',
    flexDirection: 'column',
    gap: tokens.spacingVerticalL,
  },
  formGrid: {
    display: 'grid',
    gap: tokens.spacingHorizontalM,
    gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))',
  },
  actions: {
    display: 'flex',
    gap: tokens.spacingHorizontalS,
    flexWrap: 'wrap',
    alignItems: 'center',
  },
});

type ReportHistoryTableProps = {
  title: string;
  description: string;
  emptyTitle: string;
  emptyBody: string;
  environmentId: string;
  reportPathPrefix: '/quality/report' | '/performance/report';
  runPath: '/quality/run' | '/performance/run';
  rows: RunSummary[];
  exportingRunId?: string;
  onExport: (run: RunSummary) => void;
};

function formatTimestamp(value?: string | null) {
  if (!value) {
    return 'n/a';
  }

  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
}

function triggerJsonDownload(filename: string, payload: QualityReportResponse | PerformanceReportResponse) {
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

function getHistoryExportErrorMessage(error: unknown) {
  if (error instanceof ApiError && error.code === 'report_not_ready') {
    return 'This report is not ready yet. Wait for the run to finish, then export it from history.';
  }

  return error instanceof Error ? error.message : 'Failed to export the selected report.';
}

function ReportHistoryTable({
  title,
  description,
  emptyTitle,
  emptyBody,
  environmentId,
  reportPathPrefix,
  runPath,
  rows,
  exportingRunId,
  onExport,
}: ReportHistoryTableProps) {
  if (!environmentId) {
    return null;
  }

  return (
    <SectionCard title={title} description={description}>
      {rows.length ? (
        <Table aria-label={title} size="small">
          <TableHeader>
            <TableRow>
              <TableHeaderCell>Run id</TableHeaderCell>
              <TableHeaderCell>Definition</TableHeaderCell>
              <TableHeaderCell>Status</TableHeaderCell>
              <TableHeaderCell>Started</TableHeaderCell>
              <TableHeaderCell>Ended</TableHeaderCell>
              <TableHeaderCell>Actions</TableHeaderCell>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((run) => {
              const reportLink = `${reportPathPrefix}/${run.runId}?environmentId=${encodeURIComponent(environmentId)}`;
              const runLink = `${runPath}?environmentId=${encodeURIComponent(environmentId)}&runId=${encodeURIComponent(run.runId)}`;

              return (
                <TableRow key={run.runId}>
                  <TableCell>{run.runId}</TableCell>
                  <TableCell>{run.testDefinitionRef ?? 'n/a'}</TableCell>
                  <TableCell>
                    <StatusBadge tone={statusTone(run.status)}>{formatStateLabel(run.status)}</StatusBadge>
                  </TableCell>
                  <TableCell>{formatTimestamp(run.startedAt)}</TableCell>
                  <TableCell>{formatTimestamp(run.endedAt)}</TableCell>
                  <TableCell>
                    <div style={{ display: 'flex', gap: tokens.spacingHorizontalS, flexWrap: 'wrap' }}>
                      <RouterLink to={reportLink}>Open report</RouterLink>
                      <Button
                        size="small"
                        onClick={() => onExport(run)}
                        disabled={exportingRunId === run.runId}
                      >
                        {exportingRunId === run.runId ? 'Exporting…' : 'Export as JSON'}
                      </Button>
                      <RouterLink to={runLink}>Open run page</RouterLink>
                    </div>
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      ) : (
        <EmptyState title={emptyTitle}>{emptyBody}</EmptyState>
      )}
    </SectionCard>
  );
}

export default function ExperimentHistoryPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [environmentId, setEnvironmentId] = useState(searchParams.get('environmentId') ?? '');
  const [environment, setEnvironment] = useState<DemoEnvironment>();
  const [environmentLoading, setEnvironmentLoading] = useState(false);
  const [environmentError, setEnvironmentError] = useState<string>();
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [runsLoading, setRunsLoading] = useState(false);
  const [runsError, setRunsError] = useState<string>();
  const [exportingRunId, setExportingRunId] = useState<string>();
  const [exportError, setExportError] = useState<string>();

  async function handleLoadEnvironment(nextEnvironmentId: string = environmentId) {
    if (!nextEnvironmentId.trim()) {
      setEnvironmentError('Select an environment to review its retained run history.');
      return;
    }

    setEnvironmentLoading(true);
    setRunsLoading(true);
    setEnvironmentError(undefined);
    setRunsError(undefined);
    setExportError(undefined);

    try {
      const [environmentResponse, runsResponse] = await Promise.all([
        getEnvironment(nextEnvironmentId.trim()),
        listRuns(nextEnvironmentId.trim()),
      ]);
      setEnvironment(environmentResponse);
      setRuns(
        [...runsResponse.runs].sort((left, right) =>
          new Date(right.startedAt).getTime() - new Date(left.startedAt).getTime(),
        ),
      );
      setEnvironmentId(environmentResponse.environmentId);
      setSearchParams({ environmentId: environmentResponse.environmentId });
    } catch (error) {
      const message =
        error instanceof Error ? error.message : 'Failed to load the selected environment history.';
      setEnvironmentError(message);
      setRunsError(message);
      setEnvironment(undefined);
      setRuns([]);
    } finally {
      setEnvironmentLoading(false);
      setRunsLoading(false);
    }
  }

  useEffect(() => {
    if (environmentId.trim()) {
      void handleLoadEnvironment(environmentId.trim());
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const qualityRuns = useMemo(
    () => runs.filter((run) => run.runType === 'quality-golden' || run.runType === 'quality-benchmark'),
    [runs],
  );
  const performanceRuns = useMemo(
    () => runs.filter((run) => run.runType === 'performance'),
    [runs],
  );

  async function handleExport(run: RunSummary) {
    if (!environmentId.trim()) {
      return;
    }

    setExportingRunId(run.runId);
    setExportError(undefined);

    try {
      if (run.runType === 'performance') {
        const report = await getPerformanceRunReport(environmentId.trim(), run.runId);
        triggerJsonDownload(`${report.resultReportId}.json`, report);
      } else {
        const report = await getQualityRunReport(environmentId.trim(), run.runId);
        triggerJsonDownload(`${report.resultReportId}.json`, report);
      }
    } catch (error) {
      setExportError(getHistoryExportErrorMessage(error));
    } finally {
      setExportingRunId(undefined);
    }
  }

  const styles = useStyles();

  return (
    <div className={styles.stack}>
      <PageHeader
        eyebrow="Manage"
        title="Experiment History"
        description="Reopen prior quality and performance reports for the selected environment, including environments that have already been torn down, and export the raw report JSON when you need to archive or share it."
      />

      <SectionCard title="1. Select an environment">
        <div className={styles.formGrid}>
          <EnvironmentPicker
            value={environmentId}
            onSelect={(nextEnvironmentId) => {
              setEnvironmentId(nextEnvironmentId);
              if (nextEnvironmentId) {
                void handleLoadEnvironment(nextEnvironmentId);
              }
            }}
            disabled={environmentLoading}
          />
        </div>

        {environmentError ? <StatusMessage intent="error">{environmentError}</StatusMessage> : null}
        <div className={styles.actions}>
          <Button onClick={() => void handleLoadEnvironment()} disabled={environmentLoading || !environmentId.trim()}>
            {environmentLoading ? 'Loading history…' : 'Reload history'}
          </Button>
          {environment?.environmentId ? (
            <RouterLink to={`/environments/${environment.environmentId}`}>
              Open environment detail
            </RouterLink>
          ) : null}
        </div>

        {environment ? (
          <InfoGrid>
            <InfoPanel title="Environment context">
              <DataList
                items={[
                  { label: 'Environment id', value: environment.environmentId },
                  { label: 'Profile', value: environment.profileId },
                  { label: 'Region', value: environment.region },
                  {
                    label: 'Lifecycle',
                    value: (
                      <StatusBadge tone={statusTone(environment.state)}>
                        {formatStateLabel(environment.state)}
                      </StatusBadge>
                    ),
                  },
                ]}
              />
            </InfoPanel>
            <InfoPanel title="Retained history">
              <Body1>
                Torn-down environments stay selectable here so previously generated reports remain
                easy to reopen or export without reprovisioning the environment.
              </Body1>
            </InfoPanel>
          </InfoGrid>
        ) : (
          <EmptyState title="Choose an environment to review its history">
            Pick the environment whose completed or partial experiment reports you want to reopen.
          </EmptyState>
        )}
      </SectionCard>

      {runsLoading ? <LoadingState label="Loading experiment history…" /> : null}
      {runsError ? <StatusMessage intent="error">{runsError}</StatusMessage> : null}
      {exportError ? <StatusMessage intent="error">{exportError}</StatusMessage> : null}

      {!runsLoading && environmentId && !runsError ? (
        <>
          <ReportHistoryTable
            title="2. Quality reports"
            description="Reopen golden-dataset and benchmark evaluation reports for this environment, or export the report JSON for offline review."
            emptyTitle="No quality reports yet"
            emptyBody="Quality runs created for this environment will appear here even after the environment is torn down."
            environmentId={environmentId}
            reportPathPrefix="/quality/report"
            runPath="/quality/run"
            rows={qualityRuns}
            exportingRunId={exportingRunId}
            onExport={(run) => void handleExport(run)}
          />

          <ReportHistoryTable
            title="3. Performance reports"
            description="Reopen load-test reports for this environment, or export the underlying JSON for archival and external analysis."
            emptyTitle="No performance reports yet"
            emptyBody="Performance runs created for this environment will appear here once they exist."
            environmentId={environmentId}
            reportPathPrefix="/performance/report"
            runPath="/performance/run"
            rows={performanceRuns}
            exportingRunId={exportingRunId}
            onExport={(run) => void handleExport(run)}
          />
        </>
      ) : null}
    </div>
  );
}
