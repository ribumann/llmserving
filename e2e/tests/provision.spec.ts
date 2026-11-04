import { expect, test } from '@playwright/test';
import {
  acceptedOperationResponse,
  catalogResponse,
  environmentResponse,
  fulfillJson,
  profilesResponse,
} from './support/fixtures';

test('quickstart scenario 1 provision flow', async ({ page }) => {
  let environmentPollCount = 0;

  await page.route('http://localhost:8000/**', async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const { pathname } = url;

    if (pathname === '/profiles' && request.method() === 'GET') {
      await fulfillJson(
        route,
        200,
        profilesResponse([
          {
            profileId: 'azure-single-gpu-7b',
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

    if (pathname === '/catalog' && request.method() === 'GET') {
      await fulfillJson(
        route,
        200,
        catalogResponse([
          {
            catalogEntryId: 'llama-7b',
            family: 'Llama',
            sizeClass: '7b',
            huggingFaceRepoId: 'meta-llama/Llama-3.1-8B-Instruct',
            checkpointRef: 'main',
            isGated: true,
            license: 'Custom',
            compatibleProfileIds: ['azure-single-gpu-7b'],
            notes: 'Balanced demo checkpoint.',
          },
        ]),
      );
      return;
    }

    if (pathname === '/environments/preview' && request.method() === 'POST') {
      await fulfillJson(route, 200, {
        requestId: 'req-preview',
        profileId: 'azure-single-gpu-7b',
        recommendedRegion: 'southcentralus',
        advisoryMessage: 'South Central US currently has the clearest capacity signal.',
        assessments: [
          {
            region: 'eastus',
            quotaStatus: 'sufficient',
            capacityStatus: 'constrained',
            compatibilityStatus: 'compatible',
            checkedAt: '2026-08-19T09:30:00Z',
            evidence: ['Recent allocation failed with AllocationFailed.'],
            uncertainty: 'Capacity signals can change quickly.',
          },
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

    if (pathname === '/environments' && request.method() === 'POST') {
      await fulfillJson(
        route,
        202,
        acceptedOperationResponse({
          environmentId: 'env-001',
          operationId: 'op-001',
          phase: 'accepted',
          state: 'PROVISIONING',
          region: 'southcentralus',
          message: 'Terraform apply queued.',
        }),
      );
      return;
    }

    if (pathname === '/environments/env-001' && request.method() === 'GET') {
      environmentPollCount += 1;
      const ready = environmentPollCount > 1;

      await fulfillJson(
        route,
        200,
        environmentResponse({
          environmentId: 'env-001',
          lifecycleState: ready ? 'ready' : 'provisioning',
          provider: 'azure',
          profileId: 'azure-single-gpu-7b',
          region: 'southcentralus',
          activeRevisionId: null,
          resources: [
            {
              name: 'gpu-vm',
              type: 'virtualMachine',
              state: ready ? 'ready' : 'creating',
              summary: ready ? 'Provisioned successfully.' : 'Terraform apply in progress.',
            },
          ],
          contextExtra: {
            capacityContext: {
              region: 'southcentralus',
              assessedAt: '2026-08-19T09:30:00Z',
              quotaStatus: 'sufficient',
              capacityStatus: 'available',
              notes: ['Fallback from eastus to southcentralus due to constrained capacity.'],
            },
          },
        }),
      );
      return;
    }

    await fulfillJson(route, 404, {
      requestId: 'req-404',
      error: { code: 'not_found', message: `No mocked response for ${pathname}` },
    });
  });

  await page.goto('/provision');

  await page.getByRole('combobox', { name: /cloud deployment profile/i }).selectOption(
    'azure-single-gpu-7b',
  );
  await page.getByRole('combobox', { name: /model catalog entry/i }).selectOption('llama-7b');

  await page.getByRole('button', { name: /preview region recommendation/i }).click();

  await expect(
    page.getByText(/recommended region:\s*southcentralus/i),
  ).toBeVisible();
  await expect(page.getByText(/capacity signals can change quickly/i)).toBeVisible();

  await page.getByRole('button', { name: /confirm provisioning/i }).click();

  await expect(page.getByText(/terraform apply queued/i)).toBeVisible();
  await expect(page.getByText(/environment ready/i)).toBeVisible();

  await page.getByRole('link', { name: /open environment detail/i }).click();

  await expect(page).toHaveURL(/\/environments\/env-001$/);
});
