import { useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Body1, Button, Caption1, Field, Input, Select, makeStyles, tokens } from '@fluentui/react-components';
import EnvironmentPicker from '../components/EnvironmentPicker';
import ProvenanceBadge from '../components/ProvenanceBadge';
import RunHistory from '../components/RunHistory';
import { ApiError } from '../services/apiClient';
import { getEnvironment } from '../services/environmentsApi';
import {
  cancelQualityRun,
  createQualityRun,
  getQualityRun,
  listBenchmarkDefinitions,
  listGoldenDatasets,
} from '../services/runsApi';
import type {
  CreateQualityRunResponse,
  DemoEnvironment,
  GoldenDatasetSummary,
  QualityRunStatusResponse,
  QualityRunType,
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
  badgeRow: {
    display: 'flex',
    gap: tokens.spacingHorizontalS,
    flexWrap: 'wrap',
  },
  diagnosticsLog: {
    margin: 0,
    paddingLeft: tokens.spacingHorizontalL,
    display: 'flex',
    flexDirection: 'column',
    gap: tokens.spacingVerticalXS,
  },
});

const QUALITY_RUN_POLL_INTERVAL_MS = 2000;
const TERMINAL_RUN_STATUSES = new Set<QualityRunStatusResponse['status']>([
  'completed',
  'cancelled',
  'failed',
  'incomplete',
]);
// Used only if the backend has no registered benchmark definitions yet (e.g. the
// `seed-benchmarks` script has not been run against this environment's database).
const BENCHMARK_OPTIONS_FALLBACK = ['gsm8k', 'ifeval', 'mmlu-5subject-mini'];

function formatTimestamp(value?: string | null) {
  if (!value) {
    return 'n/a';
  }

  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
}

function getQualityRunErrorMessage(error: unknown, environmentId: string) {
  if (error instanceof ApiError) {
    switch (error.code) {
      case 'test_definition_not_found':
        return 'The selected quality definition was not found. Check the dataset or benchmark id and retry.';
      case 'no_ready_deployment':
        return `No ready deployment is active for this environment. Open Deploy to activate one before retrying: /deploy?environmentId=${environmentId}`;
      case 'environment_busy':
        return 'This environment is already busy with another operation. Wait for it to finish, then start the run again.';
      case 'run_type_not_yet_supported':
        return 'This run type has not been enabled in the backend yet.';
      case 'invalid_run_type':
        return 'Select a supported quality run type before starting the run.';
      case 'unreviewed_dataset_rejected':
        return "This dataset hasn't been reviewed yet and can't be used for a run.";
      case 'duplicate_cases_detected':
        return 'This golden dataset contains duplicate cases. Review the dataset registration before retrying.';
      case 'run_not_found':
        return 'The selected run could not be found for this environment.';
      default:
        return error.message;
    }
  }

  return error instanceof Error ? error.message : 'Quality run request failed.';
}

function isTerminalStatus(status?: QualityRunStatusResponse['status']) {
  return status ? TERMINAL_RUN_STATUSES.has(status) : false;
}

function isCancelableStatus(status?: QualityRunStatusResponse['status']) {
  return status === 'queued' || status === 'running';
}

