import { expect, test } from '@playwright/test';
import { environmentResponse, fulfillJson, fulfillRunCatalog } from './support/fixtures';

test('quickstart scenario 4 performance run and partial report flow', async ({ page }) => {
  let runPollCount = 0;

  await page.route('http://localhost:8000/**', async (route) => {
    if (await fulfillRunCatalog(route)) return;
    const request = route.request();
    const url = new URL(request.url());
    const { pathname } = url;

    if (pathname === '/environments/env-456' && request.method() === 'GET') {
      await fulfillJson(
        route,
        200,
        environmentResponse({
          environmentId: 'env-456',
          lifecycleState: 'ready',
          provider: 'azure',
          profileId: 'azure-single-gpu-7b',
          region: 'southcentralus',
          activeRevisionId: 'rev-perf-001',
        }),
      );
      return;
    }

    if (pathname === '/environments/env-456/runs' && request.method() === 'POST') {
      await route.fulfill({
        status: 202,
        contentType: 'application/json',
        body: JSON.stringify({
          requestId: 'req-start',
          runId: 'run-perf-123',
          runType: 'performance',
          status: 'queued',
          deploymentRevisionId: 'rev-perf-001',
        }),
      });
      return;
    }

    if (pathname === '/environments/env-456/runs/run-perf-123' && request.method() === 'GET') {
      runPollCount += 1;
      const completed = runPollCount > 1;

      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          requestId: `req-run-${runPollCount}`,
          runId: 'run-perf-123',
          environmentId: 'env-456',
          deploymentRevisionId: 'rev-perf-001',
          runType: 'performance',
          testDefinitionRef: 'workload-demo-v1',
          status: completed ? 'incomplete' : 'running',
          startedAt: '2026-08-19T11:06:00Z',
          endedAt: completed ? '2026-08-19T11:07:30Z' : null,
          diagnostics: [
            {
              timestamp: completed ? '2026-08-19T11:07:30Z' : '2026-08-19T11:06:04Z',
              severity: completed ? 'warning' : 'info',
              message: completed
                ? 'Monitoring data incomplete after overload threshold was reached.'
                : 'Executing workload under configured concurrency.',
            },
          ],
          progress: {
            totalCases: 1,
            completedCases: completed ? 1 : 0,
          },
        }),
      });
      return;
    }

    if (pathname === '/environments/env-456/runs/run-perf-123/report' && request.method() === 'GET') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          requestId: 'req-report',
          resultReportId: 'report-perf-123',
          runId: 'run-perf-123',
          completenessIndicator: 'partial',
          quality: {
            aggregate: {
              totalCases: 0,
              passed: 0,
              failed: 0,
              errored: 0,
              skipped: 0,
              incomplete: 0,
              passRate: 0,
            },
            cases: [],
            benchmarks: [],
          },
          performance: {
            metrics: {
              timeToFirstTokenMs: { p50: 120.4, p95: 340.2 },
              interTokenLatencyMs: { p50: 15.1, p95: 40.0 },
              endToEndLatencyMs: { p50: 900.3, p95: 2200.7 },
              throughputTokensPerSec: 85.4,
            },
            requestFailures: { count: 2, total: 50, rate: 0.04 },
            units: {
              timeToFirstTokenMs: 'ms',
              interTokenLatencyMs: 'ms',
              endToEndLatencyMs: 'ms',
              throughputTokensPerSec: 'tokens/sec',
            },
            testConditions: {
              warmup: { requests: 5 },
              inputProfile: { promptTokens: 512, completionTokens: 256 },
              concurrency: 8,
              durationOrRequestCount: { requests: 50 },
              safetyLimits: { maxErrors: 3 },
              completionCriteria: { stopWhen: 'request-count-reached' },
            },
            acceleratorUtilization: {
              available: true,
              details: { avgPercent: 78.2 },
            },
            runner: 'llmperf',
          },
          referenceExecutionProfileRef: 'perf-reference-v1',
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

  await page.goto('/performance/run?environmentId=env-456');

  await page.getByRole('button', { name: /load environment/i }).click();
  await page.getByRole('combobox', { name: /^performance workload$/i }).fill('workload-demo-v1');
  await page.getByRole('button', { name: /start run/i }).click();

  await expect(page.getByText('0 / 1 cases complete')).toBeVisible();
  await expect(page.getByText('1 / 1 cases complete')).toBeVisible();
  await expect(page.getByText(/monitoring data incomplete/i)).toBeVisible();

  await page.getByRole('link', { name: /open performance report/i }).click();

  await expect(page).toHaveURL(/\/performance\/report\/run-perf-123\?environmentId=env-456$/);
  await expect(page.getByText(/must not be treated as a successful result/i)).toBeVisible();
  await expect(page.getByText(/p50 120.4 ms/i)).toBeVisible();
  await expect(page.getByText(/p95 340.2 ms/i)).toBeVisible();
  await expect(page.getByText(/85.4 tokens\/sec/i)).toBeVisible();
  await expect(page.getByText(/2 \/ 50/i)).toBeVisible();
  await expect(page.getByText(/4.0% failure rate/i)).toBeVisible();
  await expect(page.getByText(/perf-reference-v1/i)).toBeVisible();
  await expect(page.getByText(/avgPercent/i)).toBeVisible();
});

