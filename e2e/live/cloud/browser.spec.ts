import fs from 'node:fs/promises';
import { expect, test } from '@playwright/test';

test('actual main frontend renders the deployed model response and survives reload', async ({
  page,
}) => {
  const config = JSON.parse(await fs.readFile(process.env.LIVE_CLOUD_CONFIG!, 'utf8'));
  const prior = JSON.parse(await fs.readFile(process.env.LIVE_API_EVIDENCE!, 'utf8'));
  const evidenceFile = process.env.LIVE_BROWSER_EVIDENCE_FILE!;
  const errors: string[] = [];
  const evidence: Record<string, unknown> = {
    scope: 'real-main-cloud-browser',
    startedAt: new Date().toISOString(),
    status: 'failed',
    fullAcceptance: false,
    browserUrl: process.env.LIVE_BROWSER_URL,
    apiUrl: config.apiUrl,
    deployedSourceCommit: config.deployedSourceCommit,
    sourceProvenance: prior.sourceProvenance,
    harnessSourceCommit: prior.sourceCommit,
    modelRepo: config.modelRepo,
    checkpointRef: config.checkpointRef,
    environmentId: config.environmentId,
    browserErrors: errors,
  };
  page.on('pageerror', (error) => errors.push(error.message));
  try {
    expect(prior.scope).toBe('real-main-cloud-api');
    expect(prior.config).toEqual(config);
    expect(prior.checks.find(
      (check: { name: string }) => check.name === 'model-deploy-ready',
    )?.status).toBe('passed');
    const revisionId = prior.resources.deployment.deploymentRevisionId;
    evidence.revisionId = revisionId;
    await page.goto(`/exercise?environmentId=${encodeURIComponent(config.environmentId)}`);
    await expect(page.getByRole('heading', { name: 'Exercise a deployment' })).toBeVisible();
    await expect(page.getByText(revisionId, { exact: true })).toBeVisible();
    await page.getByRole('textbox', { name: 'Prompt', exact: true }).fill('Say hello.');
    await page.getByRole('textbox', { name: 'Parameters JSON', exact: true }).fill(
      JSON.stringify({ temperature: 0.0, max_tokens: 8 }),
    );
    const responsePromise = page.waitForResponse(
      (response) =>
        response.url() === `${config.apiUrl}/environments/${encodeURIComponent(config.environmentId)}/prompts` &&
        response.request().method() === 'POST',
    );
    await page.getByRole('button', { name: 'Submit prompt', exact: true }).click();
    const response = await responsePromise;
    evidence.httpStatus = response.status();
    expect(response.status()).toBe(200);
    const payload = await response.json();
    evidence.prompt = payload;
    expect(payload.responseText.trim()).not.toBe('');
    expect(payload.deploymentRevisionId).toBe(revisionId);
    expect(payload.activeRevision.deploymentRevisionId).toBe(revisionId);
    expect(payload.timing.ttftMs).toBeGreaterThan(0);
    await expect(page.getByText(payload.responseText, { exact: true })).toBeVisible();
    await expect(page.getByText('Time to first token', { exact: true })).toBeVisible();
    expect(errors).toEqual([]);
    await page.reload();
    await expect(
      page.getByText('No prompts submitted in this browser session yet', { exact: true }),
    ).toBeVisible();
    await expect(page.getByText(revisionId, { exact: true })).toBeVisible();
    expect(errors).toEqual([]);
    evidence.status = 'passed';
    evidence.historyClearedOnReload = true;
  } catch (error) {
    evidence.error = error instanceof Error ? error.message : String(error);
    throw error;
  } finally {
    evidence.endedAt = new Date().toISOString();
    await fs.writeFile(evidenceFile, JSON.stringify(evidence, null, 2), { mode: 0o600 });
  }
});
