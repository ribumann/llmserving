export type RequestIdEnvelope = {
  requestId: string;
};

export type ApiErrorShape = RequestIdEnvelope & {
  error: {
    code: string;
    message: string;
    details?: unknown;
  };
};

export type OperationStatus =
  | 'queued'
  | 'running'
  | 'completed'
  | 'cancelled'
  | 'failed'
  | 'incomplete';

export type EnvironmentLifecycleState =
  | 'not_provisioned'
  | 'provisioning'
  | 'ready'
  | 'provisioning_failed'
  | 'tearing_down'
  | 'torn_down'
  | 'teardown_failed';

export type ExperimentRunType = 'quality-golden' | 'quality-benchmark' | 'performance';

export type ProviderName = 'azure' | 'local';

export interface Diagnostic {
  code: string;
  message: string;
  severity?: 'info' | 'warning' | 'error';
  details?: Record<string, unknown>;
}

export interface CloudDeploymentProfile {
  id: string;
  name: string;
  provider: ProviderName;
  sizeClass: 'small' | 'medium' | 'large';
  description: string;
  expectedModelClass: string;
  regions: string[];
  resourceAssumptions: string[];
  capacityRequirements: string[];
  configurableInputs: Array<{
    name: string;
    type: 'string' | 'number' | 'boolean' | 'enum';
    required: boolean;
    defaultValue?: string | number | boolean;
    options?: string[];
    description?: string;
  }>;
  knownLimitations: string[];
}

export interface ModelCatalogEntry {
  id: string;
  family: string;
  sizeClass: 'small' | 'medium' | 'large';
  huggingFaceRepo: string;
  checkpoint: string;
  license: string;
  gated: boolean;
  languageCoverage: string[];
  compatibleProfileIds: string[];
  demonstrationValue?: string;
  evaluationLimitations?: string[];
}

export interface RegionAssessment {
  region: string;
  quotaStatus: 'sufficient' | 'insufficient' | 'unknown';
  capacityStatus: 'available' | 'constrained' | 'unknown';
  compatibilityStatus: 'compatible' | 'incompatible' | 'unknown';
  checkedAt: string;
  evidence: string[];
  uncertainty?: string;
}

export interface EnvironmentPreviewRequest {
  profileId: string;
  regionOverride?: string;
  configurableInputs?: Record<string, string | number | boolean | null>;
}

export interface EnvironmentPreviewResponse extends RequestIdEnvelope {
  profileId: string;
  recommendedRegion: string;
  assessments: RegionAssessment[];
  advisoryMessage?: string;
}

export interface DemoEnvironmentResource {
  name: string;
  type: string;
  state: string;
  summary?: string;
}

export interface CapacityContext {
  region: string;
  assessedAt: string;
  quotaStatus: string;
  capacityStatus: string;
  notes: string[];
}

export interface CostContext {
  estimatedHourlyUsd?: number;
  notes?: string[];
}

/**
 * Human-readable model/engine/settings detail for the deployment revision
 * currently active on an environment or that produced a given run's result,
 * so operators don't have to cross-reference bare ids to understand what
 * configuration is running.
 */
export interface DeploymentConfigurationSummary {
  deploymentRevisionId?: string | null;
  lifecycleState?: string | null;
  engineId?: string | null;
  catalogEntryId?: string | null;
  resolvedCheckpointRef?: string | null;
  modelSettings?: Record<string, unknown>;
  servingSettings?: Record<string, unknown>;
  generationSettings?: Record<string, unknown>;
}

export interface DemoEnvironment {
  environmentId: string;
  name?: string;
  provider: ProviderName;
  profileId: string;
  region: string;
  state: EnvironmentLifecycleState;
  activeOperationId?: string | null;
  activeDeploymentRevisionId?: string | null;
  activeDeploymentConfiguration?: DeploymentConfigurationSummary | null;
  activeRevisionId?: string | null;
  resources: DemoEnvironmentResource[];
  capacityContext?: CapacityContext;
  costContext?: CostContext;
  createdAt?: string;
  updatedAt?: string;
}

export interface EnvironmentSummary {
  environmentId: string;
  name?: string;
  profileId: string;
  provider: ProviderName;
  region: string;
  lifecycleState: EnvironmentLifecycleState;
  activeOperationId?: string | null;
  activeDeploymentRevisionId?: string | null;
  activeDeploymentConfiguration?: DeploymentConfigurationSummary | null;
  createdAt?: string;
  updatedAt?: string;
}

export interface ListEnvironmentsResponse extends RequestIdEnvelope {
  environments: EnvironmentSummary[];
}

export interface GoldenDatasetSummary {
  goldenDatasetId: string;
  name: string;
  version: number;
  provenance: string;
  reviewStatus: string;
  caseCount: number;
}

export interface ListGoldenDatasetsResponse extends RequestIdEnvelope {
  goldenDatasets: GoldenDatasetSummary[];
}

