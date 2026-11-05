import fs from 'node:fs';
import { defineConfig, devices } from '@playwright/test';

function required(name: string): string {
  const value = process.env[name];
  if (!value) throw new Error(`${name} is required; cloud tests never start a local server.`);
  return value;
}

const browserUrl = new URL(required('LIVE_BROWSER_URL'));
if (
  browserUrl.protocol !== 'https:' || browserUrl.username || browserUrl.password ||
  browserUrl.search || browserUrl.hash ||
  ['localhost', '127.0.0.1', '[::1]'].includes(browserUrl.hostname)
) {
  throw new Error('LIVE_BROWSER_URL must identify the actual deployed HTTPS frontend.');
}
const storageState = required('LIVE_STORAGE_STATE');
if (!fs.existsSync(storageState)) throw new Error('Authorized SSO storage state is missing.');
required('LIVE_CLOUD_CONFIG');
required('LIVE_API_EVIDENCE');
required('LIVE_BROWSER_EVIDENCE_FILE');

export default defineConfig({
  testDir: '.',
  testMatch: 'browser.spec.ts',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 120_000,
  reporter: 'list',
  outputDir: './browser-results',
  use: {
    baseURL: browserUrl.toString(),
    storageState,
    // Authenticated traces/HAR/video can contain cookies and tokens.
    trace: 'off',
    video: 'off',
    screenshot: 'off',
    serviceWorkers: 'block',
  },
  projects: [{ name: 'main-cloud-chromium', use: { ...devices['Desktop Chrome'] } }],
});
