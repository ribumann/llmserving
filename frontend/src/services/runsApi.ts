import { apiRequest } from './apiClient';
import type {
  CancelQualityRunResponse,
  CreatePerformanceRunRequest,
  CreatePerformanceRunResponse,
  CreateQualityRunRequest,
  CreateQualityRunResponse,
  ListBenchmarkDefinitionsResponse,
  ListGoldenDatasetsResponse,
  ListPerformanceWorkloadsResponse,
  ListRunsResponse,
  PerformanceReportResponse,
  PerformanceRunStatusResponse,
  QualityReportResponse,
  QualityRunStatusResponse,
} from './types';

export function listRuns(environmentId: string) {
  return apiRequest<ListRunsResponse>(`/environments/${environmentId}/runs`);
}

export function listGoldenDatasets() {
  return apiRequest<ListGoldenDatasetsResponse>('/golden-datasets');
}

export function listBenchmarkDefinitions() {
  return apiRequest<ListBenchmarkDefinitionsResponse>('/benchmark-definitions');
}

export function listPerformanceWorkloads() {
  return apiRequest<ListPerformanceWorkloadsResponse>('/performance-workloads');
}

export function createQualityRun(environmentId: string, payload: CreateQualityRunRequest) {
  return apiRequest<CreateQualityRunResponse>(`/environments/${environmentId}/runs`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function getQualityRun(environmentId: string, runId: string) {
  return apiRequest<QualityRunStatusResponse>(`/environments/${environmentId}/runs/${runId}`);
}

export function cancelQualityRun(environmentId: string, runId: string) {
  return apiRequest<CancelQualityRunResponse>(
    `/environments/${environmentId}/runs/${runId}/cancel`,
    {
      method: 'POST',
    },
  );
}

export function getQualityRunReport(environmentId: string, runId: string) {
  return apiRequest<QualityReportResponse>(`/environments/${environmentId}/runs/${runId}/report`);
}

export function createPerformanceRun(environmentId: string, payload: CreatePerformanceRunRequest) {
  return apiRequest<CreatePerformanceRunResponse>(`/environments/${environmentId}/runs`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function getPerformanceRun(environmentId: string, runId: string) {
  return apiRequest<PerformanceRunStatusResponse>(`/environments/${environmentId}/runs/${runId}`);
}

export function cancelPerformanceRun(environmentId: string, runId: string) {
  return apiRequest<CancelQualityRunResponse>(
    `/environments/${environmentId}/runs/${runId}/cancel`,
    {
      method: 'POST',
    },
  );
}

export function getPerformanceRunReport(environmentId: string, runId: string) {
  return apiRequest<PerformanceReportResponse>(`/environments/${environmentId}/runs/${runId}/report`);
}
