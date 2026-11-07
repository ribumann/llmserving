import { apiRequest } from './apiClient';
import type {
  BenchmarkDefinitionSummary,
  ComparisonResponse,
  DemoEnvironment,
  DeploymentRevision,
  EnvironmentSummary,
  GoldenDatasetSummary,
  InferenceConfigurationVersion,
  ModelConfigurationVersion,
  PerformanceReportResponse,
  PerformanceWorkloadSummary,
  RequestIdEnvelope,
  RunSummary,
} from './types';

export interface PublicProfile {
  profileId: string;
  provider: string;
  modelSizeClass: string;
  eligibleRegions: string[];
  vmSku: string;
}

export interface PublicCatalogEntry {
  catalogEntryId: string;
  family: string;
  sizeClass: string;
  huggingFaceRepoId: string;
  checkpointRef: string;
  license: string;
  isGated: boolean;
  compatibleProfileIds: string[];
}

export type PublicComparison = Pick<
  ComparisonResponse,
  'comparisonId' | 'comparabilityStatus' | 'reports'
>;

export const publicApi = {
  environments: (signal: AbortSignal) =>
    apiRequest<RequestIdEnvelope & { environments: EnvironmentSummary[] }>(
      '/public/environments',
      { signal },
    ),
  environment: (id: string, signal: AbortSignal) =>
    apiRequest<DemoEnvironment>(
      `/public/environments/${encodeURIComponent(id)}`,
      { signal },
    ),
  models: (id: string, signal: AbortSignal) =>
    apiRequest<RequestIdEnvelope & { items: ModelConfigurationVersion[] }>(
      `/public/environments/${encodeURIComponent(id)}/model-configurations`,
      { signal },
    ),
  inference: (id: string, signal: AbortSignal) =>
    apiRequest<RequestIdEnvelope & { items: InferenceConfigurationVersion[] }>(
      `/public/environments/${encodeURIComponent(id)}/inference-configurations`,
      { signal },
    ),
  runs: (id: string, signal: AbortSignal) =>
    apiRequest<RequestIdEnvelope & { runs: RunSummary[] }>(
      `/public/environments/${encodeURIComponent(id)}/runs`,
      { signal },
    ),
  deployment: (id: string, revision: string, signal: AbortSignal) =>
    apiRequest<DeploymentRevision>(
      `/public/environments/${encodeURIComponent(id)}/deployments/${encodeURIComponent(revision)}`,
      { signal },
    ),
  report: (id: string, run: string, signal: AbortSignal) =>
    apiRequest<PerformanceReportResponse>(
      `/public/environments/${encodeURIComponent(id)}/runs/${encodeURIComponent(run)}/report`,
      { signal },
    ),
  profiles: (signal: AbortSignal) =>
    apiRequest<RequestIdEnvelope & { profiles: PublicProfile[] }>(
      '/public/profiles',
      { signal },
    ),
  catalog: (signal: AbortSignal) =>
    apiRequest<RequestIdEnvelope & { catalog: PublicCatalogEntry[] }>(
      '/public/catalog',
      { signal },
    ),
  goldenDatasets: (signal: AbortSignal) =>
    apiRequest<RequestIdEnvelope & { goldenDatasets: GoldenDatasetSummary[] }>(
      '/public/golden-datasets',
      { signal },
    ),
  benchmarks: (signal: AbortSignal) =>
    apiRequest<
      RequestIdEnvelope & { benchmarkDefinitions: BenchmarkDefinitionSummary[] }
    >('/public/benchmark-definitions', { signal }),
  workloads: (signal: AbortSignal) =>
    apiRequest<
      RequestIdEnvelope & { performanceWorkloads: PerformanceWorkloadSummary[] }
    >('/public/performance-workloads', { signal }),
  comparisons: (signal: AbortSignal) =>
    apiRequest<RequestIdEnvelope & { comparisons: PublicComparison[] }>(
      '/public/comparisons',
      { signal },
    ),
  comparison: (id: string, signal: AbortSignal) =>
    apiRequest<ComparisonResponse>(
      `/public/comparisons/${encodeURIComponent(id)}`,
      { signal },
    ),
};
