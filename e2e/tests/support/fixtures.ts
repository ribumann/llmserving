import type { Route } from '@playwright/test';

/**
 * Shared response builders matching the REAL FastAPI backend wire contracts
 * (see backend/src/api/routes/catalog.py and backend/src/api/routes/environments.py).
 * These deliberately differ from the frontend's normalized `CloudDeploymentProfile`/
 * `ModelCatalogEntry`/`DemoEnvironment` shapes in frontend/src/services/types.ts -
 * the frontend API layer (catalogApi.ts/environmentsApi.ts) does the field-name
 * translation, and these mocks exist to exercise that real translation rather
 * than bypass it. Centralizing the shape here means a future backend contract
 * change only needs to be reflected in one place across the e2e suite.
 */

export interface CloudProfileFixture {
  profileId: string;
  provider: 'azure' | 'local';
  modelSizeClass: '3b' | '7b' | '70b';
  eligibleRegions: string[];
  vmSku: string;
  capacityAssumptions?: Record<string, unknown>;
  configurableInputs?: Record<string, unknown>;
  knownLimitations?: string[];
  version?: number;
}

export function profilesResponse(profiles: CloudProfileFixture[], requestId = 'req-profiles') {
  return {
    requestId,
    profiles: profiles.map((profile) => ({
      capacityAssumptions: {},
      configurableInputs: {},
      knownLimitations: [],
      version: 1,
      ...profile,
    })),
  };
}

export interface CatalogEntryFixture {
  catalogEntryId: string;
  family: string;
  sizeClass: '3b' | '7b' | '70b';
  huggingFaceRepoId: string;
  checkpointRef: string;
  isGated: boolean;
  license: string;
  compatibleProfileIds: string[];
  quantizationRequired?: boolean;
  notes?: string;
}

export function catalogResponse(entries: CatalogEntryFixture[], requestId = 'req-catalog') {
  return {
    requestId,
    // The real backend's envelope key is "catalog"; frontend's catalogApi.ts
    // also accepts "entries" defensively, but "catalog" is what it actually sends.
    catalog: entries.map((entry) => ({
      quantizationRequired: false,
      notes: '',
      ...entry,
    })),
  };
}

export interface EnvironmentResourceFixture {
  name: string;
  type: string;
  state: string;
  summary?: string;
}

export interface EnvironmentFixture {
  environmentId: string;
  lifecycleState: string;
  provider?: 'azure' | 'local';
  profileId?: string;
  region?: string;
  activeRevisionId?: string | null;
  resources?: EnvironmentResourceFixture[];
  contextExtra?: Record<string, unknown>;
  requestId?: string;
}

export function environmentResponse(fixture: EnvironmentFixture) {
  const {
    environmentId,
    lifecycleState,
    provider = 'azure',
    profileId = '',
    region = '',
    activeRevisionId = null,
    resources = [],
    contextExtra = {},
    requestId = 'req-environment',
  } = fixture;

  return {
    environmentId,
    lifecycleState,
    activeRevisionId,
    providerState: { resources },
    context: { provider, profileId, region, ...contextExtra },
    requestId,
  };
}

export interface AcceptedOperationFixture {
  environmentId: string;
  operationId: string;
  phase: string;
  state?: string;
  region?: string;
  diagnostics?: string[];
  message?: string;
  requestId?: string;
}

export function acceptedOperationResponse(fixture: AcceptedOperationFixture) {
  const {
    environmentId,
    operationId,
    phase,
    state = 'PROVISIONING',
    region = '',
    diagnostics = [],
    message,
    requestId = 'req-provision',
  } = fixture;

  return {
    environmentId,
    operationId,
    phase,
    state,
    diagnostics,
    region,
    ...(message ? { message } : {}),
    requestId,
  };
}

export async function fulfillJson(route: Route, status: number, body: unknown) {
  await route.fulfill({
    status,
    contentType: 'application/json',
    body: JSON.stringify(body),
  });
}

export async function fulfillRunCatalog(route: Route): Promise<boolean> {
  if (route.request().method() !== 'GET') return false;
  const { pathname } = new URL(route.request().url());
  const responses: Record<string, Record<string, unknown>> = {
    '/golden-datasets': {
      goldenDatasets: [{
        goldenDatasetId: 'golden-demo-v1', name: 'Demo golden', version: 1,
        provenance: 'curated', reviewStatus: 'reviewed', caseCount: 5,
      }],
    },
    '/benchmark-definitions': {
      benchmarkDefinitions: [{ benchmarkId: 'gsm8k', version: 'test-v1' }],
    },
    '/performance-workloads': {
      performanceWorkloads: [{ workloadId: 'workload-demo-v1', version: 1, concurrency: 8 }],
    },
  };
  if (/^\/environments\/[^/]+\/runs$/.test(pathname)) {
    await fulfillJson(route, 200, { requestId: 'req-history', runs: [] });
    return true;
  }
  if (!(pathname in responses)) return false;
  await fulfillJson(route, 200, { requestId: 'req-run-catalog', ...responses[pathname] });
  return true;
}
