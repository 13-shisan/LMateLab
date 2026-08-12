import { defineConfig } from '@playwright/test';
import process from 'node:process';

const baseURL = process.env.LMATELAB_PREVIEW_URL;
if (!baseURL) {
  throw new Error('LMATELAB_PREVIEW_URL is required; this suite never starts a login-node web server');
}

const viewports = [
  { name: 'desktop', width: 1440, height: 900 },
  { name: 'compact', width: 1024, height: 768 },
  { name: 'mobile', width: 390, height: 844 },
];

export default defineConfig({
  testDir: './e2e',
  timeout: 45_000,
  retries: 0,
  reporter: 'line',
  use: {
    baseURL,
    launchOptions: {
      args: ['--enable-unsafe-swiftshader'],
    },
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  outputDir: 'test-results/competition-preview',
  projects: viewports.map(({ name, width, height }) => ({
    name,
    use: { viewport: { width, height } },
  })),
});
