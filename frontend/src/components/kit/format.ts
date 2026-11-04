import type { StatusTone } from './StatusBadge';

/** `not_provisioned` / `quality-golden` → `Not Provisioned` / `Quality Golden`. Used for every raw snake_case or kebab-case status/state/phase/run-type value. */
export function formatStateLabel(value: string): string {
  return value
    .split('-')
    .join('_')
    .split('_')
    .map((segment) => segment.charAt(0).toUpperCase() + segment.slice(1))
    .join(' ');
}

const POSITIVE_STATES = new Set([
  'completed',
  'ready',
  'passed',
  'pass',
  'healthy',
  'removed',
  'reviewed',
  'success',
  'comparable',
]);

const NEGATIVE_STATES = new Set([
  'failed',
  'errored',
  'error',
  'cancelled',
  'provisioning_failed',
  'teardown_failed',
  'deployment_failed',
  'unhealthy',
  'not-directly-comparable',
]);

const ACTIVE_STATES = new Set([
  'queued',
  'running',
  'provisioning',
  'tearing_down',
  'deploying',
  'pending',
]);

const CAUTION_STATES = new Set(['degraded', 'incomplete', 'skipped', 'unreviewed', 'unknown', 'constrained', 'insufficient']);

/**
 * Maps the many status/state/severity enums used across the API (operation status,
 * environment/deployment lifecycle state, quality case status, diagnostic severity,
 * etc.) onto one of StatusBadge's semantic tones, so every page renders statuses
 * consistently instead of each page inventing its own color logic.
 */
export function statusTone(value: string): StatusTone {
  const normalized = value.toLowerCase();
  if (POSITIVE_STATES.has(normalized)) return 'success';
  if (NEGATIVE_STATES.has(normalized)) return 'error';
  if (CAUTION_STATES.has(normalized)) return 'warning';
  if (ACTIVE_STATES.has(normalized)) return 'brand';
  if (normalized === 'warning') return 'warning';
  if (normalized === 'info' || normalized === 'informative') return 'info';
  return 'neutral';
}
