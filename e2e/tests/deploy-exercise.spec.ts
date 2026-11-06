import { expect, test } from '@playwright/test';
import { catalogResponse, environmentResponse, fulfillJson } from './support/fixtures';

test('quickstart scenario 2 deploy and exercise flow', async ({ page }) => {
  let deploymentPollCount = 0;

  await page.route('http://localhost:8000/**', async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const { pathname } = url;

    if (pathname === '/session') {
      await fulfillJson(route, 200, { authenticated: true });
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

    if (pathname === '/environments/env-123' && request.method() === 'GET') {
      await fulfillJson(
        route,
        200,
        environmentResponse({
          environmentId: 'env-123',
          lifecycleState: 'ready',
          provider: 'azure',
          profileId: 'azure-single-gpu-7b',
          region: 'southcentralus',
          activeRevisionId: deploymentPollCount > 1 ? 'rev-001' : null,
        }),
      );
      return;
    }

    if (pathname === '/environments/env-123/model-configurations' && request.method() === 'GET') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          requestId: 'req-model-history',
          items: [
            {
              requestId: 'req-model-config',
              modelConfigId: 'model-config-001',
              catalogEntryId: 'llama-7b',
              resolvedCheckpointRef: 'refs/pr/12/head',
              modelSettings: {
                maxContextLength: 8192,
              },
              version: 1,
              createdAt: '2026-08-19T09:40:00Z',
            },
          ],
        }),
      });
      return;
    }

    if (
      pathname === '/environments/env-123/model-configurations' &&
      request.method() === 'POST'
    ) {
      await route.fulfill({
        status: 201,
        contentType: 'application/json',
        body: JSON.stringify({
          requestId: 'req-model-config',
          modelConfigId: 'model-config-001',
          catalogEntryId: 'llama-7b',
          resolvedCheckpointRef: 'refs/pr/12/head',
          modelSettings: {
            maxContextLength: 8192,
          },
          version: 1,
          createdAt: '2026-08-19T09:40:00Z',
        }),
      });
      return;
    }

    if (
      pathname === '/environments/env-123/inference-configurations' &&
      request.method() === 'GET'
    ) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          requestId: 'req-inference-history',
          items: [
            {
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
              version: 1,
              createdAt: '2026-08-19T09:41:00Z',
            },
          ],
        }),
      });
      return;
    }

    if (
      pathname === '/environments/env-123/inference-configurations' &&
      request.method() === 'POST'
    ) {
      await route.fulfill({
        status: 201,
        contentType: 'application/json',
        body: JSON.stringify({
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
          version: 1,
          createdAt: '2026-08-19T09:41:00Z',
        }),
      });
      return;
    }

    if (pathname === '/environments/env-123/deployments' && request.method() === 'POST') {
      await route.fulfill({
        status: 202,
        contentType: 'application/json',
        body: JSON.stringify({
          requestId: 'req-deploy',
          operationId: 'op-123',
          deploymentRevisionId: 'rev-001',
          phase: 'accepted',
          lifecycleState: 'deploying',
        }),
      });
      return;
    }

    if (pathname === '/environments/env-123/deployments/rev-001' && request.method() === 'GET') {
      deploymentPollCount += 1;
      const ready = deploymentPollCount > 1;

      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          requestId: 'req-revision',
          deploymentRevisionId: 'rev-001',
          environmentId: 'env-123',
          modelConfigId: 'model-config-001',
          inferenceConfigId: 'inference-config-001',
          engineId: 'vllm',
          lifecycleState: ready ? 'ready' : 'deploying',
          activePeriod: {
            startedAt: '2026-08-19T09:45:00Z',
            endedAt: null,
          },
          health: {
            status: ready ? 'healthy' : 'unknown',
            diagnostics: ready ? ['Readiness probe passed.'] : ['Container starting.'],
          },
          createdAt: '2026-08-19T09:44:00Z',
        }),
      });
      return;
    }

    if (pathname === '/environments/env-123/prompts' && request.method() === 'POST') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          requestId: 'req-prompt',
          deploymentRevisionId: 'rev-001',
          responseText: 'South Central US is preferred because capacity is healthier for this demo.',
          timing: {
            ttftMs: 210,
            interTokenLatencyMsAvg: 19,
            totalLatencyMs: 880,
          },
          activeRevision: {
            deploymentRevisionId: 'rev-001',
            modelConfigId: 'model-config-001',
            inferenceConfigId: 'inference-config-001',
          },
        }),
      });
      return;
    }

    await route.fulfill({
      status: 404,
      contentType: 'application/json',
      body: JSON.stringify({
        requestId: 'req-404',
        error: {
          code: 'not_found',
          message: `No mocked response for ${pathname}`,
        },
      }),
    });
  });

  await page.goto('/deploy?environmentId=env-123');

  await page.getByRole('button', { name: /load environment/i }).click();
  await page.getByRole('combobox', { name: /catalog entry/i }).selectOption('llama-7b');
  await page.getByRole('textbox', { name: /resolved checkpoint ref/i }).fill('refs/pr/12/head');
  await page.getByRole('button', { name: /create model configuration/i }).click();
  await expect(page.getByText(/selected model configuration v1/i)).toBeVisible();

  await page.getByRole('button', { name: /create inference configuration/i }).click();
  await expect(page.getByText(/selected inference configuration v1/i)).toBeVisible();

  await page.getByLabel(/hugging face token/i).fill('hf-secret-token');
  await page.getByRole('button', { name: /deploy selected revision/i }).click();

  await expect(page.getByText(/deployment ready/i)).toBeVisible();

  await page.getByRole('link', { name: /open exercise console/i }).click();
  await expect(page).toHaveURL(/\/exercise\?environmentId=env-123$/);

  await page.getByRole('textbox', { name: /prompt/i }).fill('Why is this region preferred?');
  await page.getByRole('button', { name: /submit prompt/i }).click();

  await expect(
    page.getByText(/south central us is preferred because capacity is healthier/i),
  ).toBeVisible();
  await expect(page.getByText(/210 ms/i)).toBeVisible();
  await expect(page.getByText(/880 ms/i)).toBeVisible();
  await expect(
    page.locator('dt').filter({ hasText: /^Active revision$/ }).locator('..').locator('dd'),
  ).toHaveText('rev-001');
});
