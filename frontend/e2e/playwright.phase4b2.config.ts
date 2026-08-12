import { defineConfig } from '@playwright/test'
import path from 'node:path'


const baseURL = process.env.PLAYWRIGHT_BASE_URL
const denyProxyURL = process.env.BROWSER_DENY_PROXY_URL
const ownedRoot = process.env.BROWSER_OWNED_ROOT
const artifactRoot = process.env.BROWSER_ARTIFACT_ROOT
const resultPath = process.env.BROWSER_RESULT_PATH
function samePathIdentity(left: string, right: string) {
  const normalize = (value: string) => {
    const resolved = path.resolve(value)
    return process.platform === 'win32' ? resolved.toLowerCase() : resolved
  }
  return normalize(left) === normalize(right)
}
if (!baseURL || !/^http:\/\/127\.0\.0\.1:\d+$/u.test(baseURL)) {
  throw new Error('PLAYWRIGHT_BASE_URL must identify the owned local Vite server')
}
if (!denyProxyURL || !/^http:\/\/127\.0\.0\.1:\d+$/u.test(denyProxyURL)) {
  throw new Error('BROWSER_DENY_PROXY_URL must identify the owned local deny proxy')
}
let allowedOrigins: string[]
try {
  allowedOrigins = JSON.parse(process.env.BROWSER_ALLOWED_ORIGINS || '')
} catch {
  throw new Error('BROWSER_ALLOWED_ORIGINS must identify exact owned local origins')
}
if (
  !Array.isArray(allowedOrigins)
  || allowedOrigins.length !== 2
  || new Set(allowedOrigins).size !== allowedOrigins.length
  || !allowedOrigins.includes(baseURL)
  || allowedOrigins.some(value => (
    typeof value !== 'string'
    || !/^http:\/\/127\.0\.0\.1:\d+$/u.test(value)
    || new URL(value).origin !== value
  ))
  || allowedOrigins.includes(denyProxyURL)
) throw new Error('BROWSER_ALLOWED_ORIGINS must identify exact owned local origins')
if (![ownedRoot, artifactRoot, resultPath].every(path.isAbsolute)) {
  throw new Error('Phase4B2 requires one absolute runner-owned artifact root')
}
if (
  !samePathIdentity(path.dirname(artifactRoot), ownedRoot)
  || !samePathIdentity(path.dirname(resultPath), ownedRoot)
) throw new Error('Phase4B2 artifact root must stay inside its owned root')

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
      bypass: allowedOrigins.map(value => new URL(value).host).join(','),
    },
    actionTimeout: 10_000,
    navigationTimeout: 15_000,
    trace: 'off',
    screenshot: 'off',
    video: 'off',
  },
})