export default function QualityRunPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [environmentId, setEnvironmentId] = useState(searchParams.get('environmentId') ?? '');
  const [environment, setEnvironment] = useState<DemoEnvironment>();
  const [environmentLoading, setEnvironmentLoading] = useState(false);
  const [environmentError, setEnvironmentError] = useState<string>();
  const [runType, setRunType] = useState<QualityRunType>('quality-golden');
  const [goldenDatasetId, setGoldenDatasetId] = useState('');
  const [goldenDatasets, setGoldenDatasets] = useState<GoldenDatasetSummary[]>([]);
  const [benchmarkOptions, setBenchmarkOptions] = useState<string[]>(BENCHMARK_OPTIONS_FALLBACK);
  const [benchmarkId, setBenchmarkId] = useState(BENCHMARK_OPTIONS_FALLBACK[0]);
  const [startingRun, setStartingRun] = useState(false);
  const [runError, setRunError] = useState<string>();
  const [cancellingRun, setCancellingRun] = useState(false);
  const [acceptedRun, setAcceptedRun] = useState<CreateQualityRunResponse>();
  const [runStatus, setRunStatus] = useState<QualityRunStatusResponse>();
  const [historyRefreshToken, setHistoryRefreshToken] = useState(0);

  const activeRunId =
    runStatus?.runId ?? acceptedRun?.runId ?? searchParams.get('runId')?.trim() ?? '';
  const testDefinitionRef = useMemo(
    () => (runType === 'quality-golden' ? goldenDatasetId.trim() : benchmarkId),
    [benchmarkId, goldenDatasetId, runType],
  );

  useEffect(() => {
    if (!environmentId.trim() || !activeRunId || isTerminalStatus(runStatus?.status)) {
      return;
    }

    let active = true;
    let timeoutId: number | undefined;

    const poll = async () => {
      try {
        const nextRun = await getQualityRun(environmentId.trim(), activeRunId);

        if (!active) {
          return;
        }

        setRunStatus(nextRun);

        if (isTerminalStatus(nextRun.status)) {
          return;
        }

        timeoutId = window.setTimeout(poll, QUALITY_RUN_POLL_INTERVAL_MS);
      } catch (error) {
        if (!active) {
          return;
        }

        setRunError(getQualityRunErrorMessage(error, environmentId.trim()));
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
        activeRunId ? { environmentId: response.environmentId, runId: activeRunId } : { environmentId: response.environmentId },
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

    async function loadGoldenDatasets() {
      try {
        const response = await listGoldenDatasets();

        if (!cancelled) {
          setGoldenDatasets(response.goldenDatasets);
        }
      } catch {
        if (!cancelled) {
          setGoldenDatasets([]);
        }
      }
    }

    void loadGoldenDatasets();

    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;

    async function loadBenchmarkDefinitions() {
      try {
        const response = await listBenchmarkDefinitions();

        if (!cancelled && response.benchmarkDefinitions.length > 0) {
          const ids = response.benchmarkDefinitions.map((definition) => definition.benchmarkId);
          setBenchmarkOptions(ids);
          setBenchmarkId((current) => (ids.includes(current) ? current : ids[0]));
        }
      } catch {
        // Keep the fallback options if the catalog listing is unavailable.
      }
    }

    void loadBenchmarkDefinitions();

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
      const response = await createQualityRun(environmentId.trim(), {
        runType,
        testDefinitionRef,
      });
      setAcceptedRun(response);
      setSearchParams({ environmentId: environmentId.trim(), runId: response.runId });
      setHistoryRefreshToken((current) => current + 1);
    } catch (error) {
      setRunError(getQualityRunErrorMessage(error, environmentId.trim()));
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
      const response = await cancelQualityRun(environmentId.trim(), activeRunId);
      setRunStatus((current) =>
        current
          ? {
              ...current,
              status: response.status,
            }
          : current,
      );
    } catch (error) {
      setRunError(getQualityRunErrorMessage(error, environmentId.trim()));
    } finally {
      setCancellingRun(false);
    }
  }

  const displayedStatus = runStatus?.status ?? acceptedRun?.status;
  const reportLink =
    environmentId.trim() && activeRunId
      ? `/quality/report/${activeRunId}?environmentId=${encodeURIComponent(environmentId.trim())}`
      : '';
  const styles = useStyles();

  return (
    <div className={styles.stack}>
      <PageHeader
        eyebrow="Evaluate"
        title="Run a quality evaluation"
        description="Start a curated golden-dataset or short benchmark run against the active deployment and monitor progress, diagnostics, and terminal outcomes."
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
            <InfoPanel title="Quality run guardrails">
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
          <Field label="Run type">
            <Select
              value={runType}
              onChange={(event) => setRunType(event.target.value as QualityRunType)}
            >
              <option value="quality-golden">Golden dataset</option>
              <option value="quality-benchmark">Benchmark suite</option>
            </Select>
          </Field>

          {runType === 'quality-golden' ? (
            <Field
              label="Golden dataset"
              hint={
                goldenDatasets.length === 0
                  ? 'No registered golden datasets found yet — enter a known dataset id directly.'
                  : undefined
              }
            >
              <Input
                list="golden-dataset-options"
                value={goldenDatasetId}
                onChange={(event) => setGoldenDatasetId(event.target.value)}
                placeholder="demo-factual-qa-v1"
              />
              <datalist id="golden-dataset-options">
                {goldenDatasets.map((dataset) => (
                  <option key={dataset.goldenDatasetId} value={dataset.goldenDatasetId}>
                    {`${dataset.name} v${dataset.version} — ${dataset.reviewStatus} (${dataset.caseCount} cases)`}
                  </option>
                ))}
              </datalist>
            </Field>
          ) : (
            <Field label="Benchmark id">
              <Select
                value={benchmarkId}
                onChange={(event) => setBenchmarkId(event.target.value)}
              >
                {benchmarkOptions.map((option) => (
                  <option key={option} value={option}>
                    {option}
                  </option>
                ))}
              </Select>
            </Field>
          )}
        </div>

        {runType === 'quality-golden' ? (
          <InfoGrid>
            <InfoPanel title="Provenance badge legend">
              <div className={styles.badgeRow}>
                <ProvenanceBadge provenance="curated" reviewStatus="reviewed" />
                <ProvenanceBadge provenance="ai-generated" reviewStatus="reviewed" />
                <ProvenanceBadge provenance="ai-generated" reviewStatus="unreviewed" />
              </div>
              <Body1>
                Live dataset provenance metadata is not exposed by a frontend listing endpoint yet,
                so the badge is shown here as the operator legend for reviewed versus unreviewed
                content.
              </Body1>
            </InfoPanel>
            <InfoPanel title="Execution target">
              <Body1 block>
                The selected definition reference will be recorded against the active deployment
                revision and surfaced again in the final report.
              </Body1>
              <Body1 block>
                <strong>Reference:</strong> {testDefinitionRef || 'Select or enter a definition'}
              </Body1>
            </InfoPanel>
          </InfoGrid>
        ) : (
          <Body1>
            Use one of the seeded short benchmark identifiers to verify whether serving changes
            preserved acceptable quality.
          </Body1>
        )}

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
        runTypes={['quality-golden', 'quality-benchmark']}
        reportPathPrefix="/quality/report"
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
                Open quality report
              </RouterButton>
            ) : null}
          </div>
        </SectionCard>
      ) : null}
    </div>
  );
}
