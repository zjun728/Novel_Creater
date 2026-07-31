import { defineConfig } from '@playwright/test'
import path from 'node:path'

const baseURL = process.env.PLAYWRIGHT_BASE_URL
const ownedRoot = process.env.BROWSER_OWNED_ROOT
const artifactRoot = process.env.BROWSER_ARTIFACT_ROOT
const resultPath = process.env.BROWSER_RESULT_PATH
const denyProxyURL = process.env.BROWSER_DENY_PROXY_URL
let allowedOrigins: string[]
try {
  allowedOrigins = JSON.parse(process.env.BROWSER_ALLOWED_ORIGINS || '')
} catch {
  throw new Error('Phase 3 needs exact owned browser origins')
}
if (
  !baseURL
  || !/^http:\/\/127\.0\.0\.1:\d+$/u.test(baseURL)
  || !ownedRoot
  || !artifactRoot
  || !resultPath
  || !denyProxyURL
  || !/^http:\/\/127\.0\.0\.1:\d+$/u.test(denyProxyURL)
  || !Array.isArray(allowedOrigins)
  || allowedOrigins.length !== 2
  || !allowedOrigins.includes(baseURL)
  || allowedOrigins.some(origin => !/^http:\/\/127\.0\.0\.1:\d+$/u.test(origin))
  || path.dirname(path.resolve(artifactRoot)) !== path.resolve(ownedRoot)
  || path.dirname(path.resolve(resultPath)) !== path.resolve(ownedRoot)
) throw new Error('Phase 3 needs an owned local browser environment')

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
    proxy: {
      server: denyProxyURL,
      bypass: allowedOrigins.map(origin => new URL(origin).host).join(','),
    },
    actionTimeout: 10_000,
    navigationTimeout: 15_000,
    trace: 'off',
    screenshot: 'off',
    video: 'off',
  },
})
