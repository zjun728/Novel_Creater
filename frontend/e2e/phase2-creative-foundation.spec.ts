import { expect, test } from '@playwright/test'
import { appendFileSync } from 'node:fs'

import {
  assertRuntimeEvidenceHealthy,
  observeRuntime,
  runtimeSensitiveValues,
  scanRuntimeEvidence,
} from './runtime-observer.mjs'


function requiredRunnerOrigin(name: string) {
  const value = process.env[name]
  if (!value || !/^http:\/\/127\.0\.0\.1:\d+$/u.test(value)) {
    throw new Error(`${name} must identify one exact runner-owned origin`)
  }
  return value
}


const VITE_ORIGIN = requiredRunnerOrigin('BROWSER_VITE_ORIGIN')
const BACKEND_ORIGIN = requiredRunnerOrigin('BROWSER_BACKEND_ORIGIN')
if (VITE_ORIGIN === BACKEND_ORIGIN) {
  throw new Error('runner-owned Vite and backend origins must be distinct')
}
const STEP_LEDGER = process.env.BROWSER_STEP_LEDGER
if (!STEP_LEDGER) throw new Error('BROWSER_STEP_LEDGER is required')
const SENSITIVE_VALUES = [
  ...runtimeSensitiveValues(process.env),
  process.env.BROWSER_TRANSCRIPT_SENTINEL,
].filter(value => typeof value === 'string' && value.length > 0)


function recordStep(step: string) {
  appendFileSync(STEP_LEDGER, step + '\n', { encoding: 'utf8' })
}


test('Phase 2 starts from the canonical project library', async ({ page }) => {
  const runtime = observeRuntime(page)
  let evidence
  try {
    recordStep('library-navigation-start')
    await page.goto('/projects')
    recordStep('library-navigation-finished')
    await expect(
      page.getByRole('heading', { name: '项目库', exact: true }),
    ).toBeVisible()
    recordStep('library-heading-visible')
    await expect(
      page.locator('.project-library-heading').getByRole(
        'button',
        { name: '新建项目', exact: true },
      ),
    ).toBeVisible()
    recordStep('library-button-visible')
    recordStep('library-visible')
  } finally {
    evidence = await runtime.finish()
  }

  assertRuntimeEvidenceHealthy(evidence)
  const runnerOrigins = new Set([VITE_ORIGIN, BACKEND_ORIGIN])
  expect(
    evidence.requests.every(entry => (
      runnerOrigins.has(new URL(entry.url).origin)
    )),
  ).toBe(true)
  expect(
    evidence.responses.every(entry => (
      runnerOrigins.has(new URL(entry.url).origin)
    )),
  ).toBe(true)
  expect(
    evidence.apiResponses.every(entry => (
      new URL(entry.url).origin === BACKEND_ORIGIN
    )),
  ).toBe(true)
  expect(new URL(page.url()).origin).toBe(VITE_ORIGIN)
  expect(
    scanRuntimeEvidence(evidence, SENSITIVE_VALUES).matchCount,
  ).toBe(0)
  recordStep('runtime-clean')
})
