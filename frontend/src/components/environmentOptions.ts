import type { EnvironmentSummary } from '../services/types';
import { formatStateLabel } from './kit';

export function environmentLabel(environment: EnvironmentSummary) {
  const name = environment.name?.trim();
  return `${name || `${environment.profileId} · ${environment.region}`} (${environment.environmentId.slice(-8)})`;
}

export function environmentOptionLabel(environment: EnvironmentSummary) {
  return `${environmentLabel(environment)} — ${formatStateLabel(environment.lifecycleState)}`;
}

export function visibleEnvironments(
  environments: EnvironmentSummary[],
  showArchived: boolean,
  selectedId = '',
) {
  return environments.filter(
    (environment) =>
      environment.lifecycleState !== 'torn_down' ||
      showArchived ||
      environment.environmentId === selectedId,
  ).sort((a, b) => Number(a.lifecycleState === 'torn_down') - Number(b.lifecycleState === 'torn_down'));
}
