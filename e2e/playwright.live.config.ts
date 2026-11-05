import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { defineConfig, devices } from '@playwright/test';

const currentDirectory = path.dirname(fileURLToPath(import.meta.url));

export function requireLoopbackUrl(name: string): string {
  const value = process.env[name];
  if (!value) throw new Error(`${name} must explicitly identify a local test service.`);
  const url = new URL(value);
  if (url.protocol !== 'http:' || !['localhost', '127.0.0.1'].includes(url.hostname)) {
    throw new Error(`${name} must use HTTP on loopback.`);
  }
  return url.origin;
}

const apiUrl = requireLoopbackUrl('LIVE_API_URL');
requireLoopbackUrl('OLLAMA_BASE_URL');
if (process.env.AUTH_MODE !== 'local-demo' || process.env.APP_ENV !== 'test') {
  throw new Error('Live browser tests require explicit local-demo test authentication.');
}

export default defineConfig({
  testDir: './live',
  testMatch: 'exercise.spec.ts',
  fullyParallel: false,
  workers: 1,
  timeout: 120_000,
  reporter: 'list',
  outputDir: process.env.LIVE_BROWSER_TRACE_DIR ?? './live-test-results',
  use: {
    baseURL: 'http://127.0.0.1:4173',
    trace: 'retain-on-failure',
  },
  webServer: {
    command: 'npm run dev -- --host 127.0.0.1 --port 4173 --strictPort',
    cwd: path.resolve(currentDirectory, '../frontend'),
    url: 'http://127.0.0.1:4173',
    reuseExistingServer: false,
    env: {
      VITE_API_BASE_URL: apiUrl,
      VITE_DEMO_USER: 'presenter@example.com',
    },
    timeout: 120_000,
  },
  projects: [
    {
      name: 'real-local-chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
});
