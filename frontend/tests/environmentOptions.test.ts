import { environmentLabel, visibleEnvironments } from '../src/components/environmentOptions';
import type { EnvironmentSummary } from '../src/services/types';

const active: EnvironmentSummary = {
  environmentId: 'environment-active',
  profileId: 'gpu-profile',
  region: 'westus',
  provider: 'azure',
  lifecycleState: 'ready',
};
const archived: EnvironmentSummary = {
  ...active,
  environmentId: 'environment-archived',
  lifecycleState: 'torn_down',
};
const failed: EnvironmentSummary = {
  ...active,
  environmentId: 'environment-failed',
  lifecycleState: 'provisioning_failed',
};

describe('environment options', () => {
  it('uses a supplied name or an honest disambiguated fallback', () => {
    expect(environmentLabel({ ...active, name: 'Research' })).toBe('Research (t-active)');
    expect(environmentLabel(active)).toBe('gpu-profile · westus (t-active)');
  });

  it('retains failed and explicitly selected archived entries, with archives last', () => {
    expect(visibleEnvironments([archived, failed, active], false)).toEqual([failed, active]);
    expect(visibleEnvironments([archived, failed, active], false, archived.environmentId)).toEqual([failed, active, archived]);
    expect(visibleEnvironments([archived, active], true)).toEqual([active, archived]);
    expect(visibleEnvironments([archived], false)).toEqual([]);
  });
});