test('quickstart scenario 4 performance run cancellation updates run state', async ({ page }) => {
  let cancelCount = 0;

  await page.route('http://localhost:8000/**', async (route) => {
    if (await fulfillRunCatalog(route)) return;
    const request = route.request();
    const url = new URL(request.url());
    const { pathname } = url;

    if (pathname === '/environments/env-cancel' && request.method() === 'GET') {
      await fulfillJson(
        route,
        200,
        environmentResponse({
          environmentId: 'env-cancel',
          lifecycleState: 'ready',
          provider: 'azure',
          profileId: 'azure-single-gpu-7b',
          region: 'southcentralus',
          activeRevisionId: 'rev-perf-001',
        }),
      );
      return;
    }

    if (pathname === '/environments/env-cancel/runs' && request.method() === 'POST') {
      await route.fulfill({
        status: 202,
        contentType: 'application/json',
        body: JSON.stringify({
          requestId: 'req-start',
          runId: 'run-cancel-123',
          runType: 'performance',
          status: 'queued',
          deploymentRevisionId: 'rev-perf-001',
        }),
      });
      return;
    }

    if (pathname === '/environments/env-cancel/runs/run-cancel-123' && request.method() === 'GET') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          requestId: 'req-run',
          runId: 'run-cancel-123',
          environmentId: 'env-cancel',
          deploymentRevisionId: 'rev-perf-001',
          runType: 'performance',
          testDefinitionRef: 'workload-demo-v1',
          status: 'running',
          startedAt: '2026-08-19T11:06:00Z',
          endedAt: null,
          diagnostics: [
            {
              timestamp: '2026-08-19T11:06:04Z',
              severity: 'info',
              message: 'Executing workload under configured concurrency.',
            },
          ],
          progress: {
            totalCases: 1,
            completedCases: 0,
          },
        }),
      });
      return;
    }

    if (
      pathname === '/environments/env-cancel/runs/run-cancel-123/cancel' &&
      request.method() === 'POST'
    ) {
      cancelCount += 1;

      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          requestId: `req-cancel-${cancelCount}`,
          runId: 'run-cancel-123',
          status: 'cancelled',
          cancellationRequests: [
            {
              requestedAt: '2026-08-19T11:06:10Z',
              requestedBy: 'presenter@example.com',
            },
          ],
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

  await page.goto('/performance/run?environmentId=env-cancel');

  await page.getByRole('button', { name: /load environment/i }).click();
  await page.getByRole('combobox', { name: /^performance workload$/i }).fill('workload-demo-v1');
  await page.getByRole('button', { name: /start run/i }).click();

  await expect(page.getByRole('button', { name: /cancel run/i })).toBeVisible();
  await page.getByRole('button', { name: /cancel run/i }).click();
  await expect(page.getByText('Cancelled')).toBeVisible();
  expect(cancelCount).toBe(1);
});
