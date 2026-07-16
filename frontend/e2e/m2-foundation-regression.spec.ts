import { expect, test } from '@playwright/test'

import {
  assertExactWrites,
  observeRuntime,
  runtimeSensitiveValues,
  scanRuntimeEvidence,
} from './runtime-observer.mjs'

function requiredEnvironment(name: string): string {
  const value = process.env[name]
  if (!value) throw new Error(`Missing required browser test environment: ${name}`)
  return value
}

async function assertFoundationRuntime(observer: ReturnType<typeof observeRuntime>) {
  const evidence = await observer.finish()
  const expectedReadMiss = (entry: { method: string, status: number, url: string }) => (
    entry.method === 'GET'
    && entry.status === 404
    && /\/contract-draft$/.test(new URL(entry.url).pathname)
  )
  const unexpectedApiResponses = evidence.apiResponses.filter(entry => (
    (entry.status < 200 || entry.status >= 300) && !expectedReadMiss(entry)
  ))
  const unexpectedResponseFailures = evidence.responseFailures.filter(entry => (
    !/^404 GET .*\/contract-draft$/u.test(entry)
  ))
  const bodyReadFailures = evidence.apiResponses.filter(entry => entry.bodyReadError)
  const headerReadFailures = evidence.apiResponses.filter(entry => entry.headersReadError)
  const expectedConsoleErrors = evidence.consoleErrors.filter(entry => (
    /^error: Failed to load resource: the server responded with a status of 404 \(Not Found\)$/u.test(entry)
  ))
  const unexpectedConsoleErrors = evidence.consoleErrors.filter(entry => (
    !expectedConsoleErrors.includes(entry)
  ))

  expect(assertExactWrites(evidence, [])).toEqual({ writeCount: 0 })
  expect(unexpectedApiResponses, 'only the absent draft read may return 404').toEqual([])
  expect(unexpectedResponseFailures, 'page responses must be successful').toEqual([])
  expect(bodyReadFailures, 'API response bodies must be readable').toEqual([])
  expect(headerReadFailures, 'API response headers must be readable').toEqual([])
  expect(expectedConsoleErrors, 'the absent draft produces one browser 404 diagnostic').toHaveLength(1)
  expect(unexpectedConsoleErrors, 'no unexpected console.error is allowed').toEqual([])
  expect(evidence.pageErrors, 'uncaught page errors must stay empty').toEqual([])
  expect(evidence.requestFailures, 'network requests must not fail').toEqual([])
  expect(scanRuntimeEvidence(evidence, [
    ...runtimeSensitiveValues(),
    requiredEnvironment('BROWSER_TEST_DATABASE'),
  ])).toEqual({ matchCount: 0 })
}

test('retains the writer-core v1.1 foundation on the formal project page', async ({ page }) => {
  const observer = observeRuntime(page)

  await page.goto('/project/00000000-0000-0000-0000-000000000201')

  await expect(page.getByRole('heading', { name: '合成浏览器验收项目' })).toBeVisible()
  await expect(page.getByRole('heading', { name: '本书创作契约' })).toBeVisible()
  await expect(page.getByText('writer-core-v1.1.0', { exact: true })).toBeVisible()
  await expect(page.getByText('Canon 0', { exact: true })).toBeVisible()
  await expect(page.getByText('Projection 0', { exact: true })).toBeVisible()
  await expect(page.getByText('状态同步', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '进入写作台' })).toBeDisabled()

  await assertFoundationRuntime(observer)
})
