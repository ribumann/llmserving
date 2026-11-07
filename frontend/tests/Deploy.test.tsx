import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import DeployPage from '../src/pages/Deploy';
import { listCatalog } from '../src/services/catalogApi';
import {
  createDeployment,
  createInferenceConfiguration,
  createModelConfiguration,
  getDeploymentRevision,
  listInferenceConfigurations,
  listModelConfigurations,
} from '../src/services/deploymentsApi';
import { getEnvironment, listEnvironments } from '../src/services/environmentsApi';

vi.mock('../src/services/catalogApi', () => ({
  listCatalog: vi.fn(),
}));

vi.mock('../src/services/deploymentsApi', () => ({
  createModelConfiguration: vi.fn(),
  listModelConfigurations: vi.fn(),
  createInferenceConfiguration: vi.fn(),
  listInferenceConfigurations: vi.fn(),
  createDeployment: vi.fn(),
  getDeploymentRevision: vi.fn(),
}));

vi.mock('../src/services/environmentsApi', () => ({
  getEnvironment: vi.fn(),
  listEnvironments: vi.fn(),
}));

const mockedListCatalog = vi.mocked(listCatalog);
const mockedGetEnvironment = vi.mocked(getEnvironment);
const mockedListEnvironments = vi.mocked(listEnvironments);
const mockedCreateModelConfiguration = vi.mocked(createModelConfiguration);
const mockedListModelConfigurations = vi.mocked(listModelConfigurations);
const mockedCreateInferenceConfiguration = vi.mocked(createInferenceConfiguration);
const mockedListInferenceConfigurations = vi.mocked(listInferenceConfigurations);
const mockedCreateDeployment = vi.mocked(createDeployment);
const mockedGetDeploymentRevision = vi.mocked(getDeploymentRevision);

