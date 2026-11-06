import { expect, test } from '@playwright/test';

test('app loads', async ({ page }) => {
  await page.route('http://localhost:8000/session', (route) => route.fulfill({ status: 401 }));
  await page.goto('/');

  await expect(page.getByRole('heading', { name: /azure llm serving demo/i })).toBeVisible();
  await expect(page.getByText(/guided operator workflow/i)).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Explore the workflow' })).toBeVisible();
});

test('anonymous deep links explain protected actions without loading private data', async ({ page }) => {
  const apiCalls: string[] = [];
  await page.route('http://localhost:8000/**', async (route) => {
    apiCalls.push(new URL(route.request().url()).pathname);
    await route.fulfill({ status: 401 });
  });
  await page.goto('/quality/report/private-run');
  await expect(page.getByRole('heading', { name: 'Sign in to use the operator workspace' })).toBeVisible();
  await expect(page.getByRole('main').getByRole('link', { name: 'Sign in with Microsoft' }))
    .toHaveAttribute('href', '/.auth/login/aad?post_login_redirect_uri=%2Fquality%2Freport%2Fprivate-run');
  await page.getByRole('link', { name: 'Teardown', exact: true }).click();
  await expect(page.getByText('Review the teardown plan before removing an environment and its resources.')).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Sign in to use the operator workspace' })).toBeVisible();
  expect(apiCalls.length).toBeGreaterThan(0);
  expect([...new Set(apiCalls)]).toEqual(['/session']);
});
