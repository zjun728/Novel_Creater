import { defineConfig } from '@playwright/test'
import path from 'node:path'


const baseURL = process.env.PLAYWRIGHT_BASE_URL
if (!baseURL || !/^http:\/\/127\.0\.0\.1:\d+$/u.test(baseURL)) {
  throw new Error('PLAYWRIGHT_BASE_URL must identify the runner-owned local Vite server')
}
const corpusRoot = process.env.BROWSER_CORPUS_ROOT_SENTINEL
const artifactRoot = process.env.BROWSER_ARTIFACT_ROOT
if (!corpusRoot || !artifactRoot || !path.isAbsolute(artifactRoot)) {
  throw new Error('Phase 2A artifacts require one absolute runner-owned root')
}
const ownedRoot = path.dirname(path.resolve(corpusRoot))
const resolvedArtifactRoot = path.resolve(artifactRoot)
if (
  path.dirname(resolvedArtifactRoot).toLowerCase() !== ownedRoot.toLowerCase()
  || path.basename(resolvedArtifactRoot) !== 'phase2a-test-results'
) {
  throw new Error('Phase 2A artifact root must stay inside its runner-owned root')
}

export default defineConfig({
  testDir: './e2e',
  outputDir: resolvedArtifactRoot,
  preserveOutput: 'never',
  fullyParallel: false,
  workers: 1,
  timeout: 150_000,
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
