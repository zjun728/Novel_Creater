import { defineConfig } from '@playwright/test'
import path from 'node:path'

const baseURL = process.env.PLAYWRIGHT_BASE_URL
const denyProxyURL = process.env.BROWSER_DENY_PROXY_URL
const ownedRoot = process.env.BROWSER_OWNED_ROOT
const artifactRoot = process.env.BROWSER_ARTIFACT_ROOT
const resultPath = process.env.BROWSER_RESULT_PATH
const normalize = (value: string) => {
  const resolved = path.resolve(value)
  return process.platform === 'win32' ? resolved.toLowerCase() : resolved
}
if (!baseURL || !/^http:\/\/127\.0\.0\.1:\d+$/u.test(baseURL)) throw new Error('Phase5 requires an owned Vite server')
if (!denyProxyURL || !/^http:\/\/127\.0\.0\.1:\d+$/u.test(denyProxyURL)) throw new Error('Phase5 requires an owned deny proxy')
const allowedOrigins = JSON.parse(process.env.BROWSER_ALLOWED_ORIGINS || '[]')
if (!Array.isArray(allowedOrigins) || allowedOrigins.length !== 2 || !allowedOrigins.includes(baseURL)) {
  throw new Error('Phase5 requires exact owned origins')
}
if (![ownedRoot, artifactRoot, resultPath].every(value => typeof value === 'string' && path.isAbsolute(value))) {
  throw new Error('Phase5 requires absolute runner-owned artifacts')
}
if (normalize(path.dirname(artifactRoot)) !== normalize(ownedRoot) || normalize(path.dirname(resultPath)) !== normalize(ownedRoot)) {
  throw new Error('Phase5 artifacts must stay inside the owned root')
}

export default defineConfig({
  testDir: '.',
  outputDir: artifactRoot,
  preserveOutput: 'never',
  fullyParallel: false,
  workers: 1,
  timeout: 180_000,
  reporter: [['json', { outputFile: resultPath }]],
  use: {
    baseURL,
    proxy: { server: denyProxyURL, bypass: allowedOrigins.map(value => new URL(value).host).join(',') },
    actionTimeout: 10_000,
    navigationTimeout: 15_000,
    trace: 'off',
    screenshot: 'off',
    video: 'off',
  },
})
