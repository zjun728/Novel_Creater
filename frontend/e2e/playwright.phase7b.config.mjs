import { defineConfig } from '@playwright/test'
import path from 'node:path'

const baseURL = process.env.PLAYWRIGHT_BASE_URL
const ownedRoot = process.env.BROWSER_OWNED_ROOT
const artifactRoot = process.env.BROWSER_ARTIFACT_ROOT
const resultPath = process.env.BROWSER_RESULT_PATH
// Loopback ownership: 127.0.0.1 only.
const normalize = value => {
  const resolved = path.resolve(value)
  return process.platform === 'win32' ? resolved.toLowerCase() : resolved
}

if (!baseURL || !/^http:\/\/127\.0\.0\.1:\d+$/u.test(baseURL)) {
  throw new Error('Phase7B requires an owned loopback Vite server')
}
const allowedOrigins = JSON.parse(process.env.BROWSER_ALLOWED_ORIGINS || '[]')
if (
  !Array.isArray(allowedOrigins)
  || allowedOrigins.length !== 2
  || !allowedOrigins.includes(baseURL)
  || allowedOrigins.some(value => !/^http:\/\/127\.0\.0\.1:\d+$/u.test(value))
  || new Set(allowedOrigins).size !== 2
) throw new Error('Phase7B requires exactly two loopback-only origins')
if (![ownedRoot, artifactRoot, resultPath].every(value => (
  typeof value === 'string' && path.isAbsolute(value)
))) throw new Error('Phase7B requires absolute runner-owned paths')
if (![artifactRoot, resultPath].every(value => (
  normalize(path.dirname(value)) === normalize(ownedRoot)
))) throw new Error('Phase7B output paths must be direct children of the owned root')

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
    actionTimeout: 10_000,
    navigationTimeout: 20_000,
    trace: 'off',
    screenshot: 'off',
    video: 'off',
  },
})
