import { expect, test } from '@playwright/test';

test('app loads', async ({ page }) => {
  await page.goto('/');

  await expect(page.getByRole('heading', { name: /azure llm serving demo/i })).toBeVisible();
  await expect(page.getByText(/guided operator workflow/i)).toBeVisible();
});
