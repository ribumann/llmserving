import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import ProvisionPage from '../src/pages/Provision';
import { listCatalog, listProfiles } from '../src/services/catalogApi';
import {
  getEnvironment,
  previewEnvironment,
  provisionEnvironment,
} from '../src/services/environmentsApi';

vi.mock('../src/services/catalogApi', () => ({
  listProfiles: vi.fn(),
  listCatalog: vi.fn(),
}));

vi.mock('../src/services/environmentsApi', async () => {
  const actual = await vi.importActual<typeof import('../src/services/environmentsApi')>(
    '../src/services/environmentsApi',
  );

  return {
    ...actual,
    previewEnvironment: vi.fn(),
    provisionEnvironment: vi.fn(),
    getEnvironment: vi.fn(),
  };
});

const mockedListProfiles = vi.mocked(listProfiles);
const mockedListCatalog = vi.mocked(listCatalog);
const mockedPreviewEnvironment = vi.mocked(previewEnvironment);
const mockedProvisionEnvironment = vi.mocked(provisionEnvironment);
const mockedGetEnvironment = vi.mocked(getEnvironment);

describe('ProvisionPage', () => {
  beforeEach(() => {
    mockedListProfiles.mockResolvedValue({
      requestId: 'req-profiles',
      profiles: [
        {
          id: 'azure-single-gpu-7b',
          name: 'Azure single GPU 7B',
          provider: 'azure',
          sizeClass: 'medium',
          description: 'Single GPU Azure profile for 7B checkpoints.',
          expectedModelClass: '7B',
          regions: ['eastus', 'southcentralus', 'italynorth'],
          resourceAssumptions: ['1x Standard_NC24ads_A100_v4'],
          capacityRequirements: ['GPU quota'],
          configurableInputs: [
            {
              name: 'enableMonitoring',
              type: 'boolean',
              required: false,
              defaultValue: true,
              description: 'Enable Azure Monitor.',
            },
            { name: 'vmSizeOverride', type: 'string', required: false, defaultValue: '' },
            {
              name: 'vmPriority',
              type: 'enum',
              required: true,
              defaultValue: 'Spot',
              options: ['Spot', 'Regular'],
            },
          ],
          knownLimitations: ['Depends on GPU capacity in-region.'],
        },
      ],
    });

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

    mockedPreviewEnvironment.mockResolvedValue({
      requestId: 'req-preview',
      profileId: 'azure-single-gpu-7b',
      recommendedRegion: 'southcentralus',
      advisoryMessage: 'Capacity is healthier in southcentralus.',
      assessments: [
        {
          region: 'eastus',
          quotaStatus: 'sufficient',
          capacityStatus: 'constrained',
          compatibilityStatus: 'compatible',
          checkedAt: '2026-08-19T09:30:00Z',
          evidence: ['Observed recent allocation pressure.'],
          uncertainty: 'Real-time capacity may still fluctuate.',
        },
        {
          region: 'southcentralus',
          quotaStatus: 'sufficient',
          capacityStatus: 'available',
          compatibilityStatus: 'compatible',
          checkedAt: '2026-08-19T09:30:00Z',
          evidence: ['Latest SKU signal shows capacity.'],
        },
      ],
    });

    mockedProvisionEnvironment.mockResolvedValue({
      requestId: 'req-provision',
      operationId: 'op-123',
      phase: 'provisioning',
      status: 'queued',
      environmentId: 'env-123',
      message: 'Terraform apply queued.',
    });

    mockedGetEnvironment.mockResolvedValue({
      environmentId: 'env-123',
      name: 'azure-llm-demo',
      provider: 'azure',
      profileId: 'azure-single-gpu-7b',
      region: 'southcentralus',
      state: 'ready',
      activeOperationId: null,
      activeRevisionId: null,
      resources: [
        {
          name: 'gpu-vm',
          type: 'virtualMachine',
          state: 'ready',
          summary: 'Provisioned successfully.',
        },
      ],
      capacityContext: {
        region: 'southcentralus',
        assessedAt: '2026-08-19T09:30:00Z',
        quotaStatus: 'sufficient',
        capacityStatus: 'available',
        notes: ['Used recommended fallback region southcentralus.'],
      },
      createdAt: '2026-08-19T09:31:00Z',
      updatedAt: '2026-08-19T09:33:00Z',
    });
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it('loads profiles, previews capacity, confirms provisioning, and shows ready progress', async () => {
    const user = userEvent.setup();

    render(
      <MemoryRouter>
        <ProvisionPage />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(mockedListProfiles).toHaveBeenCalledTimes(1);
      expect(mockedListCatalog).toHaveBeenCalledTimes(1);
    });

    await user.selectOptions(
      await screen.findByRole('combobox', { name: /cloud deployment profile/i }),
      'azure-single-gpu-7b',
    );
    await user.selectOptions(
      screen.getByRole('combobox', { name: /model catalog entry/i }),
      'llama-7b',
    );

    await user.click(screen.getByRole('button', { name: /preview region recommendation/i }));

    expect(mockedPreviewEnvironment).toHaveBeenCalledWith({
      profileId: 'azure-single-gpu-7b',
      regionOverride: undefined,
      configurableInputs: { enableMonitoring: true, vmSizeOverride: null, vmPriority: 'Spot' },
    });

    expect(await screen.findByText(/recommended region:/i)).toBeInTheDocument();
    expect(screen.getByText(/capacity is healthier in southcentralus/i)).toBeInTheDocument();
    expect(screen.getByText(/real-time capacity may still fluctuate/i)).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /confirm provisioning/i }));

    await waitFor(() => {
      expect(mockedProvisionEnvironment).toHaveBeenCalledWith({
        profileId: 'azure-single-gpu-7b',
        region: 'southcentralus',
        name: undefined,
        inputs: {
          enableMonitoring: true,
          vmSizeOverride: null,
          vmPriority: 'Spot',
        },
      });
      expect(mockedGetEnvironment).toHaveBeenCalledWith('env-123');
    });

    expect(await screen.findByText(/environment ready/i)).toBeInTheDocument();
    expect(screen.getByText(/terraform apply queued/i)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /open environment detail/i })).toHaveAttribute(
      'href',
      '/environments/env-123',
    );
  });

  it('previews and provisions the same selected region, VM size and priority, and invalidates changes', async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <ProvisionPage />
      </MemoryRouter>,
    );
    await user.selectOptions(await screen.findByRole('combobox', { name: /cloud deployment profile/i }), 'azure-single-gpu-7b');
    await user.selectOptions(screen.getByRole('combobox', { name: /model catalog entry/i }), 'llama-7b');
    await user.selectOptions(screen.getByRole('combobox', { name: /provisioning region/i }), 'italynorth');
    await user.type(screen.getByRole('textbox', { name: 'vmSizeOverride' }), 'Standard_NC4as_T4_v3');
    await user.selectOptions(screen.getByRole('combobox', { name: 'vmPriority' }), 'Regular');
    await user.click(screen.getByRole('button', { name: /preview region recommendation/i }));

    const inputs = {
      enableMonitoring: true,
      vmSizeOverride: 'Standard_NC4as_T4_v3',
      vmPriority: 'Regular',
    };
    expect(mockedPreviewEnvironment).toHaveBeenLastCalledWith({
      profileId: 'azure-single-gpu-7b',
      regionOverride: 'italynorth',
      configurableInputs: inputs,
    });
    const confirm = await screen.findByRole('button', { name: /confirm provisioning/i });
    expect(confirm).toBeEnabled();
    await user.selectOptions(screen.getByRole('combobox', { name: 'vmPriority' }), 'Spot');
    expect(confirm).toBeDisabled();
    await user.selectOptions(screen.getByRole('combobox', { name: 'vmPriority' }), 'Regular');
    expect(confirm).toBeDisabled();
    await user.click(screen.getByRole('button', { name: /preview region recommendation/i }));
    await user.click(await screen.findByRole('button', { name: /confirm provisioning/i }));
    expect(mockedProvisionEnvironment).toHaveBeenCalledWith({
      profileId: 'azure-single-gpu-7b',
      region: 'italynorth',
      name: undefined,
      inputs,
    });
  });

  it('does not accept an obsolete in-flight preview after inputs change', async () => {
    const user = userEvent.setup();
    let resolvePreview!: (value: Awaited<ReturnType<typeof previewEnvironment>>) => void;
    const result = await mockedPreviewEnvironment({ profileId: 'azure-single-gpu-7b' });
    mockedPreviewEnvironment.mockReset();
    mockedPreviewEnvironment.mockReturnValue(new Promise((resolve) => { resolvePreview = resolve; }));
    render(<MemoryRouter><ProvisionPage /></MemoryRouter>);
    await user.selectOptions(await screen.findByRole('combobox', { name: /cloud deployment profile/i }), 'azure-single-gpu-7b');
    await user.selectOptions(screen.getByRole('combobox', { name: /model catalog entry/i }), 'llama-7b');
    await user.click(screen.getByRole('button', { name: /preview region recommendation/i }));
    await user.selectOptions(screen.getByRole('combobox', { name: 'vmPriority' }), 'Regular');
    resolvePreview(result);
    await waitFor(() => expect(screen.getByRole('button', { name: /preview region recommendation/i })).toBeEnabled());
    expect(screen.queryByRole('button', { name: /confirm provisioning/i })).not.toBeInTheDocument();
  });
});
