import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Body1, Button, Caption1, Field, Input, makeStyles, tokens } from '@fluentui/react-components';
import EnvironmentPicker from '../components/EnvironmentPicker';
import RunHistory from '../components/RunHistory';
import { ApiError } from '../services/apiClient';
import { getEnvironment } from '../services/environmentsApi';
import {
  cancelPerformanceRun,
  createPerformanceRun,
  getPerformanceRun,
  listPerformanceWorkloads,
} from '../services/runsApi';
import type {
  CreatePerformanceRunResponse,
  DemoEnvironment,
  PerformanceRunStatusResponse,
  PerformanceRunType,
  PerformanceWorkloadSummary,
} from '../services/types';
import {
  DataList,
  InfoGrid,
  InfoPanel,
  PageHeader,
  RouterButton,
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
  diagnosticsLog: {
    margin: 0,
    paddingLeft: tokens.spacingHorizontalL,
    display: 'flex',
    flexDirection: 'column',
    gap: tokens.spacingVerticalXS,
  },
});

const PERFORMANCE_RUN_POLL_INTERVAL_MS = 2000;
const TERMINAL_RUN_STATUSES = new Set<PerformanceRunStatusResponse['status']>([
  'completed',
  'cancelled',
  'failed',
  'incomplete',
]);

function formatTimestamp(value?: string | null) {
  if (!value) {
    return 'n/a';
  }

  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
}

function getPerformanceRunErrorMessage(error: unknown, environmentId: string) {
  if (error instanceof ApiError) {
    switch (error.code) {
      case 'test_definition_not_found':
        return 'The selected performance workload was not found. Check the workload id and retry.';
      case 'no_ready_deployment':
        return `No ready deployment is active for this environment. Open Deploy to activate one before retrying: /deploy?environmentId=${environmentId}`;
      case 'environment_busy':
        return 'This environment is already busy with another operation. Wait for it to finish, then start the run again.';
      case 'run_type_not_yet_supported':
        return 'Performance runs have not been enabled in the backend yet.';
      case 'run_not_found':
        return 'The selected performance run could not be found for this environment.';
      default:
        return error.message;
    }
  }

  return error instanceof Error ? error.message : 'Performance run request failed.';
}

function isTerminalStatus(status?: PerformanceRunStatusResponse['status']) {
  return status ? TERMINAL_RUN_STATUSES.has(status) : false;
}

function isCancelableStatus(status?: PerformanceRunStatusResponse['status']) {
  return status === 'queued' || status === 'running';
}

