import { defineConfig } from '@playwright/test'
import path from 'node:path'

const baseURL = process.env.PLAYWRIGHT_BASE_URL
const denyProxyURL = process.env.BROWSER_DENY_PROXY_URL
const ownedRoot = process.env.BROWSER_OWNED_ROOT
const artifactRoot = process.env.BROWSER_ARTIFACT_ROOT
const downloadRoot = process.env.BROWSER_DOWNLOAD_ROOT
const browserDownloadsRoot = process.env.BROWSER_BROWSER_DOWNLOADS_ROOT
const resultPath = process.env.BROWSER_RESULT_PATH
const pageEventLedgerPath = process.env.BROWSER_PAGE_EVENT_LEDGER_PATH
const normalize = value => { const resolved = path.resolve(value); return process.platform === 'win32' ? resolved.toLowerCase() : resolved }
if (!baseURL || !/^http:\/\/127\.0\.0\.1:\d+$/u.test(baseURL)) throw new Error('Phase8A requires an owned Vite server')
if (!denyProxyURL || !/^http:\/\/127\.0\.0\.1:\d+$/u.test(denyProxyURL)) throw new Error('Phase8A requires an owned deny proxy')
const allowedOrigins = JSON.parse(process.env.BROWSER_ALLOWED_ORIGINS || '[]')
if (!Array.isArray(allowedOrigins) || allowedOrigins.length !== 2 || !allowedOrigins.includes(baseURL)) throw new Error('Phase8A requires exact owned origins')
const paths = [ownedRoot, artifactRoot, downloadRoot, browserDownloadsRoot, resultPath, pageEventLedgerPath]
if (!paths.every(value => typeof value === 'string' && path.isAbsolute(value))) throw new Error('Phase8A requires absolute runner-owned paths')
if (![artifactRoot, downloadRoot, browserDownloadsRoot, resultPath, pageEventLedgerPath].every(value => normalize(path.dirname(value)) === normalize(ownedRoot))) throw new Error('Phase8A output paths must be direct children of the owned root')

const proxy = { server: denyProxyURL, bypass: allowedOrigins.map(value => new URL(value).host).join(',') }
const common = { browserName: 'chromium', headless: false, baseURL, proxy, acceptDownloads: true, actionTimeout: 12_000, navigationTimeout: 20_000, contextOptions: { reducedMotion: 'reduce' }, trace: 'off', screenshot: 'off', video: 'off' }

export default defineConfig({
  testDir: '.', outputDir: artifactRoot, preserveOutput: 'never', fullyParallel: false,
  workers: 1, timeout: 300_000, reporter: [['json', { outputFile: resultPath }]],
  projects: [
    { name: 'chromium-wide-100', use: { ...common, viewport: { width: 1440, height: 900 }, launchOptions: { downloadsPath: browserDownloadsRoot } } },
  ],
})
