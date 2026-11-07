import { useEffect, useState, type ReactNode } from 'react';
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import {
  Button,
  Field,
  Select,
  Text,
  makeStyles,
  tokens,
} from '@fluentui/react-components';
import { SignInLink } from '../components/OperatorAccess';
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
  formatMetricValue,
  formatStateLabel,
  statusTone,
} from '../components/kit';
import {
  publicApi,
  type PublicCatalogEntry,
  type PublicComparison,
  type PublicProfile,
} from '../services/publicApi';
import type {
  BenchmarkDefinitionSummary,
  ComparisonResponse,
  DemoEnvironment,
  DeploymentRevision,
  EnvironmentSummary,
  GoldenDatasetSummary,
  InferenceConfigurationVersion,
  ModelConfigurationVersion,
  PerformanceReportData,
  PerformanceReportResponse,
  PerformanceWorkloadSummary,
  RunSummary,
} from '../services/types';
import type { OperatorSession } from '../services/useOperatorSession';

const useStyles = makeStyles({
  stack: {
    display: 'flex',
    flexDirection: 'column',
    gap: tokens.spacingVerticalL,
  },
  content: { overflowWrap: 'anywhere', minWidth: 0 },
  actions: {
    display: 'flex',
    flexWrap: 'wrap',
    gap: tokens.spacingHorizontalM,
    alignItems: 'center',
  },
});

const VIEWS: Record<string, { title: string; action?: string }> = {
  '/': { title: 'Overview' },
  '/provision': {
    title: 'Provision',
    action: 'Preview capacity and provision',
  },
  '/deploy': { title: 'Deploy', action: 'Save configurations and deploy' },
  '/exercise': { title: 'Exercise', action: 'Send prompt' },
  '/retune': { title: 'Retune', action: 'Save and redeploy' },
  '/quality/run': { title: 'Quality Run', action: 'Submit quality run' },
  '/performance/run': {
    title: 'Performance Run',
    action: 'Submit performance run',
  },
  '/compare': { title: 'Compare', action: 'Create comparison' },
  '/history': { title: 'Experiment History' },
  '/teardown': { title: 'Teardown', action: 'Preview and tear down' },
};

type PublicData = {
  environments: EnvironmentSummary[];
  environment?: DemoEnvironment;
  models?: ModelConfigurationVersion[];
  inference?: InferenceConfigurationVersion[];
  runs?: RunSummary[];
  deployment?: DeploymentRevision;
  report?: PerformanceReportResponse;
  profiles?: PublicProfile[];
  catalog?: PublicCatalogEntry[];
  golden?: GoldenDatasetSummary[];
  benchmarks?: BenchmarkDefinitionSummary[];
  workloads?: PerformanceWorkloadSummary[];
  comparisons?: PublicComparison[];
  comparison?: ComparisonResponse;
};

function valueLabel(value: unknown): string {
  if (value === null || value === undefined) return 'Not available';
  if (typeof value === 'object') {
    if (Array.isArray(value)) return value.map(valueLabel).join(', ');
    return Object.entries(value)
      .map(([key, item]) => `${key}: ${valueLabel(item)}`)
      .join('; ');
  }
  return String(value);
}

function Settings({ values }: { values: Record<string, unknown> }) {
  const entries = Object.entries(values);
  return entries.length ? (
    <DataList
      items={entries.map(([key, value]) => ({
        label: key,
        value: valueLabel(value),
      }))}
    />
  ) : (
    <Text>No public settings recorded.</Text>
  );
}

function formatDistribution(value: unknown, unit: string | undefined) {
  if (
    typeof value !== 'object' ||
    value === null ||
    !('p50' in value) ||
    !('p95' in value) ||
    typeof value.p50 !== 'number' ||
    !Number.isFinite(value.p50) ||
    typeof value.p95 !== 'number' ||
    !Number.isFinite(value.p95)
  ) {
    return null;
  }
  const suffix = unit ?? 'ms';
  return `p50 ${formatMetricValue(value.p50)} ${suffix} · p95 ${formatMetricValue(value.p95)} ${suffix}`;
}