export interface BenchmarkDefinitionSummary {
  benchmarkId: string;
  version: string;
}

export interface ListBenchmarkDefinitionsResponse extends RequestIdEnvelope {
  benchmarkDefinitions: BenchmarkDefinitionSummary[];
}

export interface PerformanceWorkloadSummary {
  workloadId: string;
  version: number;
  concurrency: number;
}

export interface ListPerformanceWorkloadsResponse extends RequestIdEnvelope {
  performanceWorkloads: PerformanceWorkloadSummary[];
}

export interface RunSummary {
  runId: string;
  runType: ExperimentRunType;
  testDefinitionRef?: string | null;
  status: OperationStatus;
  startedAt: string;
  endedAt?: string | null;
  configuration?: DeploymentConfigurationSummary;
}

export interface ListRunsResponse extends RequestIdEnvelope {
  runs: RunSummary[];
}

export interface EnvironmentProvisionRequest {
  profileId: string;
  region: string;
  name?: string;
  inputs?: Record<string, string | number | boolean | null>;
}

export interface AcceptedOperation extends RequestIdEnvelope {
  operationId: string;
  phase: string;
  status: Extract<OperationStatus, 'queued' | 'running'>;
  environmentId?: string;
  runId?: string;
  message?: string;
}

export interface TeardownPreviewRequest {
  preservationMode?: 'retain' | 'export';
}

export interface TeardownPreviewResponse extends RequestIdEnvelope {
  previewToken: string;
  resources: Array<{
    id: string;
    name: string;
    type: string;
    consequence: 'remove' | 'retain' | 'export';
    notes?: string[];
  }>;
  consequences: string[];
}

export interface TeardownRequest {
  previewToken: string;
  confirmationText: string;
  preservationMode?: 'retain' | 'export';
}

export interface TeardownResult extends RequestIdEnvelope {
  operationId: string;
  phase: string;
  status: OperationStatus;
  resourceOutcomes: Array<{
    id: string;
    name: string;
    outcome: 'removed' | 'retained' | 'failed';
    detail?: string;
  }>;
}

export interface ModelConfigurationRequest {
  catalogEntryId: string;
  resolvedCheckpointRef: string;
  modelSettings: Record<string, unknown>;
}

export interface ModelConfigurationVersion extends RequestIdEnvelope {
  modelConfigId: string;
  catalogEntryId: string;
  resolvedCheckpointRef: string;
  modelSettings: Record<string, unknown>;
  version: number;
  createdAt: string;
}

export interface ListModelConfigurationsResponse extends RequestIdEnvelope {
  items: ModelConfigurationVersion[];
}

export interface InferenceConfigurationRequest {
  engineId: string;
  servingSettings: Record<string, unknown>;
  generationSettings: Record<string, unknown>;
}

export interface InferenceConfigurationVersion extends RequestIdEnvelope {
  inferenceConfigId: string;
  engineId: string;
  servingSettings: Record<string, unknown>;
  generationSettings: Record<string, unknown>;
  version: number;
  createdAt: string;
}

export interface ListInferenceConfigurationsResponse extends RequestIdEnvelope {
  items: InferenceConfigurationVersion[];
}

export interface DeploymentRequest {
  modelConfigId: string;
  inferenceConfigId: string;
  huggingFaceToken?: string;
}

export type DeploymentLifecycleState =
  | 'pending'
  | 'deploying'
  | 'ready'
  | 'deployment_failed'
  | 'superseded';

export type DeploymentHealthStatus = 'healthy' | 'degraded' | 'unhealthy' | 'unknown';

export interface DeploymentAcceptanceResponse extends RequestIdEnvelope {
  operationId: string;
  deploymentRevisionId: string;
  phase: 'accepted';
  lifecycleState: 'deploying';
}

export interface DeploymentRevision extends RequestIdEnvelope {
  deploymentRevisionId: string;
  environmentId: string;
  modelConfigId: string;
  inferenceConfigId: string;
  engineId: string;
  lifecycleState: DeploymentLifecycleState;
  activePeriod: {
    startedAt: string | null;
    endedAt: string | null;
  };
  health: {
    status: DeploymentHealthStatus;
    diagnostics: string[];
  };
  createdAt: string;
  configuration?: DeploymentConfigurationSummary;
}

export interface PromptRequest {
  prompt: string;
  parameters: Record<string, unknown>;
}

export interface PromptResponse extends RequestIdEnvelope {
  deploymentRevisionId: string;
  responseText: string;
  timing: {
    ttftMs: number;
    interTokenLatencyMsAvg: number;
    totalLatencyMs: number;
  };
  activeRevision: {
    deploymentRevisionId: string;
    modelConfigId: string;
    inferenceConfigId: string;
  };
}

export type QualityRunType = Extract<ExperimentRunType, 'quality-golden' | 'quality-benchmark'>;
export type PerformanceRunType = Extract<ExperimentRunType, 'performance'>;

