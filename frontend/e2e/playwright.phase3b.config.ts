import { defineConfig } from '@playwright/test'
import path from 'node:path'


const baseURL = process.env.PLAYWRIGHT_BASE_URL
if (!baseURL || !/^http:\/\/127\.0\.0\.1:\d+$/u.test(baseURL)) {
  throw new Error('PLAYWRIGHT_BASE_URL must identify the owned local Vite server')
}
const ownedRoot = process.env.BROWSER_OWNED_ROOT
const artifactRoot = process.env.BROWSER_ARTIFACT_ROOT
const resultPath = process.env.BROWSER_RESULT_PATH
if (
  !ownedRoot
  || !artifactRoot
  || !resultPath
  || !path.isAbsolute(ownedRoot)
  || !path.isAbsolute(artifactRoot)
  || !path.isAbsolute(resultPath)
) {
  throw new Error('Phase 3B requires one absolute runner-owned artifact root')
}
const root = path.resolve(ownedRoot)
const output = path.resolve(artifactRoot)
const result = path.resolve(resultPath)
if (
  path.dirname(output).toLowerCase() !== root.toLowerCase()
  || path.dirname(result).toLowerCase() !== root.toLowerCase()
) {
  throw new Error('Phase 3B artifact root must stay inside its owned root')
}

export default defineConfig({
  testDir: '.',
  outputDir: output,
  preserveOutput: 'never',
  fullyParallel: false,
  workers: 1,
  timeout: 180_000,
  reporter: [['json', { outputFile: result }]],
  use: {
    baseURL,
    actionTimeout: 10_000,
    navigationTimeout: 15_000,
    trace: 'off',
    screenshot: 'off',
    video: 'off',
  },
})