export default function PerformanceRunPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [environmentId, setEnvironmentId] = useState(searchParams.get('environmentId') ?? '');
  const [environment, setEnvironment] = useState<DemoEnvironment>();
  const [environmentLoading, setEnvironmentLoading] = useState(false);
  const [environmentError, setEnvironmentError] = useState<string>();
  const [workloadId, setWorkloadId] = useState('');
  const [performanceWorkloads, setPerformanceWorkloads] = useState<PerformanceWorkloadSummary[]>([]);
  const [startingRun, setStartingRun] = useState(false);
  const [runError, setRunError] = useState<string>();
  const [cancellingRun, setCancellingRun] = useState(false);
  const [acceptedRun, setAcceptedRun] = useState<CreatePerformanceRunResponse>();
  const [runStatus, setRunStatus] = useState<PerformanceRunStatusResponse>();
  const [historyRefreshToken, setHistoryRefreshToken] = useState(0);
  const styles = useStyles();

  const activeRunId =
    runStatus?.runId ?? acceptedRun?.runId ?? searchParams.get('runId')?.trim() ?? '';
  const runType: PerformanceRunType = 'performance';
  const testDefinitionRef = workloadId.trim();

  useEffect(() => {
    if (!environmentId.trim() || !activeRunId || isTerminalStatus(runStatus?.status)) {
      return;
    }

    let active = true;
    let timeoutId: number | undefined;

    const poll = async () => {
      try {
        const nextRun = await getPerformanceRun(environmentId.trim(), activeRunId);

        if (!active) {
          return;
        }

        setRunStatus(nextRun);

        if (isTerminalStatus(nextRun.status)) {
          return;
        }

        timeoutId = window.setTimeout(poll, PERFORMANCE_RUN_POLL_INTERVAL_MS);
      } catch (error) {
        if (!active) {
          return;
        }

        setRunError(getPerformanceRunErrorMessage(error, environmentId.trim()));
      }
    };

    void poll();

    return () => {
      active = false;
      if (timeoutId !== undefined) {
        window.clearTimeout(timeoutId);
      }
    };
  }, [activeRunId, environmentId, runStatus?.status]);

  async function handleLoadEnvironment(nextEnvironmentId: string = environmentId) {
    if (!nextEnvironmentId.trim()) {
      setEnvironmentError('Select an environment to load the active deployment context.');
      return;
    }

    setEnvironmentLoading(true);
    setEnvironmentError(undefined);

    try {
      const response = await getEnvironment(nextEnvironmentId.trim());
      setEnvironment(response);
      setEnvironmentId(response.environmentId);
      setSearchParams(
        activeRunId
          ? { environmentId: response.environmentId, runId: activeRunId }
          : { environmentId: response.environmentId },
      );
    } catch (error) {
      setEnvironmentError(
        error instanceof Error ? error.message : 'Failed to load the selected environment.',
      );
      setEnvironment(undefined);
    } finally {
      setEnvironmentLoading(false);
    }
  }

  useEffect(() => {
    // Auto-load the environment carried over via the ?environmentId= deep link so an
    // operator arriving from another page doesn't have to click "Load environment" again.
    if (environmentId.trim()) {
      void handleLoadEnvironment(environmentId.trim());
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    let cancelled = false;

    async function loadPerformanceWorkloads() {
      try {
        const response = await listPerformanceWorkloads();

        if (!cancelled) {
          setPerformanceWorkloads(response.performanceWorkloads);
        }
      } catch {
        if (!cancelled) {
          setPerformanceWorkloads([]);
        }
      }
    }

    void loadPerformanceWorkloads();

    return () => {
      cancelled = true;
    };
  }, []);

  async function handleStartRun() {
    if (!environmentId.trim() || !testDefinitionRef) {
      return;
    }

    setStartingRun(true);
    setRunError(undefined);
    setAcceptedRun(undefined);
    setRunStatus(undefined);

    try {
      const response = await createPerformanceRun(environmentId.trim(), {
        runType,
        testDefinitionRef,
      });
      setAcceptedRun(response);
      setSearchParams({ environmentId: environmentId.trim(), runId: response.runId });
      setHistoryRefreshToken((current) => current + 1);
    } catch (error) {
      setRunError(getPerformanceRunErrorMessage(error, environmentId.trim()));
    } finally {
      setStartingRun(false);
    }
  }

  async function handleCancelRun() {
    if (!environmentId.trim() || !activeRunId) {
      return;
    }

    setCancellingRun(true);
    setRunError(undefined);

    try {
      const response = await cancelPerformanceRun(environmentId.trim(), activeRunId);
      setRunStatus((current) =>
        current
          ? {
              ...current,
              status: response.status,
            }
          : current,
      );
    } catch (error) {
      setRunError(getPerformanceRunErrorMessage(error, environmentId.trim()));
    } finally {
      setCancellingRun(false);
    }
  }

  const displayedStatus = runStatus?.status ?? acceptedRun?.status;
  const reportLink =
    environmentId.trim() && activeRunId
      ? `/performance/report/${activeRunId}?environmentId=${encodeURIComponent(environmentId.trim())}`
      : '';

  return (
    <div className={styles.stack}>
      <PageHeader
        eyebrow="Evaluate"
        title="Measure performance"
        description="Start an industry-standard performance workload against the active deployment and monitor queue state, diagnostics, and terminal outcomes before opening the final metrics report."
      />

      <SectionCard title="1. Active environment">
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
          <Button onClick={() => void handleLoadEnvironment()} disabled={environmentLoading}>
            {environmentLoading ? 'Loading environment…' : 'Reload environment'}
          </Button>
          {environmentId.trim() ? (
            <RouterLink to={`/deploy?environmentId=${environmentId.trim()}`}>Open deploy page</RouterLink>
          ) : null}
        </div>

        {environment ? (
          <InfoGrid>
            <InfoPanel title="Deployment context">
              <DataList
                items={[
                  { label: 'Name', value: environment.name ?? environment.environmentId },
                  { label: 'Lifecycle', value: formatStateLabel(environment.state) },
                  {
                    label: 'Active deployment revision',
                    value: environment.activeDeploymentRevisionId ?? environment.activeRevisionId ?? 'None',
                  },
                  { label: 'Updated', value: formatTimestamp(environment.updatedAt) },
                ]}
              />
            </InfoPanel>
            <InfoPanel title="Performance run guardrails">
              <Body1>
                A run requires an active ready deployment. Only one deployment-affecting operation
                or evaluation can run against the same environment at a time.
              </Body1>
            </InfoPanel>
          </InfoGrid>
        ) : null}
      </SectionCard>

      <SectionCard title="2. Run definition">
        <div className={styles.formGrid}>
          <Field
            label="Performance workload"
            hint={
              performanceWorkloads.length === 0
                ? 'No registered performance workloads found yet — enter a known workload id directly.'
                : undefined
            }
          >
            <Input
              list="performance-workload-options"
              value={workloadId}
              onChange={(event) => setWorkloadId(event.target.value)}
              placeholder="workload-demo-v1"
            />
            <datalist id="performance-workload-options">
              {performanceWorkloads.map((workload) => (
                <option key={workload.workloadId} value={workload.workloadId}>
                  {`v${workload.version} — concurrency ${workload.concurrency}`}
                </option>
              ))}
            </datalist>
          </Field>
        </div>

        <InfoGrid>
          <InfoPanel title="Execution target">
            <Body1 block>
              The workload reference will be recorded against the active deployment revision and
              surfaced again in the final report alongside the measured test conditions.
            </Body1>
            <Body1 block>
              <strong>Reference:</strong> {testDefinitionRef || 'Enter a workload id'}
            </Body1>
          </InfoPanel>
          <InfoPanel title="Recorded conditions">
            <Body1>
              Warm-up, input profile, concurrency, duration or request count, safety limits, and
              completion criteria come from the referenced workload definition.
            </Body1>
          </InfoPanel>
        </InfoGrid>

        {runError ? <StatusMessage intent="error">{runError}</StatusMessage> : null}
        <div className={styles.actions}>
          <Button
            appearance="primary"
            onClick={() => void handleStartRun()}
            disabled={!environmentId.trim() || !testDefinitionRef || startingRun}
          >
            {startingRun ? 'Starting run…' : 'Start run'}
          </Button>
        </div>
      </SectionCard>

      <RunHistory
        environmentId={environmentId.trim()}
        runTypes={['performance']}
        reportPathPrefix="/performance/report"
        refreshToken={historyRefreshToken}
      />

      {(acceptedRun || runStatus || activeRunId) && displayedStatus ? (
        <SectionCard title="3. Run progress">
          <InfoGrid>
            <InfoPanel>
              <DataList
                items={[
                  { label: 'Run id', value: activeRunId },
                  { label: 'Run type', value: formatStateLabel(runStatus?.runType ?? acceptedRun?.runType ?? runType) },
                  { label: 'Status', value: formatStateLabel(displayedStatus) },
                  { label: 'Deployment revision', value: runStatus?.deploymentRevisionId ?? acceptedRun?.deploymentRevisionId ?? 'Pending' },
                  {
                    label: 'Model / engine',
                    value: runStatus?.configuration
                      ? `${runStatus.configuration.resolvedCheckpointRef ?? 'n/a'} · ${runStatus.configuration.engineId ?? 'n/a'}`
                      : 'Pending',
                  },
                  {
                    label: 'Progress',
                    value: runStatus
                      ? `${runStatus.progress.completedCases} / ${runStatus.progress.totalCases} cases complete`
                      : 'Waiting for run telemetry…',
                  },
                  { label: 'Started', value: formatTimestamp(runStatus?.startedAt) },
                  { label: 'Ended', value: formatTimestamp(runStatus?.endedAt) },
                ]}
              />
            </InfoPanel>

            <InfoPanel title="Diagnostics">
              {runStatus?.diagnostics.length ? (
                <ul className={styles.diagnosticsLog}>
                  {runStatus.diagnostics.map((diagnostic) => (
                    <li key={`${diagnostic.timestamp}-${diagnostic.message}`}>
                      <StatusBadge tone={statusTone(diagnostic.severity)}>{diagnostic.severity}</StatusBadge>{' '}
                      <Caption1>{formatTimestamp(diagnostic.timestamp)}</Caption1> —{' '}
                      <Body1 as="span">{diagnostic.message}</Body1>
                    </li>
                  ))}
                </ul>
              ) : (
                <Body1>No diagnostics have been emitted yet.</Body1>
              )}
            </InfoPanel>
          </InfoGrid>

          <div className={styles.actions}>
            {isCancelableStatus(runStatus?.status ?? acceptedRun?.status) ? (
              <Button onClick={() => void handleCancelRun()} disabled={cancellingRun}>
                {cancellingRun ? 'Cancelling run…' : 'Cancel run'}
              </Button>
            ) : null}
            {isTerminalStatus(runStatus?.status) && reportLink ? (
              <RouterButton appearance="primary" to={reportLink}>
                Open performance report
              </RouterButton>
            ) : null}
          </div>
        </SectionCard>
      ) : null}
    </div>
  );
}
