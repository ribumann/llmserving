import { expect, test } from '@playwright/test';
import { fulfillJson } from './support/fixtures';

test('quickstart scenario 5 compare flow', async ({ page }) => {
  await page.route('http://localhost:8000/**', async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const { pathname } = url;

    if (pathname === '/comparisons' && request.method() === 'POST') {
      await fulfillJson(route, 201, {
        requestId: 'req-comparison',
        comparisonId: 'comparison-123',
        comparabilityStatus: 'not-directly-comparable',
        reasons: [
          "These results used different model checkpoints (Qwen/Qwen3-4B@main, Qwen/Qwen3-4B@v2) and are not directly comparable.",
        ],
        reports: [
          { reportId: 'report-1', revisionId: 'rev-001', environmentId: 'env-123' },
          { reportId: 'report-2', revisionId: 'rev-002', environmentId: 'env-123' },
        ],
        sections: [
          {
            title: 'Configuration',
            items: [
              { reportId: 'report-1', checkpoint: 'Qwen/Qwen3-4B@main' },
              { reportId: 'report-2', checkpoint: 'Qwen/Qwen3-4B@v2' },
            ],
          },
          {
            title: 'Quality',
            items: [
              { reportId: 'report-1', totalCases: 10, passed: 8, passRate: 0.8 },
              { reportId: 'report-2', totalCases: 10, passed: 9, passRate: 0.9 },
            ],
          },
          { title: 'Performance', items: [] },
          { title: 'Failures', items: [] },
          { title: 'Accelerator utilization', items: [] },
        ],
      });
      return;
    }

    if (pathname === '/comparisons/comparison-123' && request.method() === 'GET') {
      await fulfillJson(route, 200, {
        requestId: 'req-comparison-get',
        comparisonId: 'comparison-123',
        comparabilityStatus: 'not-directly-comparable',
        reasons: [
          "These results used different model checkpoints (Qwen/Qwen3-4B@main, Qwen/Qwen3-4B@v2) and are not directly comparable.",
        ],
        reports: [
          { reportId: 'report-1', revisionId: 'rev-001', environmentId: 'env-123' },
          { reportId: 'report-2', revisionId: 'rev-002', environmentId: 'env-123' },
        ],
        sections: [
          {
            title: 'Configuration',
            items: [
              { reportId: 'report-1', checkpoint: 'Qwen/Qwen3-4B@main' },
              { reportId: 'report-2', checkpoint: 'Qwen/Qwen3-4B@v2' },
            ],
          },
          { title: 'Quality', items: [] },
          { title: 'Performance', items: [] },
          { title: 'Failures', items: [] },
          { title: 'Accelerator utilization', items: [] },
        ],
      });
      return;
    }

    await route.continue();
  });

  await page.goto('/compare');

  await page.getByRole('textbox', { name: /report id 1/i }).fill('report-1');
  await page.getByRole('textbox', { name: /report id 2/i }).fill('report-2');
  await page.getByRole('button', { name: /^compare$/i }).click();

  await expect(page).toHaveURL(/\?comparisonId=comparison-123$/);
  await expect(page.getByText('Not Directly Comparable', { exact: true })).toBeVisible();
  await expect(page.getByText(/different model checkpoints/i)).toBeVisible();
  await expect(page.getByText('report-1').first()).toBeVisible();
  await expect(page.getByText('report-2').first()).toBeVisible();

  await page.reload();

  await expect(page.getByText('Not Directly Comparable', { exact: true })).toBeVisible();
  await expect(page.getByText('rev-001')).toBeVisible();
});