function performanceMetricItems(performance: PerformanceReportData) {
  const { metrics, units } = performance;
  return [
    {
      label: 'Time to first token',
      value: formatDistribution(
        metrics.timeToFirstTokenMs,
        units.timeToFirstTokenMs,
      ),
    },
    {
      label: 'Inter-token latency',
      value: formatDistribution(
        metrics.interTokenLatencyMs,
        units.interTokenLatencyMs,
      ),
    },
    {
      label: 'End-to-end latency',
      value: formatDistribution(
        metrics.endToEndLatencyMs,
        units.endToEndLatencyMs,
      ),
    },
    {
      label: 'Throughput',
      value:
        typeof metrics.throughputTokensPerSec === 'number' &&
        Number.isFinite(metrics.throughputTokensPerSec)
          ? `${formatMetricValue(metrics.throughputTokensPerSec)} ${units.throughputTokensPerSec ?? 'tokens/sec'}`
          : null,
    },
  ].filter(
    (item): item is { label: string; value: string } => item.value !== null,
  );
}

function PerformanceMetricList({
  performance,
}: {
  performance: PerformanceReportData;
}) {
  const items = performanceMetricItems(performance);
  return items.length ? (
    <DataList items={items} />
  ) : (
    <Text>No performance metrics were recorded.</Text>
  );
}

function Records<T>({
  title,
  rows,
  render,
}: {
  title: string;
  rows: T[];
  render: (row: T) => ReactNode;
}) {
  return (
    <SectionCard title={title}>
      {rows.length ? (
        <InfoGrid>
          {rows.map((row, index) => (
            <InfoPanel key={index}>{render(row)}</InfoPanel>
          ))}
        </InfoGrid>
      ) : (
        <EmptyState title={`No ${title.toLowerCase()} recorded`} />
      )}
    </SectionCard>
  );
}

