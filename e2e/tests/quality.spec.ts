import { expect, test } from '@playwright/test';
import { environmentResponse, fulfillJson, fulfillRunCatalog } from './support/fixtures';

test('quickstart scenario 3 quality run and report flow', async ({ page }) => {
  let runPollCount = 0;
  let completeRun = false;

  await page.route('http://localhost:8000/**', async (route) => {
    if (await fulfillRunCatalog(route)) return;
    const request = route.request();
    const url = new URL(request.url());
    const { pathname } = url;

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
          activeRevisionId: 'rev-001',
        }),
      );
      return;
    }

    if (pathname === '/environments/env-123/runs' && request.method() === 'POST') {
      await route.fulfill({
        status: 202,
        contentType: 'application/json',
        body: JSON.stringify({
          requestId: 'req-start',
          runId: 'run-123',
          runType: 'quality-golden',
          status: 'queued',
          deploymentRevisionId: 'rev-001',
        }),
      });
      return;
    }

    if (pathname === '/environments/env-123/runs/run-123' && request.method() === 'GET') {
      runPollCount += 1;
      const completed = completeRun;

      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          requestId: `req-run-${runPollCount}`,
          runId: 'run-123',
          environmentId: 'env-123',
          deploymentRevisionId: 'rev-001',
          runType: 'quality-golden',
          testDefinitionRef: 'golden-demo-v1',
          status: completed ? 'completed' : 'running',
          startedAt: '2026-08-19T10:06:00Z',
          endedAt: completed ? '2026-08-19T10:06:09Z' : null,
          diagnostics: [
            {
              timestamp: completed ? '2026-08-19T10:06:09Z' : '2026-08-19T10:06:01Z',
              severity: 'info',
              message: completed ? 'Run completed.' : 'Executing golden cases.',
            },
          ],
          progress: {
            totalCases: 5,
            completedCases: completed ? 5 : 2,
          },
        }),
      });
      return;
    }

    if (pathname === '/environments/env-123/runs/run-123/report' && request.method() === 'GET') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          requestId: 'req-report',
          resultReportId: 'report-123',
          runId: 'run-123',
          completenessIndicator: 'complete',
          quality: {
            aggregate: {
              totalCases: 5,
              passed: 4,
              failed: 1,
              errored: 0,
              skipped: 0,
              incomplete: 0,
              passRate: 0.8,
            },
            cases: [
              {
                caseId: 'case-001',
                input: 'Summarize the deployment choice.',
                evaluationRule: 'Must mention GPU capacity.',
                observedOutcome: 'Mentions GPU capacity and region choice.',
                status: 'passed',
              },
              {
                caseId: 'case-002',
                input: 'Return JSON only.',
                evaluationRule: 'Must be valid JSON.',
                observedOutcome: 'Returned prose instead of JSON.',
                status: 'failed',
              },
            ],
            benchmarks: [],
          },
          performance: null,
          referenceExecutionProfileRef: 'quality-short-v1',
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

  await page.goto('/quality/run?environmentId=env-123');

  await page.getByRole('button', { name: /load environment/i }).click();
  await page.getByRole('combobox', { name: /^golden dataset$/i }).fill('golden-demo-v1');
  await page.getByRole('button', { name: /start run/i }).click();

  await expect(page.getByText('2 / 5 cases complete')).toBeVisible();
  await expect(page.getByText(/executing golden cases/i)).toBeVisible();
  completeRun = true;
  await expect(page.getByText('5 / 5 cases complete')).toBeVisible();

  await page.getByRole('link', { name: /open quality report/i }).click();

  await expect(page).toHaveURL(/\/quality\/report\/run-123\?environmentId=env-123$/);
  await expect(page.getByText('80.0%')).toBeVisible();
  await expect(page.getByText(/return json only/i)).toBeVisible();
  await expect(page.getByText(/returned prose instead of json/i)).toBeVisible();
});