describe('DeployPage', () => {
  beforeEach(() => {
    mockedListCatalog.mockResolvedValue({
      requestId: 'req-catalog',
      entries: [
        {
          id: 'llama-7b',
          family: 'Llama',
          sizeClass: 'medium',
          huggingFaceRepo: 'meta-llama/Llama-3.1-8B-Instruct',
          checkpoint: 'main',
          license: 'Custom',
          gated: true,
          languageCoverage: ['en'],
          compatibleProfileIds: ['azure-single-gpu-7b'],
          demonstrationValue: 'Balanced demo checkpoint.',
        },
      ],
    });

    mockedGetEnvironment.mockResolvedValue({
      environmentId: 'env-123',
      name: 'demo-ready',
      provider: 'azure',
      profileId: 'azure-single-gpu-7b',
      region: 'southcentralus',
      state: 'ready',
      activeOperationId: null,
      activeDeploymentRevisionId: 'rev-old',
      resources: [],
      createdAt: '2026-08-19T09:31:00Z',
      updatedAt: '2026-08-19T09:33:00Z',
    });

    mockedListEnvironments.mockResolvedValue({
      requestId: 'req-environments',
      environments: [
        {
          environmentId: 'env-123',
          profileId: 'azure-single-gpu-7b',
          provider: 'azure',
          region: 'southcentralus',
          lifecycleState: 'ready',
          activeOperationId: null,
        },
      ],
    });

    mockedCreateModelConfiguration.mockResolvedValue({
      requestId: 'req-model-config',
      modelConfigId: 'model-config-001',
      catalogEntryId: 'llama-7b',
      resolvedCheckpointRef: 'refs/pr/12/head',
      modelSettings: {
        maxContextLength: 8192,
      },
      version: 3,
      createdAt: '2026-08-19T09:40:00Z',
    });

    mockedCreateInferenceConfiguration.mockResolvedValue({
      requestId: 'req-inference-config',
      inferenceConfigId: 'inference-config-001',
      engineId: 'vllm',
      servingSettings: {
        gpu_memory_utilization: 0.9,
        max_model_len: 8192,
      },
      generationSettings: {
        temperature: 0.2,
        top_p: 0.95,
        max_tokens: 512,
      },
      version: 4,
      createdAt: '2026-08-19T09:41:00Z',
    });

    mockedListModelConfigurations.mockResolvedValue({
      requestId: 'req-model-history',
      items: [],
    });

    mockedListInferenceConfigurations.mockResolvedValue({
      requestId: 'req-inference-history',
      items: [],
    });

    mockedCreateDeployment.mockResolvedValue({
      requestId: 'req-deploy',
      operationId: 'op-123',
      deploymentRevisionId: 'rev-001',
      phase: 'accepted',
      lifecycleState: 'deploying',
    });

    mockedGetDeploymentRevision.mockResolvedValue({
      requestId: 'req-revision',
      deploymentRevisionId: 'rev-001',
      environmentId: 'env-123',
      modelConfigId: 'model-config-001',
      inferenceConfigId: 'inference-config-001',
      engineId: 'vllm',
      lifecycleState: 'ready',
      activePeriod: {
        startedAt: '2026-08-19T09:45:00Z',
        endedAt: null,
      },
      health: {
        status: 'healthy',
        diagnostics: ['Readiness probe passed.'],
      },
      createdAt: '2026-08-19T09:44:00Z',
    });
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it('creates configurations, deploys them, and shows ready health', async () => {
    const user = userEvent.setup();

    render(
      <MemoryRouter initialEntries={['/deploy?environmentId=env-123']}>
        <DeployPage />
      </MemoryRouter>,
    );

    // The environment auto-loads from the ?environmentId= deep link on mount.
    await waitFor(() => {
      expect(mockedGetEnvironment).toHaveBeenCalledWith('env-123');
      expect(mockedListCatalog).toHaveBeenCalledTimes(1);
    });

    await user.selectOptions(screen.getByRole('combobox', { name: /catalog entry/i }), 'llama-7b');
    await user.clear(screen.getByRole('textbox', { name: /resolved checkpoint ref/i }));
    await user.type(screen.getByRole('textbox', { name: /resolved checkpoint ref/i }), 'refs/pr/12/head');
    await user.click(screen.getByRole('button', { name: /create model configuration/i }));
    await waitFor(() => {
      expect(mockedCreateModelConfiguration).toHaveBeenCalledWith('env-123', {
        catalogEntryId: 'llama-7b',
        resolvedCheckpointRef: 'refs/pr/12/head',
        modelSettings: {
          maxContextLength: 8192,
        },
      });
    });

    await user.click(screen.getByRole('button', { name: /create inference configuration/i }));
    await waitFor(() => {
      expect(mockedCreateInferenceConfiguration).toHaveBeenCalledWith('env-123', {
        engineId: 'vllm',
        servingSettings: {
          gpu_memory_utilization: 0.9,
          max_model_len: 8192,
        },
        generationSettings: {
          temperature: 0.2,
          top_p: 0.95,
          max_tokens: 512,
        },
      });
    });

    expect(mockedCreateDeployment).not.toHaveBeenCalled();
    expect(
      screen.getAllByText(/saving creates a new immutable configuration version/i),
    ).toHaveLength(1);
    expect(
      screen.getByText(/traffic changes only when you deploy the selected versions/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/only catalog entries compatible/i)).toBeInTheDocument();

    await user.type(screen.getByLabelText(/hugging face token/i), 'hf-secret-token');
    await user.click(screen.getByRole('button', { name: /deploy selected revision/i }));

    await waitFor(() => {
      expect(mockedCreateDeployment).toHaveBeenCalledWith('env-123', {
        modelConfigId: 'model-config-001',
        inferenceConfigId: 'inference-config-001',
        huggingFaceToken: 'hf-secret-token',
      });
      expect(mockedGetDeploymentRevision).toHaveBeenCalledWith('env-123', 'rev-001');
    });

    expect(await screen.findByText(/deployment ready/i)).toBeInTheDocument();
    expect(screen.getByText(/readiness probe passed/i)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /open exercise console/i })).toHaveAttribute(
      'href',
      '/exercise?environmentId=env-123',
    );
    expect(screen.getByLabelText(/hugging face token/i)).toHaveValue('');
  });
});
