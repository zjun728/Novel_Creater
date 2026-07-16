import { expect, test } from '@playwright/test'

import {
  assertExactWrites,
  observeRuntime,
  runtimeSensitiveValues,
  scanRuntimeEvidence,
} from './runtime-observer.mjs'
import { SYNTHETIC_STORY_ENGINE_OPTIONS } from './synthetic-story-engine-options.mjs'

const manualWizardWrites = [
  { method: 'PUT', path: /\/selected-seed$/, count: 1, statuses: [200] },
  { method: 'POST', path: /\/story-engine-batches\/manual$/, count: 1, statuses: [201] },
  { method: 'PUT', path: /\/contract-draft$/, count: 3, statuses: [200] },
  { method: 'POST', path: /\/contracts\/preview$/, count: 1, statuses: [200] },
  { method: 'POST', path: /\/contracts\/confirm$/, count: 1, statuses: [201] },
]

function requiredEnvironment(name: string): string {
  const value = process.env[name]
  if (!value) throw new Error(`Missing required browser test environment: ${name}`)
  return value
}

async function assertManualRuntime(observer: ReturnType<typeof observeRuntime>) {
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

  expect(assertExactWrites(evidence, manualWizardWrites)).toEqual({ writeCount: 7 })
  expect(draftReadMisses, 'the initial and confirmed reloads read the absent draft').toHaveLength(2)
  expect(unexpectedApiResponses, 'only the absent draft reads may return 404').toEqual([])
  expect(unexpectedResponseFailures, 'page responses must be successful').toEqual([])
  expect(evidence.apiResponses.filter(entry => entry.bodyReadError)).toEqual([])
  expect(evidence.apiResponses.filter(entry => entry.headersReadError)).toEqual([])
  expect(expectedConsoleErrors, 'each absent draft read produces one browser 404 diagnostic').toHaveLength(2)
  expect(unexpectedConsoleErrors, 'no unexpected console.error is allowed').toEqual([])
  expect(evidence.pageErrors, 'uncaught page errors must stay empty').toEqual([])
  expect(evidence.requestFailures, 'network requests must not fail').toEqual([])
  expect(scanRuntimeEvidence(evidence, [
    ...runtimeSensitiveValues(),
    requiredEnvironment('BROWSER_TEST_DATABASE'),
  ])).toEqual({ matchCount: 0 })
}

test('completes and confirms the five-step wizard with manual three-engine options', async ({ page }) => {
  const observer = observeRuntime(page)

  await page.goto('/project/00000000-0000-0000-0000-000000000201')
  await expect(page.getByRole('heading', { name: '本书创作契约' })).toBeVisible()

  await page.getByRole('button', { name: /选择种子/ }).click()
  const seedCard = page.getByRole('article').filter({
    has: page.getByRole('heading', { name: '雾港天文钟' }),
  })
  await seedCard.getByRole('button', { name: '选定并继续' }).click()

  await page.getByRole('button', { name: '高级手动 JSON' }).click()
  await page.getByRole('textbox').fill(JSON.stringify(SYNTHETIC_STORY_ENGINE_OPTIONS))
  await page.getByRole('button', { name: '建立手动三案' }).click()
  await expect(page.getByRole('radio')).toHaveCount(3)
  await page.getByRole('radio', { name: /潮钟追凶/ }).click()
  await page.getByRole('button', { name: '保存并继续' }).dblclick()

  await expect(page.getByRole('heading', { name: '三个可比较的写作气质' })).toBeVisible()
  await page.getByRole('button', { name: '返回故事发动机' }).click()
  await expect(page.getByRole('heading', { name: '选择能持续制造故事的发动机' })).toBeVisible()
  await page.getByRole('button', { name: /风格契约/ }).click()
  await expect(page.getByRole('heading', { name: '三个可比较的写作气质' })).toBeVisible()
  const styleCard = page.getByRole('article').filter({
    has: page.getByRole('heading', { name: '克制悬疑型' }),
  })
  await styleCard.getByRole('button', { name: '设为主风格' }).click()
  await page.getByRole('button', { name: '保存并继续' }).click()

  await expect(page.getByRole('heading', { name: '作者明确允许参考的来源' })).toBeVisible()
  await page.getByRole('button', { name: '保存并继续' }).click()

  await expect(page.getByRole('heading', { name: '冻结快照' })).toBeVisible()
  await expect(page.getByText('可以签印', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: '一次确认完整契约', exact: true }).click()

  const contractHead = page.getByRole('article').filter({
    has: page.getByRole('heading', { name: '当前生效的创作契约' }),
  })
  await expect(contractHead).toBeVisible()
  await expect(contractHead.getByRole('row', {
    name: '正式修订 R1 当前状态 等待滚动规划',
    exact: true,
  })).toBeVisible()
  await expect(page.getByRole('button', { name: '进入写作台' })).toBeDisabled()

  await page.reload()
  await expect(page.getByRole('heading', { name: '本书创作契约' })).toBeVisible()
  await expect(page.getByRole('article').filter({
    has: page.getByRole('heading', { name: '当前生效的创作契约' }),
  })).toBeVisible()
  await expect(page.getByRole('row', {
    name: '正式修订 R1 当前状态 等待滚动规划',
    exact: true,
  })).toBeVisible()
  await expect(page.getByRole('button', { name: '创建新修订' })).toBeVisible()
  await expect(page.getByRole('button', { name: '保存并继续' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: '一次确认完整契约', exact: true })).toHaveCount(0)
  await expect(page.getByRole('button', { name: '进入写作台' })).toBeDisabled()

  await assertManualRuntime(observer)
})
