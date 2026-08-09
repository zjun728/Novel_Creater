import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { expect, test } from '@playwright/test'

import {
  assertExactWrites,
  assertNoPrivateEvidenceMarkers,
  assertRuntimeEvidenceHealthy,
  observeRuntime,
  runtimeSensitiveValues,
  scanRuntimeEvidence,
} from './runtime-observer.mjs'


const projectId = process.env.BROWSER_PROJECT_ID
const writerPath = `/projects/${String(projectId)}/write/chapters/1`
const allowedOrigins = JSON.parse(process.env.BROWSER_ALLOWED_ORIGINS || '[]')
const drafts = ['甲'.repeat(96), '乙'.repeat(112)]
const digest = (value: string) => createHash('sha256').update(value, 'utf8').digest('hex')


async function editorDigest(editor) {
  return digest(await editor.inputValue())
}


function assertHealthy(evidence) {
  assertRuntimeEvidenceHealthy(evidence, { allowedOrigins })
  assertExactWrites(evidence, [
    { method: 'PUT', path: /\/working-draft$/u, count: 2, statuses: [200] },
    { method: 'POST', path: /\/candidates$/u, count: 2, statuses: [201] },
    { method: 'POST', path: /\/candidates\/[^/]+\/load$/u, count: 1, statuses: [200] },
  ])
  assert.equal(evidence.responses.some(item => new URL(item.url).pathname.includes('/draft-operations')), false)
  assert.equal(scanRuntimeEvidence(evidence, runtimeSensitiveValues()).matchCount, 0)
  assertNoPrivateEvidenceMarkers([
    ...evidence.consoleMessages,
    ...evidence.consoleErrors,
    ...evidence.pageErrors,
    ...evidence.requestFailures,
    ...evidence.responseFailures,
  ])
}


test('@candidate-workbench saves two, compares two read-only drafts, and loads one', async ({ page }) => {
  const runtime = observeRuntime(page, { allowedOrigins })
  await page.goto(writerPath)
  await expect(page.getByRole('heading', { name: '章节工作台' })).toBeVisible()
  const editor = page.getByRole('textbox', { name: '章节正文工作稿' })
  const save = page.getByRole('button', { name: '保存为候选' })

  await editor.fill(drafts[0])
  await expect(page.getByText(/已暂存 \d{2}:\d{2}:\d{2}/u)).toBeVisible()
  await save.click()
  await expect(page.getByText('候选 1', { exact: true })).toBeVisible()

  await editor.fill(drafts[1])
  await expect.poll(() => editorDigest(editor)).toBe(digest(drafts[1]))
  await expect(page.getByText(/已暂存 \d{2}:\d{2}:\d{2}/u)).toBeVisible()
  await save.click()
  await expect(page.getByText('候选 2', { exact: true })).toBeVisible()

  await page.getByRole('checkbox', { name: '选择候选 1 进行比较' }).check()
  await page.getByRole('checkbox', { name: '选择候选 2 进行比较' }).check()
  const comparison = page.getByLabel('候选稿只读比较')
  await expect(comparison).toBeVisible()
  const panes = comparison.locator('pre')
  await expect(panes).toHaveCount(2)
  assert.equal(digest(String(await panes.nth(0).textContent())), digest(drafts[0]))
  assert.equal(digest(String(await panes.nth(1).textContent())), digest(drafts[1]))

  const firstCandidate = page.getByRole('listitem').filter({ hasText: '候选 1' })
  await firstCandidate.getByRole('button', { name: '载入为工作稿' }).click()
  await expect.poll(() => editorDigest(editor)).toBe(digest(drafts[0]))

  const evidence = await runtime.finish()
  assertHealthy(evidence)
})
