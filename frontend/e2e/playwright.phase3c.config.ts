import { defineConfig } from '@playwright/test'
import path from 'node:path'


const baseURL = process.env.PLAYWRIGHT_BASE_URL
if (!baseURL || !/^http:\/\/127\.0\.0\.1:\d+$/u.test(baseURL)) {
  throw new Error('PLAYWRIGHT_BASE_URL must identify the owned local Vite server')
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
) {
  throw new Error('BROWSER_ALLOWED_ORIGINS must identify exact owned local origins')
}
const denyProxyURL = process.env.BROWSER_DENY_PROXY_URL
if (
  !denyProxyURL
  || !/^http:\/\/127\.0\.0\.1:\d+$/u.test(denyProxyURL)
  || new URL(denyProxyURL).origin !== denyProxyURL
  || allowedOrigins.includes(denyProxyURL)
) {
  throw new Error('BROWSER_DENY_PROXY_URL must identify the owned local deny proxy')
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
  throw new Error('Phase 3C requires one absolute runner-owned artifact root')
}
const root = path.resolve(ownedRoot)
const output = path.resolve(artifactRoot)
const result = path.resolve(resultPath)
if (
  path.dirname(output).toLowerCase() !== root.toLowerCase()
  || path.dirname(result).toLowerCase() !== root.toLowerCase()
) {
  throw new Error('Phase 3C artifact root must stay inside its owned root')
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
