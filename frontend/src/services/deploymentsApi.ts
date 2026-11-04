import { apiRequest } from './apiClient';
import type {
  DeploymentAcceptanceResponse,
  DeploymentRequest,
  DeploymentRevision,
  InferenceConfigurationRequest,
  InferenceConfigurationVersion,
  ListInferenceConfigurationsResponse,
  ListModelConfigurationsResponse,
  ModelConfigurationRequest,
  ModelConfigurationVersion,
  PromptRequest,
  PromptResponse,
} from './types';

export function createModelConfiguration(
  environmentId: string,
  payload: ModelConfigurationRequest,
) {
  return apiRequest<ModelConfigurationVersion>(
    `/environments/${environmentId}/model-configurations`,
    {
      method: 'POST',
      body: JSON.stringify(payload),
    },
  );
}

export function listModelConfigurations(environmentId: string) {
  return apiRequest<ListModelConfigurationsResponse>(
    `/environments/${environmentId}/model-configurations`,
  );
}

export function createInferenceConfiguration(
  environmentId: string,
  payload: InferenceConfigurationRequest,
) {
  return apiRequest<InferenceConfigurationVersion>(
    `/environments/${environmentId}/inference-configurations`,
    {
      method: 'POST',
      body: JSON.stringify(payload),
    },
  );
}

export function listInferenceConfigurations(environmentId: string) {
  return apiRequest<ListInferenceConfigurationsResponse>(
    `/environments/${environmentId}/inference-configurations`,
  );
}

export function createDeployment(environmentId: string, payload: DeploymentRequest) {
  return apiRequest<DeploymentAcceptanceResponse>(`/environments/${environmentId}/deployments`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function getDeploymentRevision(environmentId: string, revisionId: string) {
  return apiRequest<DeploymentRevision>(
    `/environments/${environmentId}/deployments/${revisionId}`,
  );
}

export function submitPrompt(environmentId: string, payload: PromptRequest) {
  return apiRequest<PromptResponse>(`/environments/${environmentId}/prompts`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export const deployRevision = createDeployment;
