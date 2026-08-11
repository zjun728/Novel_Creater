import { defineConfig } from '@playwright/test'
import path from 'node:path'

const baseURL = process.env.PLAYWRIGHT_BASE_URL
const denyProxyURL = process.env.BROWSER_DENY_PROXY_URL
const ownedRoot = process.env.BROWSER_OWNED_ROOT
const artifactRoot = process.env.BROWSER_ARTIFACT_ROOT
const downloadRoot = process.env.BROWSER_DOWNLOAD_ROOT
const corpusRoot = process.env.BROWSER_CORPUS_ROOT
const packageTempRoot = process.env.BROWSER_PACKAGE_TEMP_ROOT
const quarantineRoot = process.env.BROWSER_IMPORT_QUARANTINE_ROOT
const resultPath = process.env.BROWSER_RESULT_PATH
const normalize = value => {
  const resolved = path.resolve(value)
  return process.platform === 'win32' ? resolved.toLowerCase() : resolved
}

if (!baseURL || !/^http:\/\/127\.0\.0\.1:\d+$/u.test(baseURL)) throw new Error('Phase6C requires an owned Vite server')
if (!denyProxyURL || !/^http:\/\/127\.0\.0\.1:\d+$/u.test(denyProxyURL)) throw new Error('Phase6C requires an owned deny proxy')
const allowedOrigins = JSON.parse(process.env.BROWSER_ALLOWED_ORIGINS || '[]')
if (!Array.isArray(allowedOrigins) || allowedOrigins.length !== 2 || !allowedOrigins.includes(baseURL)) {
  throw new Error('Phase6C requires exact owned origins')
}
const paths = [
  ownedRoot, artifactRoot, downloadRoot, corpusRoot, packageTempRoot, quarantineRoot, resultPath,
]
if (!paths.every(value => typeof value === 'string' && path.isAbsolute(value))) {
  throw new Error('Phase6C requires absolute runner-owned paths')
}
if (![artifactRoot, downloadRoot, corpusRoot, packageTempRoot, quarantineRoot, resultPath]
  .every(value => normalize(path.dirname(value)) === normalize(ownedRoot))) {
  throw new Error('Phase6C output paths must be direct children of the owned root')
}

export default defineConfig({
  testDir: '.', outputDir: artifactRoot, preserveOutput: 'never', fullyParallel: false,
  workers: 1, timeout: 240_000, reporter: [['json', { outputFile: resultPath }]],
  use: {
    baseURL,
    proxy: {
      server: denyProxyURL,
      bypass: allowedOrigins.map(value => new URL(value).host).join(','),
    },
    actionTimeout: 12_000, navigationTimeout: 20_000,
    acceptDownloads: true, trace: 'off', screenshot: 'off', video: 'off',
  },
})
