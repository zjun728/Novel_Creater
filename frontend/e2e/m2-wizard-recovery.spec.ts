import { expect, test, type Page } from '@playwright/test'

import {
  assertExactWrites,
  observeRuntime,
  runtimeSensitiveValues,
  scanRuntimeEvidence,
} from './runtime-observer.mjs'
import { SYNTHETIC_STORY_ENGINE_OPTIONS } from './synthetic-story-engine-options.mjs'

const recoveryWrites = [
  { method: 'POST', path: /\/story-engine-batches\/manual$/, count: 2, statuses: [201] },
  { method: 'PUT', path: /\/contract-draft$/, count: 2, statuses: [200, 409] },
  { method: 'POST', path: /\/story-engine-batches\/[^/]+\/reconcile$/, count: 2, statuses: [200] },
]

async function createManualEngine(page: Page) {
  await page.getByRole('button', { name: '高级手动 JSON' }).click()
  await page.getByRole('textbox').fill(JSON.stringify(SYNTHETIC_STORY_ENGINE_OPTIONS))
  await page.getByRole('button', { name: '建立手动三案' }).click()
  await expect(page.getByRole('radio')).toHaveCount(3)
  await page.getByRole('radio', { name: /潮钟追凶/ }).click()
}

async function assertRecoveryRuntime(observers: Array<ReturnType<typeof observeRuntime>>) {
  const parts = await Promise.all(observers.map(observer => observer.finish()))
  const evidence = {
    requests: parts.flatMap(part => part.requests),
    apiResponses: parts.flatMap(part => part.apiResponses),
    consoleMessages: parts.flatMap(part => part.consoleMessages),
    consoleErrors: parts.flatMap(part => part.consoleErrors),
    pageErrors: parts.flatMap(part => part.pageErrors),
    requestFailures: parts.flatMap(part => part.requestFailures),
    responseFailures: parts.flatMap(part => part.responseFailures),
    pageContent: parts.map(part => part.pageContent).join('\n'),
  }
  const expectedReadMiss = (entry: { method: string, status: number, url: string }) => (
    entry.method === 'GET'
    && entry.status === 404
    && /\/contract-draft$/.test(new URL(entry.url).pathname)
  )
  const expectedDraftConflict = (entry: { method: string, status: number, url: string }) => (
    entry.method === 'PUT'
    && entry.status === 409
    && /\/contract-draft$/.test(new URL(entry.url).pathname)
  )
  const draftReadMisses = evidence.apiResponses.filter(expectedReadMiss)
  const draftConflicts = evidence.apiResponses.filter(expectedDraftConflict)
  const unexpectedApiResponses = evidence.apiResponses.filter(entry => (
    (entry.status < 200 || entry.status >= 300)
    && !expectedReadMiss(entry)
    && !expectedDraftConflict(entry)
  ))
  const unexpectedResponseFailures = evidence.responseFailures.filter(entry => (
    !/^404 GET .*\/contract-draft$/u.test(entry)
    && !/^409 PUT .*\/contract-draft$/u.test(entry)
  ))
  const expectedConsoleErrors = evidence.consoleErrors.filter(entry => (
    /^error: Failed to load resource: the server responded with a status of (?:404 \(Not Found\)|409 \(Conflict\))$/u.test(entry)
  ))
  const unexpectedConsoleErrors = evidence.consoleErrors.filter(entry => (
    !expectedConsoleErrors.includes(entry)
  ))

  expect(assertExactWrites(evidence, recoveryWrites)).toEqual({ writeCount: 6 })
  expect(draftReadMisses, 'both tabs and the confirmed recovery reload read the absent draft').toHaveLength(3)
  expect(draftConflicts, 'the stale tab receives exactly one real CAS conflict').toHaveLength(1)
  expect(unexpectedApiResponses, 'only absent draft reads and the intended stale write may fail').toEqual([])
  expect(unexpectedResponseFailures, 'page response failures are limited to the proven 404 and 409 cases').toEqual([])
  expect(evidence.apiResponses.filter(entry => entry.bodyReadError)).toEqual([])
  expect(evidence.apiResponses.filter(entry => entry.headersReadError)).toEqual([])
  expect(expectedConsoleErrors, 'three 404 reads and one 409 write produce browser diagnostics').toHaveLength(4)
  expect(unexpectedConsoleErrors, 'no unexpected console.error is allowed').toEqual([])
  expect(evidence.pageErrors, 'uncaught page errors must stay empty').toEqual([])
  expect(evidence.requestFailures, 'network requests must not fail').toEqual([])
  expect(scanRuntimeEvidence(evidence, runtimeSensitiveValues())).toEqual({ matchCount: 0 })
}

test('reconciles interrupted batches and proves real two-tab draft CAS', async ({ page }) => {
  const observer = observeRuntime(page)
  const secondPage = await page.context().newPage()
  const secondObserver = observeRuntime(secondPage)

  await Promise.all([
    page.goto('/project/00000000-0000-0000-0000-000000000201'),
    secondPage.goto('/project/00000000-0000-0000-0000-000000000201'),
  ])
  await expect(page.getByRole('heading', { name: '待恢复的故事发动机批次' })).toBeVisible()
  await expect(secondPage.getByRole('heading', { name: '本书创作契约' })).toBeVisible()
  await expect(page.getByRole('button', { name: '核对批次 00000701' })).toBeVisible()
  await expect(page.getByRole('button', { name: '核对批次 00000702' })).toBeVisible()

  await page.getByRole('button', { name: '核对批次 00000701' }).click()
  await expect(page.getByText('结果未知，系统不会自动重试', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: '核对批次 00000702' }).click()
  await expect(page.getByText('未开始，已安全结束', { exact: true })).toBeVisible()

  await page.reload()
  await expect(page.getByRole('button', { name: '核对批次 00000701' })).toBeVisible()
  await expect(page.getByRole('button', { name: '核对批次 00000702' })).toHaveCount(0)

  await createManualEngine(page)
  await createManualEngine(secondPage)
  await page.getByRole('button', { name: '保存并继续' }).click()
  await expect(page.getByRole('heading', { name: '三个可比较的写作气质' })).toBeVisible()

  await secondPage.getByRole('button', { name: '保存并继续' }).click()
  await expect(secondPage.getByText('草稿版本已经变化。请重新加载后再编辑，系统不会覆盖另一份修订。', {
    exact: true,
  })).toBeVisible()
  await expect(secondPage.getByRole('button', { name: '保存并继续' })).toBeDisabled()

  await assertRecoveryRuntime([observer, secondObserver])
  await secondPage.close()
})
