import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import EnvironmentDetailPage from '../src/pages/EnvironmentDetail';
import { listProfiles } from '../src/services/catalogApi';
import { getEnvironment } from '../src/services/environmentsApi';

vi.mock('../src/services/catalogApi', () => ({
  listProfiles: vi.fn(),
}));

vi.mock('../src/services/environmentsApi', async () => {
  const actual = await vi.importActual<typeof import('../src/services/environmentsApi')>(
    '../src/services/environmentsApi',
  );

  return {
    ...actual,
    getEnvironment: vi.fn(),
  };
});

const mockedListProfiles = vi.mocked(listProfiles);
const mockedGetEnvironment = vi.mocked(getEnvironment);

describe('EnvironmentDetailPage', () => {
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
          regions: ['eastus', 'southcentralus'],
          resourceAssumptions: ['1x Standard_NC24ads_A100_v4'],
          capacityRequirements: ['GPU quota'],
          configurableInputs: [],
          knownLimitations: ['Requires quota validation before apply.'],
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
      activeRevisionId: 'rev-001',
      resources: [
        {
          name: 'gpu-vm',
          type: 'virtualMachine',
          state: 'running',
          summary: 'Serving VM ready.',
        },
      ],
      capacityContext: {
        region: 'southcentralus',
        assessedAt: '2026-08-19T09:30:00Z',
        quotaStatus: 'sufficient',
        capacityStatus: 'available',
        notes: ['Fallback from eastus avoided a constrained capacity signal.'],
      },
      costContext: {
        estimatedHourlyUsd: 7.5,
        notes: ['GPU VM dominates spend.'],
      },
      createdAt: '2026-08-19T09:31:00Z',
      updatedAt: '2026-08-19T09:33:00Z',
    });
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it('renders state, profile, revision, and capacity context', async () => {
    render(
      <MemoryRouter initialEntries={['/environments/env-123']}>
        <Routes>
          <Route path="/environments/:environmentId" element={<EnvironmentDetailPage />} />
        </Routes>
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(mockedGetEnvironment).toHaveBeenCalledWith('env-123');
      expect(mockedListProfiles).toHaveBeenCalledTimes(1);
    });

    expect(await screen.findByRole('heading', { name: /demo-ready/i })).toBeInTheDocument();
    expect(screen.getByText(/azure single gpu 7b/i)).toBeInTheDocument();
    expect(screen.getByText(/rev-001/i)).toBeInTheDocument();
    expect(
      screen.getByText(/fallback from eastus avoided a constrained capacity signal/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/\$7\.50/i)).toBeInTheDocument();
    expect(screen.getByText(/serving vm ready/i)).toBeInTheDocument();
  });
});
