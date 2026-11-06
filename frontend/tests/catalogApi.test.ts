import { listProfiles } from '../src/services/catalogApi';
import { apiRequest } from '../src/services/apiClient';

vi.mock('../src/services/apiClient', () => ({ apiRequest: vi.fn() }));

it('adds Italy and VM controls to an existing Azure 3B profile without duplicating configured controls', async () => {
  vi.mocked(apiRequest).mockResolvedValue({
    requestId: 'catalog',
    profiles: [{
      profileId: 'azure-single-gpu-3b',
      provider: 'azure',
      modelSizeClass: '3b',
      eligibleRegions: ['eastus2'],
      vmSku: 'Standard_NC16as_T4_v3',
      capacityAssumptions: {},
      configurableInputs: { profileSizeClass: 'small', vmPriority: 'Regular' },
      knownLimitations: [],
    }],
  });
  const { profiles } = await listProfiles();
  expect(profiles[0].regions).toEqual(['eastus2', 'italynorth']);
  expect(profiles[0].configurableInputs.filter((input) => input.name === 'vmPriority')).toEqual([
    expect.objectContaining({ type: 'enum', defaultValue: 'Regular', options: ['Spot', 'Regular'] }),
  ]);
  expect(profiles[0].configurableInputs).toContainEqual(
    expect.objectContaining({ name: 'vmSizeOverride', defaultValue: '' }),
  );
});
