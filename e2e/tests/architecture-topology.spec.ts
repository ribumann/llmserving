import { expect, test, type Page, type Route } from '@playwright/test';
import {
  acceptedOperationResponse,
  catalogResponse,
  environmentResponse,
  fulfillJson,
  profilesResponse,
} from './support/fixtures';

/**
 * Playwright coverage for quickstart.md Scenario 8 (T145, User Story 10):
 * the architecture-topology validation items that are observable from the
 * frontend UI. Resource-group/networking/secret-leakage assertions (items
 * 1, 4, 5, 6, 7) require inspecting real Azure resources and are instead a
 * scripted Azure CLI check meant to run after a real deployment - see
 * scripts/validate-architecture-topology.ps1.
 */

const PROFILE_ID = 'azure-single-gpu-7b';
const CATALOG_ENTRY_ID = 'llama-7b';

async function registerCatalogRoutes(
  page: Page,
  extra: (route: Route, pathname: string, method: string) => Promise<boolean>,
) {
  await page.route('http://localhost:8000/**', async (route) => {
    const request = route.request();
    const { pathname } = new URL(request.url());
    const method = request.method();

    if (await extra(route, pathname, method)) {
      return;
    }

    if (pathname === '/profiles' && method === 'GET') {
      await fulfillJson(
        route,
        200,
        profilesResponse([
          {
            profileId: PROFILE_ID,
            provider: 'azure',
            modelSizeClass: '7b',
            eligibleRegions: ['eastus', 'southcentralus'],
            vmSku: 'Standard_NC24ads_A100_v4',
            knownLimitations: ['Depends on current GPU capacity.'],
          },
        ]),
      );
      return;
    }

    if (pathname === '/catalog' && method === 'GET') {
      await fulfillJson(
        route,
        200,
        catalogResponse([
          {
            catalogEntryId: CATALOG_ENTRY_ID,
            family: 'Llama',
            sizeClass: '7b',
            huggingFaceRepoId: 'meta-llama/Llama-3.1-8B-Instruct',
            checkpointRef: 'main',
            isGated: true,
            license: 'Custom',
            compatibleProfileIds: [PROFILE_ID],
            notes: 'Balanced demo checkpoint.',
          },
        ]),
      );
      return;
    }

    if (pathname === '/environments/preview' && method === 'POST') {
      await fulfillJson(route, 200, {
        requestId: 'req-preview',
        profileId: PROFILE_ID,
        recommendedRegion: 'southcentralus',
        advisoryMessage: 'South Central US currently has the clearest capacity signal.',
        assessments: [
          {
            region: 'southcentralus',
            quotaStatus: 'sufficient',
            capacityStatus: 'available',
            compatibilityStatus: 'compatible',
            checkedAt: '2026-08-19T09:30:00Z',
            evidence: ['Latest SKU signal reports capacity.'],
          },
        ],
      });
      return;
    }

    await fulfillJson(route, 404, {
      requestId: 'req-404',
      error: { code: 'not_found', message: `No mocked response for ${pathname}` },
    });
  });
}

async function selectProfileAndPreview(page: Page) {
  await page.goto('/provision');
  await page.getByRole('combobox', { name: /cloud deployment profile/i }).selectOption(PROFILE_ID);
  await page
    .getByRole('combobox', { name: /model catalog entry/i })
    .selectOption(CATALOG_ENTRY_ID);
  await page.getByRole('button', { name: /preview region recommendation/i }).click();
  await expect(page.getByText(/recommended region:\s*southcentralus/i)).toBeVisible();
}

test('quickstart scenario 8 item 2: a conflicting operation is rejected immediately, not queued', async ({
  page,
}) => {
  // Simulates FastAPI's single-writer lock (FR-052/FR-083): the environment
  // this profile/region would provision into is already locked by another
  // in-flight operation, so the backend must answer this request with an
  // immediate 409 rather than accepting and queueing it.
  await registerCatalogRoutes(page, async (route, pathname, method) => {
    if (pathname === '/environments' && method === 'POST') {
      await fulfillJson(route, 409, {
        requestId: 'req-conflict',
        error: {
          code: 'environment_locked',
          message: 'Environment env-001 is already locked by operation op-existing.',
        },
      });
      return true;
    }
    return false;
  });

  await selectProfileAndPreview(page);
  await page.getByRole('button', { name: /confirm provisioning/i }).click();

  // The conflict must surface immediately - no "Provisioning progress" panel
  // (which only appears once an operation is actually accepted) is shown,
  // and the confirm button returns to its idle label rather than staying in
  // a queued/retrying state.
  await expect(page.getByText(/already locked by operation op-existing/i)).toBeVisible();
  await expect(page.getByRole('heading', { name: /provisioning progress/i })).toHaveCount(0);
  await expect(page.getByRole('button', { name: /^confirm provisioning$/i })).toBeVisible();
});

test('quickstart scenario 8 item 3: provisioning phase/elapsed time is sourced from the orchestration', async ({
  page,
}) => {
  let pollCount = 0;

  await registerCatalogRoutes(page, async (route, pathname, method) => {
    if (pathname === '/environments' && method === 'POST') {
      await fulfillJson(
        route,
        202,
        acceptedOperationResponse({
          environmentId: 'env-topology-001',
          operationId: 'op-topology-001',
          phase: 'accepted',
          state: 'PROVISIONING',
          region: 'southcentralus',
          message: 'Terraform apply queued via Durable Functions.',
        }),
      );
      return true;
    }

    if (pathname === '/environments/env-topology-001' && method === 'GET') {
      pollCount += 1;
      // The phase reported here stands in for the Durable Functions
      // orchestrator's own phase (FR-077/FR-078) - FastAPI never computes
      // this itself, it only relays what the orchestration reports back via
      // the internal callback API.
      const ready = pollCount > 1;

      await fulfillJson(
        route,
        200,
        environmentResponse({
          environmentId: 'env-topology-001',
          lifecycleState: ready ? 'ready' : 'provisioning',
          provider: 'azure',
          profileId: PROFILE_ID,
          region: 'southcentralus',
          activeRevisionId: null,
        }),
      );
      return true;
    }

    return false;
  });

  await selectProfileAndPreview(page);
  await page.getByRole('button', { name: /confirm provisioning/i }).click();

  await expect(page.getByRole('heading', { name: /provisioning progress/i })).toBeVisible();
  await expect(page.getByText('Operation id')).toBeVisible();
  await expect(page.getByText('op-topology-001')).toBeVisible();

  const currentPhase = page
    .locator('dt', { hasText: 'Current phase' })
    .locator('xpath=following-sibling::dd[1]');
  const elapsed = page
    .locator('dt', { hasText: 'Elapsed' })
    .locator('xpath=following-sibling::dd[1]');

  await expect(currentPhase).toBeVisible();
  await expect(elapsed).toHaveText(/^\d+s$/);
  await expect(page.getByText(/environment ready/i)).toBeVisible();
});
