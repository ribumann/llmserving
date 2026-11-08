import { expect, test } from '@playwright/test';
import path from 'node:path';

const environment = {
  environmentId: 'public-env', provider: 'azure', profileId: 'public-profile',
  region: 'eastus', state: 'torn_down', lifecycleState: 'torn_down', resources: [],
};
const run = {
  runId: 'public-run', runType: 'quality-golden', testDefinitionRef: 'public-golden',
  status: 'completed', startedAt: '2026-11-07T10:00:00Z',
};

test('anonymous visitors browse actual persisted summaries and retained reports', async ({ page }) => {
  const apiCalls: string[] = [];
  await page.route('http://localhost:8000/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    apiCalls.push(path);
    if (path === '/session') {
      await route.fulfill({ status: 401 });
      return;
    }
    expect(route.request().method()).toBe('GET');
    expect(path.startsWith('/public/')).toBe(true);
    let json: unknown;
    if (path === '/public/environments') json = { environments: [environment] };
    else if (path === '/public/environments/public-env') json = environment;
    else if (path.endsWith('/runs')) json = { runs: [run] };
    else if (path.endsWith('/model-configurations') || path.endsWith('/inference-configurations')) json = { items: [] };
    else if (path.endsWith('/report')) json = {
      resultReportId: 'public-report', runId: 'public-run', completenessIndicator: 'complete',
      quality: { cases: [], aggregate: { totalCases: 10, passed: 9, passRate: 0.9 }, benchmarks: [] },
      performance: null,
    };
    else throw new Error(`Unexpected public request ${path}`);
    await route.fulfill({ json });
  });
  await page.goto('/');
  await expect(page.getByRole('heading', { name: /azure llm serving demo/i })).toBeVisible();
  await expect(page.getByText(/No active environments/)).toBeVisible();
  await page.getByLabel('Show torn-down environments').check();
  await expect(page.getByText('public-profile · eastus (blic-env)', { exact: true })).toBeVisible();
  await page.getByRole('link', { name: 'View experiments' }).click();
  await expect(page.getByRole('heading', { name: 'Experiments and saved reports' })).toBeVisible();
  await page.getByRole('link', { name: 'Open report summary' }).click();
  await expect(page.getByRole('heading', { name: 'Saved report summary' })).toBeVisible();
  await expect(page.getByText('90%', { exact: true })).toBeVisible();
  await page.getByText('Report provenance and test conditions').click();
  await expect(page.getByText('public-report', { exact: true })).toBeVisible();
  await expect(page.getByRole('link', { name: 'Sign in with Microsoft' }))
    .toHaveAttribute('href', '/.auth/login/aad?post_login_redirect_uri=%2Fquality%2Freport%2Fpublic-run%3FenvironmentId%3Dpublic-env');
  expect(apiCalls).toContain('/public/environments/public-env/runs/public-run/report');
  if (process.env.READONLY_SCREENSHOT_DIR) {
    await page.screenshot({ path: path.join(process.env.READONLY_SCREENSHOT_DIR, 'public-read-desktop.png'), fullPage: true });
  }
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByRole('navigation', { name: 'Primary' })).toBeHidden();
  await expect(page.getByRole('heading', { name: 'Saved report summary' })).toBeVisible();
  await expect.poll(() => page.evaluate(() =>
    document.documentElement.scrollWidth <= window.innerWidth,
  )).toBe(true);
  if (process.env.READONLY_SCREENSHOT_DIR) {
    await page.screenshot({ path: path.join(process.env.READONLY_SCREENSHOT_DIR, 'public-read-mobile.png'), fullPage: true });
  }
});

test('authentication outages do not block public browsing or unlock actions', async ({ page }) => {
  const methods: string[] = [];
  await page.route('http://localhost:8000/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    methods.push(route.request().method());
    if (path === '/session') {
      await route.fulfill({ status: 503 });
    } else if (path === '/public/environments') {
      await route.fulfill({ json: { environments: [environment] } });
    } else if (path === '/public/environments/public-env') {
      await route.fulfill({ json: environment });
    } else if (path.endsWith('/runs')) {
      await route.fulfill({ json: { runs: [run] } });
    } else {
      await route.fulfill({ json: { items: [] } });
    }
  });
  await page.goto('/exercise?environmentId=public-env');
  await expect(page.getByText(/operator sign-in is unavailable/i)).toBeVisible();
  await expect(page.getByText('public-golden', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Send prompt' })).toBeDisabled();
  await page.keyboard.press('Enter');
  await expect(page.getByRole('textbox')).toHaveCount(0);
  await page.getByRole('link', { name: 'Teardown', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Preview and tear down' })).toBeDisabled();
  expect(methods.every((method) => method === 'GET')).toBe(true);
});
