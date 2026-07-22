import { defineConfig } from '@playwright/test'
import path from 'node:path'


const baseURL = process.env.PLAYWRIGHT_BASE_URL
if (!baseURL || !/^http:\/\/127\.0\.0\.1:\d+$/u.test(baseURL)) {
  throw new Error('PLAYWRIGHT_BASE_URL must identify the runner-owned local Vite server')
}
const ownedRoot = process.env.BROWSER_OWNED_ROOT
const artifactRoot = process.env.BROWSER_ARTIFACT_ROOT
if (!ownedRoot || !artifactRoot || !path.isAbsolute(ownedRoot) || !path.isAbsolute(artifactRoot)) {
  throw new Error('Phase 2C requires one absolute runner-owned artifact root')
}
const root = path.resolve(ownedRoot)
const output = path.resolve(artifactRoot)
if (path.dirname(output).toLowerCase() !== root.toLowerCase()) {
  throw new Error('Phase 2C artifact root must stay inside its runner-owned root')
}

export default defineConfig({
  testDir: './e2e',
  outputDir: output,
  preserveOutput: 'never',
  fullyParallel: false,
  workers: 1,
  timeout: 180_000,
  reporter: 'list',
  use: {
    baseURL,
    actionTimeout: 10_000,
    navigationTimeout: 15_000,
    trace: 'off',
    screenshot: 'off',
    video: 'off',
  },
})
