import { expect, test } from '@playwright/test'

import {
  assertExactWrites,
  observeRuntime,
  runtimeSensitiveValues,
  scanRuntimeEvidence,
} from './runtime-observer.mjs'

const settingsWrites = [
  { method: 'POST', path: /\/corpus\/imports$/, count: 1, statuses: [200] },
]

function requiredEnvironment(name: string): string {
  const value = process.env[name]
  if (!value) throw new Error(`Missing required browser test environment: ${name}`)
  return value
}

async function assertSettingsRuntime(observer: ReturnType<typeof observeRuntime>) {
  const evidence = await observer.finish()
  const responseFor = (path: string) => evidence.apiResponses.find(entry => (
    entry.method === 'GET' && new URL(entry.url).pathname === path
  ))
  const styleInventory = responseFor('/api/assets/style-templates')
  const experienceInventory = responseFor('/api/assets/experience-cards')

  expect(assertExactWrites(evidence, settingsWrites)).toEqual({ writeCount: 1 })
  expect(evidence.apiResponses.filter(entry => entry.status < 200 || entry.status >= 300)).toEqual([])
  expect(evidence.responseFailures, 'page responses must be successful').toEqual([])
  expect(evidence.apiResponses.filter(entry => entry.bodyReadError)).toEqual([])
  expect(evidence.apiResponses.filter(entry => entry.headersReadError)).toEqual([])
  expect(evidence.consoleErrors, 'console.error must stay empty').toEqual([])
  expect(evidence.pageErrors, 'uncaught page errors must stay empty').toEqual([])
  expect(evidence.requestFailures, 'network requests must not fail').toEqual([])
  expect(styleInventory, 'the settings asset tab must load the style inventory API').toBeDefined()
  expect(JSON.parse(styleInventory?.body || 'null')).toHaveLength(10)
  expect(experienceInventory, 'the settings asset tab must load the experience inventory API').toBeDefined()
  expect(JSON.parse(experienceInventory?.body || 'null')).toHaveLength(64)
  expect(scanRuntimeEvidence(evidence, [
    ...runtimeSensitiveValues(),
    requiredEnvironment('BROWSER_TEST_DATABASE'),
  ])).toEqual({ matchCount: 0 })
}

test('reviews the complete assets and imports only the bounded synthetic corpus', async ({ page }) => {
  const observer = observeRuntime(page)

  await page.goto('/settings')
  await expect(page.getByRole('heading', { name: '创作基础设置' })).toBeVisible()

  await page.getByText('创作资产', { exact: true }).click()
  await expect(page.getByRole('heading', { name: '创作资产册' })).toBeVisible()
  await expect(page.getByText('writer-core-v1.1.0', { exact: true })).toBeVisible()
  await expect(page.getByText('10 / 10', { exact: true })).toBeVisible()
  await expect(page.getByText('64 / 64', { exact: true })).toBeVisible()

  await page.getByText('本机语料', { exact: true }).click()
  await expect(page.getByRole('heading', { name: '本机语料册' })).toBeVisible()
  await expect(page.getByText('synthetic-browser-corpus.txt', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: '导入此文件' }).click()
  const importedSources = page.getByRole('region', { name: '已导入语料修订' })
  const sourceCard = importedSources.getByRole('article').filter({
    has: page.getByText('synthetic-browser-corpus.txt', { exact: true }),
  })
  await expect(sourceCard.getByText('analyzed', { exact: true })).toBeVisible()

  await assertSettingsRuntime(observer)
})
