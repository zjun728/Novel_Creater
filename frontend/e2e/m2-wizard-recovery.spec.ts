import { expect, test } from '@playwright/test'

import {
  assertExactWrites,
  observeRuntime,
  runtimeSensitiveValues,
  scanRuntimeEvidence,
} from './runtime-observer.mjs'

const recoveryWrites = [
  {
    method: 'POST',
    path: /\/story-engine-batches\/[^/]+\/reconcile$/,
    count: 2,
    statuses: [200],
  },
]

function requiredEnvironment(name: string): string {
  const value = process.env[name]
  if (!value) throw new Error(`Missing required browser test environment: ${name}`)
  return value
}

async function assertRecoveryRuntime(observer: ReturnType<typeof observeRuntime>) {
  const evidence = await observer.finish()
  const expectedReadMiss = (entry: { method: string, status: number, url: string }) => (
    entry.method === 'GET'
    && entry.status === 404
    && /\/contract-draft$/.test(new URL(entry.url).pathname)
  )
  const draftReadMisses = evidence.apiResponses.filter(expectedReadMiss)
  const unexpectedApiResponses = evidence.apiResponses.filter(entry => (
    (entry.status < 200 || entry.status >= 300) && !expectedReadMiss(entry)
  ))
  const unexpectedResponseFailures = evidence.responseFailures.filter(entry => (
    !/^404 GET .*\/contract-draft$/u.test(entry)
  ))
  const expectedConsoleErrors = evidence.consoleErrors.filter(entry => (
    /^error: Failed to load resource: the server responded with a status of 404 \(Not Found\)$/u.test(entry)
  ))
  const unexpectedConsoleErrors = evidence.consoleErrors.filter(entry => (
    !expectedConsoleErrors.includes(entry)
  ))

  expect(assertExactWrites(evidence, recoveryWrites)).toEqual({ writeCount: 2 })
  expect(draftReadMisses, 'load and reload each read the absent draft').toHaveLength(2)
  expect(unexpectedApiResponses, 'only the absent draft reads may return 404').toEqual([])
  expect(unexpectedResponseFailures, 'page responses must be successful').toEqual([])
  expect(evidence.apiResponses.filter(entry => entry.bodyReadError)).toEqual([])
  expect(evidence.apiResponses.filter(entry => entry.headersReadError)).toEqual([])
  expect(expectedConsoleErrors, 'each absent draft read produces one browser diagnostic').toHaveLength(2)
  expect(unexpectedConsoleErrors, 'no unexpected console.error is allowed').toEqual([])
  expect(evidence.pageErrors, 'uncaught page errors must stay empty').toEqual([])
  expect(evidence.requestFailures, 'network requests must not fail').toEqual([])
  expect(scanRuntimeEvidence(evidence, [
    ...runtimeSensitiveValues(),
    requiredEnvironment('BROWSER_TEST_DATABASE'),
  ])).toEqual({ matchCount: 0 })
}

test('discovers and explicitly reconciles interrupted Provider batches', async ({ page }) => {
  const observer = observeRuntime(page)

  await page.goto('/project/00000000-0000-0000-0000-000000000201')
  await expect(page.getByRole('heading', {
    name: '待恢复的故事发动机批次',
  })).toBeVisible()
  await expect(page.getByRole('button', { name: '核对批次 00000701' })).toBeVisible()
  await expect(page.getByRole('button', { name: '核对批次 00000702' })).toBeVisible()

  await page.getByRole('button', { name: '核对批次 00000701' }).click()
  await expect(page.getByText('结果未知，系统不会自动重试', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: '核对批次 00000702' }).click()
  await expect(page.getByText('未开始，已安全结束', { exact: true })).toBeVisible()

  await page.reload()
  await expect(page.getByRole('button', { name: '核对批次 00000701' })).toBeVisible()
  await expect(page.getByRole('button', { name: '核对批次 00000702' })).toHaveCount(0)

  await assertRecoveryRuntime(observer)
})
