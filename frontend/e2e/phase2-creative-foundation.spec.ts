import { expect, test } from '@playwright/test'
import { appendFileSync } from 'node:fs'

import {
  assertRuntimeEvidenceHealthy,
  observeRuntime,
  runtimeSensitiveValues,
  scanRuntimeEvidence,
} from './runtime-observer.mjs'


const STEP_LEDGER = process.env.BROWSER_STEP_LEDGER
if (!STEP_LEDGER) throw new Error('BROWSER_STEP_LEDGER is required')


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
  expect(
    scanRuntimeEvidence(evidence, runtimeSensitiveValues(process.env)).matchCount,
  ).toBe(0)
  recordStep('runtime-clean')
})
