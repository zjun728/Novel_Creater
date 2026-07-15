import { defineConfig } from '@playwright/test'


export default defineConfig({
  testDir: './e2e',
  outputDir: '../output/playwright/m2-test-results',
  fullyParallel: false,
  workers: 1,
  reporter: 'list',
  use: {
    baseURL: 'http://127.0.0.1:5173',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
})