export type GoldenDatasetProvenance = 'curated' | 'ai-generated';

export type GoldenDatasetReviewStatus = 'reviewed' | 'unreviewed';

export interface RegisteredGoldenDataset {
  goldenDatasetId: string;
  name: string;
  version: number;
  provenance: GoldenDatasetProvenance;
  reviewStatus: GoldenDatasetReviewStatus;
}

export interface CreateQualityRunRequest {
  runType: QualityRunType;
  testDefinitionRef: string;
}

export interface CreateQualityRunResponse extends RequestIdEnvelope {
  runId: string;
  runType: QualityRunType;
  status: 'queued';
  deploymentRevisionId: string;
}

export interface CreatePerformanceRunRequest {
  runType: PerformanceRunType;
  testDefinitionRef: string;
}

export interface CreatePerformanceRunResponse extends RequestIdEnvelope {
  runId: string;
  runType: PerformanceRunType;
  status: QualityRunStatusResponse['status'];
  deploymentRevisionId: string;
}

export interface QualityRunDiagnostic {
  timestamp: string;
  severity: 'info' | 'warning' | 'error';
  message: string;
}

export interface QualityRunProgress {
  totalCases: number;
  completedCases: number;
}

export interface QualityRunStatusResponse extends RequestIdEnvelope {
  runId: string;
  environmentId: string;
  deploymentRevisionId: string;
  runType: QualityRunType;
  testDefinitionRef: string;
  status: OperationStatus;
  startedAt: string;
  endedAt: string | null;
  diagnostics: QualityRunDiagnostic[];
  progress: QualityRunProgress;
  configuration?: DeploymentConfigurationSummary;
}

export type PerformanceRunStatusResponse = Omit<QualityRunStatusResponse, 'runType'> & {
  runType: PerformanceRunType;
};

export interface RunCancellationRequest {
  requestedAt: string;
  requestedBy: string;
}

export interface CancelQualityRunResponse extends RequestIdEnvelope {
  runId: string;
  status: OperationStatus;
  cancellationRequests: RunCancellationRequest[];
}

export type QualityCaseStatus = 'passed' | 'failed' | 'errored' | 'skipped' | 'incomplete';

export interface QualityCaseResult {
  caseId: string;
  input: string;
  evaluationRule: string;
  observedOutcome: string;
  status: QualityCaseStatus;
}

export interface QualityAggregate {
  totalCases: number;
  passed: number;
  failed: number;
  errored: number;
  skipped: number;
  incomplete: number;
  passRate: number;
}

export interface QualityBenchmarkResult {
  benchmarkId: string;
  version: string;
  score: number;
  baseline: number;
  delta: number;
  passFail: 'pass' | 'fail';
  regressionFlag: boolean;
}

export interface QualityReportResponse extends RequestIdEnvelope {
  resultReportId: string;
  runId: string;
  completenessIndicator: 'complete' | 'partial' | 'unavailable-monitoring-data';
  quality: {
    cases: QualityCaseResult[];
    aggregate: QualityAggregate;
    benchmarks: QualityBenchmarkResult[];
  };
  performance: null;
  referenceExecutionProfileRef: string | null;
  configuration?: DeploymentConfigurationSummary;
}

export interface PerformanceMetricDistribution {
  p50: number;
  p95: number;
}

export interface PerformanceRequestFailures {
  count: number;
  total: number;
  rate: number;
}

export interface PerformanceAcceleratorUtilization {
  available: boolean;
  details?: Record<string, number> | null;
}

export interface PerformanceReportMetrics {
  timeToFirstTokenMs: PerformanceMetricDistribution;
  interTokenLatencyMs: PerformanceMetricDistribution;
  endToEndLatencyMs: PerformanceMetricDistribution;
  throughputTokensPerSec: number;
}

export interface PerformanceReportData {
  metrics: PerformanceReportMetrics;
  requestFailures: PerformanceRequestFailures;
  units: Record<string, string>;
  testConditions: Record<string, unknown>;
  acceleratorUtilization: PerformanceAcceleratorUtilization;
  runner: string;
}

export interface PerformanceReportResponse extends RequestIdEnvelope {
  resultReportId: string;
  runId: string;
  completenessIndicator: QualityReportResponse['completenessIndicator'];
  quality: QualityReportResponse['quality'];
  performance: PerformanceReportData | null;
  referenceExecutionProfileRef: string | null;
  configuration?: DeploymentConfigurationSummary;
}

export interface CreateComparisonRequest {
  reportIds: string[];
  title?: string;
}

export interface ComparisonResponse extends RequestIdEnvelope {
  comparisonId: string;
  comparabilityStatus: 'comparable' | 'not-directly-comparable';
  reasons: string[];
  reports: Array<{
    reportId: string;
    revisionId?: string;
    environmentId?: string;
  }>;
  sections: Array<{
    title: string;
    items: Array<Record<string, unknown>>;
  }>;
}
