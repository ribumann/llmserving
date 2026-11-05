import fs from 'node:fs/promises';
import { expect, test } from '@playwright/test';
import { requireLoopbackUrl } from '../playwright.live.config';

test('real browser renders an actual local-model response and revision', async ({
  page,
  request,
}) => {
  const apiUrl = requireLoopbackUrl('LIVE_API_URL');
  const ollamaUrl = requireLoopbackUrl('OLLAMA_BASE_URL');
  const environmentId = process.env.LIVE_ENVIRONMENT_ID;
  const revisionId = process.env.LIVE_DEPLOYMENT_REVISION_ID;
  const expectedDigest = process.env.OLLAMA_EXPECTED_DIGEST;
  const evidenceFile = process.env.LIVE_BROWSER_EVIDENCE_FILE;
  if (!environmentId || !revisionId || !expectedDigest || !evidenceFile) {
    throw new Error('Live browser test requires deployed environment, model and evidence inputs.');
  }
  expect((await request.get(`${apiUrl}/readyz`)).status()).toBe(200);
  expect((await request.get(`${apiUrl}/providers`)).status()).toBe(401);

  const browserErrors: string[] = [];
  page.on('pageerror', (error) => browserErrors.push(error.message));
  await page.goto(`/exercise?environmentId=${encodeURIComponent(environmentId)}`);
  await expect(page.getByRole('heading', { name: 'Exercise a deployment' })).toBeVisible();
  await expect(page.getByText(revisionId, { exact: true })).toBeVisible();
  await page.getByRole('textbox', { name: 'Prompt', exact: true }).fill('Say hello.');
  await page.getByRole('textbox', { name: 'Parameters JSON', exact: true }).fill(
    JSON.stringify({ temperature: 0.0, max_tokens: 8 }),
  );
  const responsePromise = page.waitForResponse(
    (response) =>
      response.url() === `${apiUrl}/environments/${environmentId}/prompts` &&
      response.request().method() === 'POST',
  );
  await page.getByRole('button', { name: 'Submit prompt', exact: true }).click();
  const response = await responsePromise;
  expect(response.status()).toBe(200);
  const payload = await response.json();
  expect(payload.responseText.trim()).not.toBe('');
  expect(payload.deploymentRevisionId).toBe(revisionId);
  expect(payload.activeRevision.deploymentRevisionId).toBe(revisionId);
  expect(payload.timing.ttftMs).toBeGreaterThan(0);
  await expect(page.getByText(payload.responseText, { exact: true })).toBeVisible();
  await expect(page.getByText('Time to first token', { exact: true })).toBeVisible();
  expect(browserErrors).toEqual([]);

  const tagsResponse = await request.get(`${ollamaUrl}/api/tags`);
  expect(tagsResponse.ok()).toBe(true);
  const model = (await tagsResponse.json()).models.find(
    (item: { name: string }) => item.name === 'qwen2.5:0.5b-instruct',
  );
  expect(model?.digest).toBe(expectedDigest);
  await page.reload();
  await expect(
    page.getByText('No prompts submitted in this browser session yet', { exact: true }),
  ).toBeVisible();
  await expect(page.getByText(revisionId, { exact: true })).toBeVisible();
  expect(browserErrors).toEqual([]);
  await fs.writeFile(
    evidenceFile,
    JSON.stringify(
      {
        commit: process.env.GITHUB_SHA ?? 'unrecorded',
        scope: 'Real loopback browser/API/PostgreSQL/CPU Ollama; local-demo, not Azure SSO',
        model,
        environmentId,
        revisionId,
        prompt: payload,
        anonymousRejected: true,
        historyClearedOnReload: true,
        passed: true,
      },
      null,
      2,
    ),
  );
});