export default function PublicWorkspace({
  session,
  retry,
}: {
  session: OperatorSession;
  retry: () => void;
}) {
  const styles = useStyles();
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const environmentParam = pathname.startsWith('/environments/')
    ? decodeURIComponent(pathname.slice('/environments/'.length))
    : (params.get('environmentId') ?? '');
  const comparisonId = params.get('comparisonId') ?? '';
  const isReport =
    pathname.startsWith('/quality/report/') ||
    pathname.startsWith('/performance/report/');
  const runId = isReport
    ? decodeURIComponent(pathname.split('/').pop() ?? '')
    : '';
  const view = VIEWS[pathname] ?? {
    title: isReport
      ? pathname.startsWith('/quality')
        ? 'Quality Report'
        : 'Performance Report'
      : 'Environment detail',
  };
  const showConfigs =
    !['/', '/provision', '/compare'].includes(pathname) && !isReport;
  const showCatalog = ['/provision', '/deploy', '/retune'].includes(pathname);
  const [data, setData] = useState<PublicData>();
  const [error, setError] = useState<string>();
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setData(undefined);
    setError(undefined);
    async function load() {
      const environments = await publicApi.environments(controller.signal);
      const environmentId =
        environmentParam || environments.environments[0]?.environmentId;
      const result: PublicData = { environments: environments.environments };
      const tasks: Promise<void>[] = [];
      if (
        environmentId &&
        pathname !== '/' &&
        pathname !== '/provision' &&
        pathname !== '/compare'
      ) {
        tasks.push(
          publicApi
            .environment(environmentId, controller.signal)
            .then(async (environment) => {
              result.environment = environment;
              const revision =
                environment.activeDeploymentRevisionId ??
                environment.activeRevisionId;
              if (revision && showConfigs) {
                result.deployment = await publicApi.deployment(
                  environmentId,
                  revision,
                  controller.signal,
                );
              }
            }),
        );
        tasks.push(
          publicApi.runs(environmentId, controller.signal).then((response) => {
            result.runs = response.runs;
          }),
        );
        if (showConfigs) {
          tasks.push(
            publicApi
              .models(environmentId, controller.signal)
              .then((response) => {
                result.models = response.items;
              }),
          );
          tasks.push(
            publicApi
              .inference(environmentId, controller.signal)
              .then((response) => {
                result.inference = response.items;
              }),
          );
        }
        if (isReport && runId) {
          tasks.push(
            publicApi
              .report(environmentId, runId, controller.signal)
              .then((report) => {
                result.report = report;
              }),
          );
        }
      }
      if (showCatalog) {
        tasks.push(
          publicApi.profiles(controller.signal).then((response) => {
            result.profiles = response.profiles;
          }),
        );
        tasks.push(
          publicApi.catalog(controller.signal).then((response) => {
            result.catalog = response.catalog;
          }),
        );
      }
      if (pathname === '/quality/run') {
        tasks.push(
          publicApi.goldenDatasets(controller.signal).then((response) => {
            result.golden = response.goldenDatasets;
          }),
        );
        tasks.push(
          publicApi.benchmarks(controller.signal).then((response) => {
            result.benchmarks = response.benchmarkDefinitions;
          }),
        );
      }
      if (pathname === '/performance/run') {
        tasks.push(
          publicApi.workloads(controller.signal).then((response) => {
            result.workloads = response.performanceWorkloads;
          }),
        );
      }
      if (pathname === '/compare') {
        tasks.push(
          publicApi.comparisons(controller.signal).then((response) => {
            result.comparisons = response.comparisons;
          }),
        );
        if (comparisonId) {
          tasks.push(
            publicApi
              .comparison(comparisonId, controller.signal)
              .then((comparison) => {
                result.comparison = comparison;
              }),
          );
        }
      }
      await Promise.all(tasks);
      if (!controller.signal.aborted) setData(result);
    }
    void load().catch((failure: unknown) => {
      if (!controller.signal.aborted) {
        setError(
          failure instanceof Error
            ? failure.message
            : 'Public data could not be loaded.',
        );
      }
    });
    return () => controller.abort();
  }, [
    pathname,
    environmentParam,
    comparisonId,
    runId,
    isReport,
    showConfigs,
    showCatalog,
    attempt,
  ]);

  const selectedEnvironment =
    environmentParam ||
    data?.environment?.environmentId ||
    data?.environments[0]?.environmentId ||
    '';
  const suffix = `?environmentId=${encodeURIComponent(selectedEnvironment)}`;

  return (
    <section className={`${styles.stack} ${styles.content}`}>
      <PageHeader
        title={view.title}
        description="Browse persisted public summaries. Configuration and actions are read-only until operator access is verified."
      />
      <StatusMessage intent="info" title="Read-only access">
        {session === 'unavailable'
          ? 'Operator sign-in is unavailable. Public data remains accessible; actions stay locked.'
          : session === 'forbidden'
            ? 'This account is not an approved operator. Public browsing is still available.'
            : 'Sign in with an approved Microsoft account to execute actions.'}
        <div className={styles.actions}>
          <SignInLink />
          {session === 'unavailable' ? (
            <Button onClick={retry}>Check access again</Button>
          ) : null}
          {view.action ? <Button disabled>{view.action}</Button> : null}
        </div>
      </StatusMessage>
      <Text size={200}>
        Public summaries exclude credentials, operator identities,
        infrastructure identifiers, private endpoints, diagnostics and raw
        prompt or response content.
      </Text>
      {error ? (
        <StatusMessage intent="error" title="Couldn't load public data">
          {error}{' '}
          <Button onClick={() => setAttempt((current) => current + 1)}>
            Retry public data
          </Button>
        </StatusMessage>
      ) : !data ? (
        <LoadingState label="Loading public data..." />
      ) : (
        <>
          {pathname !== '/' &&
          pathname !== '/compare' &&
          pathname !== '/provision' ? (
            <Field label="Environment">
              <Select
                value={selectedEnvironment}
                onChange={(_, next) => {
                  if (pathname.startsWith('/environments/')) {
                    navigate(`/environments/${encodeURIComponent(next.value)}`);
                  } else if (isReport) {
                    navigate(
                      `/history?environmentId=${encodeURIComponent(next.value)}`,
                    );
                  } else {
                    setParams({ environmentId: next.value });
                  }
                }}
              >
                {!data.environments.length ? (
                  <option value="">No environments recorded</option>
                ) : null}
                {data.environments.map((environment) => (
                  <option
                    key={environment.environmentId}
                    value={environment.environmentId}
                  >
                    {environment.environmentId}
                  </option>
                ))}
              </Select>
            </Field>
          ) : null}
          {pathname === '/' || pathname === '/provision' ? (
            <Records
              title="Environments"
              rows={data.environments}
              render={(environment) => (
                <>
                  <DataList
                    items={[
                      {
                        label: 'Environment',
                        value: environment.environmentId,
                      },
                      { label: 'Profile', value: environment.profileId },
                      { label: 'Provider', value: environment.provider },
                      { label: 'Region', value: environment.region },
                      {
                        label: 'State',
                        value: formatStateLabel(environment.lifecycleState),
                      },
                    ]}
                  />
                  <RouterLink
                    to={`/environments/${encodeURIComponent(environment.environmentId)}`}
                  >
                    View environment
                  </RouterLink>
                  <RouterLink
                    to={`/history?environmentId=${encodeURIComponent(environment.environmentId)}`}
                  >
                    View experiments
                  </RouterLink>
                </>
              )}
            />
          ) : null}
          {data.environment ? (
            <SectionCard title="Environment state">
              <DataList
                items={[
                  {
                    label: 'Environment',
                    value: data.environment.environmentId,
                  },
                  { label: 'Provider', value: data.environment.provider },
                  { label: 'Profile', value: data.environment.profileId },
                  { label: 'Region', value: data.environment.region },
                  {
                    label: 'State',
                    value: (
                      <StatusBadge tone={statusTone(data.environment.state)}>
                        {formatStateLabel(data.environment.state)}
                      </StatusBadge>
                    ),
                  },
                  {
                    label: 'Active deployment revision',
                    value:
                      data.environment.activeDeploymentRevisionId ??
                      data.environment.activeRevisionId ??
                      'None',
                  },
                ]}
              />
              <div className={styles.actions}>
                <RouterLink to={`/deploy${suffix}`}>Configurations</RouterLink>
                <RouterLink to={`/history${suffix}`}>Experiments</RouterLink>
                <RouterLink to={`/quality/run${suffix}`}>
                  Quality definitions
                </RouterLink>
                <RouterLink to={`/performance/run${suffix}`}>
                  Performance workloads
                </RouterLink>
              </div>
            </SectionCard>
          ) : null}
          {data.deployment ? (
            <SectionCard title="Active deployment">
              <DataList
                items={[
                  {
                    label: 'Revision',
                    value: data.deployment.deploymentRevisionId,
                  },
                  { label: 'Engine', value: data.deployment.engineId },
                  {
                    label: 'State',
                    value: formatStateLabel(data.deployment.lifecycleState),
                  },
                  { label: 'Health', value: data.deployment.health.status },
                  {
                    label: 'Model configuration',
                    value: data.deployment.modelConfigId,
                  },
                  {
                    label: 'Inference configuration',
                    value: data.deployment.inferenceConfigId,
                  },
                ]}
              />
            </SectionCard>
          ) : null}
          {data.models ? (
            <Records
              title="Model configurations"
              rows={data.models}
              render={(model) => (
                <>
                  <DataList
                    items={[
                      { label: 'Configuration', value: model.modelConfigId },
                      { label: 'Version', value: model.version },
                      { label: 'Catalog entry', value: model.catalogEntryId },
                      {
                        label: 'Checkpoint',
                        value: model.resolvedCheckpointRef,
                      },
                    ]}
                  />
                  <Settings values={model.modelSettings} />
                </>
              )}
            />
          ) : null}
          {data.inference ? (
            <Records
              title="Inference configurations"
              rows={data.inference}
              render={(inference) => (
                <>
                  <DataList
                    items={[
                      {
                        label: 'Configuration',
                        value: inference.inferenceConfigId,
                      },
                      { label: 'Version', value: inference.version },
                      { label: 'Engine', value: inference.engineId },
                    ]}
                  />
                  <Text weight="semibold">Serving settings</Text>
                  <Settings values={inference.servingSettings} />
                  <Text weight="semibold">Generation settings</Text>
                  <Settings values={inference.generationSettings} />
                </>
              )}
            />
          ) : null}
          {data.profiles ? (
            <Records
              title="Available profiles"
              rows={data.profiles}
              render={(profile) => (
                <DataList
                  items={[
                    { label: 'Profile', value: profile.profileId },
                    { label: 'Provider', value: profile.provider },
                    { label: 'Model size', value: profile.modelSizeClass },
                    { label: 'VM size', value: profile.vmSku },
                    {
                      label: 'Eligible regions',
                      value: profile.eligibleRegions.join(', '),
                    },
                  ]}
                />
              )}
            />
          ) : null}
          {data.catalog ? (
            <Records
              title="Model catalog"
              rows={data.catalog}
              render={(entry) => (
                <DataList
                  items={[
                    { label: 'Model', value: entry.catalogEntryId },
                    { label: 'Family', value: entry.family },
                    { label: 'Size', value: entry.sizeClass },
                    { label: 'Checkpoint', value: entry.checkpointRef },
                    { label: 'License', value: entry.license },
                    { label: 'Gated', value: entry.isGated ? 'Yes' : 'No' },
                    {
                      label: 'Compatible profiles',
                      value: entry.compatibleProfileIds.join(', '),
                    },
                  ]}
                />
              )}
            />
          ) : null}
          {data.golden ? (
            <Records
              title="Golden datasets"
              rows={data.golden}
              render={(dataset) => (
                <DataList
                  items={[
                    { label: 'Definition', value: dataset.goldenDatasetId },
                    { label: 'Version', value: dataset.version },
                    { label: 'Provenance', value: dataset.provenance },
                    { label: 'Review', value: dataset.reviewStatus },
                    { label: 'Case count', value: dataset.caseCount },
                  ]}
                />
              )}
            />
          ) : null}
          {data.benchmarks ? (
            <Records
              title="Benchmark definitions"
              rows={data.benchmarks}
              render={(benchmark) => (
                <DataList
                  items={[
                    { label: 'Benchmark', value: benchmark.benchmarkId },
                    { label: 'Version', value: benchmark.version },
                  ]}
                />
              )}
            />
          ) : null}
          {data.workloads ? (
            <Records
              title="Performance workloads"
              rows={data.workloads}
              render={(workload) => (
                <DataList
                  items={[
                    { label: 'Workload', value: workload.workloadId },
                    { label: 'Version', value: workload.version },
                    { label: 'Concurrency', value: workload.concurrency },
                  ]}
                />
              )}
            />
          ) : null}
          {data.runs ? (
            <Records
              title="Experiments and saved reports"
              rows={data.runs}
              render={(run) => (
                <>
                  <DataList
                    items={[
                      { label: 'Run', value: run.runId },
                      { label: 'Type', value: run.runType },
                      {
                        label: 'Definition',
                        value: run.testDefinitionRef ?? 'Not recorded',
                      },
                      { label: 'Status', value: formatStateLabel(run.status) },
                      { label: 'Started', value: run.startedAt },
                      { label: 'Ended', value: run.endedAt ?? 'Not finished' },
                      {
                        label: 'Deployment revision',
                        value:
                          run.configuration?.deploymentRevisionId ??
                          'Not recorded',
                      },
                    ]}
                  />
                  <RouterLink
                    to={`/${run.runType === 'performance' ? 'performance' : 'quality'}/report/${encodeURIComponent(run.runId)}${suffix}`}
                  >
                    Open report summary
                  </RouterLink>
                </>
              )}
            />
          ) : null}
          {data.report ? (
            <SectionCard title="Saved report summary">
              <DataList
                items={[
                  { label: 'Report', value: data.report.resultReportId },
                  { label: 'Run', value: data.report.runId },
                  {
                    label: 'Completeness',
                    value: data.report.completenessIndicator,
                  },
                  {
                    label: 'Deployment revision',
                    value:
                      data.report.configuration?.deploymentRevisionId ??
                      'Not recorded',
                  },
                ]}
              />
              {data.report.quality?.aggregate ? (
                <Settings values={{ ...data.report.quality.aggregate }} />
              ) : null}
              {data.report.quality?.benchmarks?.map((benchmark) => (
                <DataList
                  key={benchmark.benchmarkId}
                  items={[
                    { label: 'Benchmark', value: benchmark.benchmarkId },
                    { label: 'Score', value: benchmark.score },
                    { label: 'Baseline', value: benchmark.baseline },
                    { label: 'Delta', value: benchmark.delta },
                  ]}
                />
              ))}
              {data.report.performance ? (
                <>
                  <Text weight="semibold">
                    Performance metrics (milliseconds; throughput in
                    tokens/second)
                  </Text>
                  <PerformanceMetricList performance={data.report.performance} />
                  <Text weight="semibold">Request failures</Text>
                  <Settings
                    values={{ ...data.report.performance.requestFailures }}
                  />
                  <Text weight="semibold">Test conditions</Text>
                  <Settings values={data.report.performance.testConditions} />
                </>
              ) : null}
              <Text>
                Raw prompts, outputs and per-case content are operator-only.
              </Text>
            </SectionCard>
          ) : null}
          {data.comparisons ? (
            <Records
              title="Saved comparisons"
              rows={data.comparisons}
              render={(comparison) => (
                <>
                  <DataList
                    items={[
                      { label: 'Comparison', value: comparison.comparisonId },
                      {
                        label: 'Comparability',
                        value: comparison.comparabilityStatus,
                      },
                      {
                        label: 'Reports',
                        value: comparison.reports
                          .map((report) => report.reportId)
                          .join(', '),
                      },
                    ]}
                  />
                  <RouterLink
                    to={`/compare?comparisonId=${encodeURIComponent(comparison.comparisonId)}`}
                  >
                    Open saved comparison
                  </RouterLink>
                </>
              )}
            />
          ) : null}
          {data.comparison ? (
            <SectionCard title="Saved comparison">
              <DataList
                items={[
                  { label: 'Comparison', value: data.comparison.comparisonId },
                  {
                    label: 'Comparability',
                    value: data.comparison.comparabilityStatus,
                  },
                  {
                    label: 'Reasons',
                    value: data.comparison.reasons.join('; ') || 'None',
                  },
                ]}
              />
              {data.comparison.sections.map((section, index) => (
                <div key={index}>
                  <Text weight="semibold">{section.title}</Text>
                  {section.items.map((item, itemIndex) => (
                    <Settings key={itemIndex} values={item} />
                  ))}
                </div>
              ))}
            </SectionCard>
          ) : null}
          {pathname === '/exercise' ? (
            <Text>
              Prompt entry is disabled for visitors. Browse deployment settings
              and prior experiments above.
            </Text>
          ) : null}
          {pathname === '/teardown' ? (
            <Text>
              Teardown previews can access infrastructure and generate work, so
              only operators can request them. Persisted lifecycle state remains
              visible.
            </Text>
          ) : null}
        </>
      )}
    </section>
  );
}
