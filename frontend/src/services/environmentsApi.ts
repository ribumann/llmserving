import { apiRequest } from './apiClient';
import type {
  AcceptedOperation,
  DemoEnvironment,
  DeploymentConfigurationSummary,
  EnvironmentLifecycleState,
  EnvironmentPreviewRequest,
  EnvironmentPreviewResponse,
  EnvironmentProvisionRequest,
  ListEnvironmentsResponse,
  TeardownPreviewRequest,
  TeardownPreviewResponse,
  TeardownRequest,
  TeardownResult,
} from './types';

export function listEnvironments() {
  return apiRequest<ListEnvironmentsResponse>('/environments');
}

export function previewEnvironment(payload: EnvironmentPreviewRequest) {
  return apiRequest<EnvironmentPreviewResponse>('/environments/preview', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

const settledEnvironmentStates = new Set<EnvironmentLifecycleState>([
  'ready',
  'provisioning_failed',
  'torn_down',
  'teardown_failed',
]);

export function isEnvironmentSettled(state: EnvironmentLifecycleState) {
  return settledEnvironmentStates.has(state);
}

export function provisionEnvironment(payload: EnvironmentProvisionRequest) {
  return apiRequest<AcceptedOperation>('/environments', {
    method: 'POST',
    body: JSON.stringify({
      profileId: payload.profileId,
      region: payload.region,
      configurableInputs: payload.inputs ?? {},
    }),
  });
}

type BackendEnvironment = {
  environmentId: string;
  lifecycleState: EnvironmentLifecycleState;
  activeRevisionId?: string | null;
  providerState?: Record<string, unknown>;
  context?: Record<string, unknown>;
};

export async function getEnvironment(environmentId: string): Promise<DemoEnvironment> {
  const response = await apiRequest<BackendEnvironment>(`/environments/${environmentId}`);
  const context = response.context ?? {};
  const providerState = response.providerState ?? {};

  return {
    environmentId: response.environmentId,
    provider: (context.provider as DemoEnvironment['provider']) ?? 'azure',
    profileId: (context.profileId as string) ?? '',
    region: (context.region as string) ?? 'local',
    state: response.lifecycleState,
    activeRevisionId: response.activeRevisionId ?? null,
    activeDeploymentRevisionId: response.activeRevisionId ?? null,
    activeDeploymentConfiguration:
      (context.activeDeploymentConfiguration as DeploymentConfigurationSummary | null) ?? null,
    resources: Array.isArray(providerState.resources)
      ? (providerState.resources as DemoEnvironment['resources'])
      : [],
  };
}

export function previewTeardown(environmentId: string, payload: TeardownPreviewRequest = {}) {
  return apiRequest<TeardownPreviewResponse>(`/environments/${environmentId}/teardown/preview`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function teardownEnvironment(environmentId: string, payload: TeardownRequest) {
  return apiRequest<TeardownResult>(`/environments/${environmentId}/teardown`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}
