import { expect, test, type Page } from '@playwright/test'

import {
  assertExactWrites,
  observeRuntime,
  runtimeSensitiveValues,
  scanRuntimeEvidence,
} from './runtime-observer.mjs'


function requiredEnvironment(name: string) {
  const value = process.env[name]
  if (!value) throw new Error(`${name} is required from the P0-C runner`)
  return value
}


const QIDIAN_FILE = requiredEnvironment('BROWSER_QIDIAN_SNAPSHOT_PATH')
const VITE_ORIGIN = requiredEnvironment('BROWSER_VITE_ORIGIN')
const BACKEND_ORIGIN = requiredEnvironment('BROWSER_BACKEND_ORIGIN')


function sourceCard(page: Page, name: string) {
  return page.locator('.source-card').filter({
    has: page.getByRole('heading', { name, exact: true }),
  })
}


async function waitForWrite(page: Page, method: string, pattern: RegExp) {
  return page.waitForResponse(response => (
    response.request().method() === method
    && pattern.test(new URL(response.url()).pathname)
  ))
}


async function saveSuggestion(page: Page, name: '保存为方向' | '保存为候选种子') {
  const button = page.getByRole('button', { name, exact: true }).last()
  await expect(button).toBeVisible()
  const responsePromise = waitForWrite(
    page,
    'POST',
    name === '保存为方向'
      ? /\/api\/topic-discussions\/[^/]+\/directions$/u
      : /\/api\/topic-discussions\/[^/]+\/candidates$/u,
  )
  await button.click()
  expect((await responsePromise).ok()).toBe(true)
}


test('accepts the complete author-owned topic discovery and project seed flow', async ({ page }) => {
  const runtime = observeRuntime(page, { allowedOrigins: [VITE_ORIGIN, BACKEND_ORIGIN] })
  let bodyFailure: unknown = null
  let auditFailure: unknown = null

  try {
    await page.goto('/topics/market')
    await expect(page.locator('.topic-header').getByRole('heading', { name: '选题中心', exact: true })).toBeVisible()
    for (const name of [
      '起点新签榜',
      'QQ 阅读男生人气榜',
      '番茄小说阅读榜',
      '七猫男生更新榜',
      '书旗公开书库',
      '纵横月票榜',
      '晋江季度作品积分榜',
      '黑岩钻石榜',
    ]) {
      await expect(sourceCard(page, name)).toBeVisible()
    }

    await expect(page.getByText(/启用定时|自动刷新|每隔/u)).toHaveCount(0)
    const sourceList = page.getByLabel('市场来源列表')
    await expect(sourceList).toBeVisible()
    expect(await sourceList.evaluate(element => ({
      overflowY: getComputedStyle(element).overflowY,
      scrollable: element.scrollHeight > element.clientHeight,
    }))).toEqual({ overflowY: 'auto', scrollable: true })

    const qidian = sourceCard(page, '起点新签榜')
    const chooserPromise = page.waitForEvent('filechooser')
    const importPromise = waitForWrite(page, 'POST', /\/api\/market-sources\/[^/]+\/manual-import$/u)
    await qidian.getByRole('button', { name: '手动导入快照', exact: true }).click()
    await (await chooserPromise).setFiles(QIDIAN_FILE)
    expect((await importPromise).ok()).toBe(true)
    await expect(qidian.getByText('快照可用', { exact: true })).toBeVisible()
    await qidian.getByRole('button', { name: '附加最新快照到讨论', exact: true }).click()
    await expect(qidian.getByRole('button', { name: '已附加到讨论', exact: true })).toBeVisible()

    const refreshPromise = waitForWrite(page, 'POST', /\/api\/market-sources\/[^/]+\/refresh$/u)
    await qidian.getByRole('button', { name: '手动刷新', exact: true }).click()
    expect((await refreshPromise).status()).toBe(503)
    await expect(qidian.getByText('保留上次成功 · 最新刷新失败', { exact: true })).toBeVisible()
    await expect(qidian.getByRole('button', { name: '已附加到讨论', exact: true })).toBeVisible()

    await page.getByLabel('新讨论标题').fill('从县城秩序重建开始')
    const createDiscussion = waitForWrite(page, 'POST', /\/api\/topic-discussions$/u)
    await page.getByRole('button', { name: '开始讨论', exact: true }).click()
    expect((await createDiscussion).status()).toBe(200)
    await page.getByLabel('继续讨论').fill('请结合证据提出一个方向和一个完整候选种子。')
    const firstMessage = waitForWrite(page, 'POST', /\/api\/topic-discussions\/[^/]+\/messages$/u)
    await page.getByRole('button', { name: '发送给 AI', exact: true }).click()
    expect((await firstMessage).ok()).toBe(true)
    await expect(page.getByText('典镇山河', { exact: true })).toBeVisible()

    await saveSuggestion(page, '保存为方向')
    await saveSuggestion(page, '保存为候选种子')

    await page.goto('/topics/directions')
    await expect(page.getByRole('heading', { name: '基层秩序建设型东方玄幻', exact: true })).toBeVisible()
    await page.goto('/topics/candidates')
    await expect(page.getByRole('heading', { name: '典镇山河', exact: true })).toBeVisible()
    await expect(page.getByText('当前候选 · 版本 1', { exact: true })).toBeVisible()

    await page.goBack()
    await expect(page).toHaveURL(/\/topics\/directions$/u)
    await page.goForward()
    await expect(page).toHaveURL(/\/topics\/candidates$/u)
    await page.reload()
    await expect(page.getByText('当前候选 · 版本 1', { exact: true })).toBeVisible()

    await page.getByRole('button', { name: '继续讨论', exact: true }).click()
    await expect(page).toHaveURL(/\/topics\/discussions$/u)
    await expect(page.getByText('正在继续讨论：典镇山河 · 版本 1', { exact: true })).toBeVisible()
    await page.getByLabel('继续讨论').fill('把人物付出的政治代价写进第二版故事承诺。')
    const secondMessage = waitForWrite(page, 'POST', /\/api\/topic-discussions\/[^/]+\/messages$/u)
    await page.getByRole('button', { name: '发送给 AI', exact: true }).click()
    expect((await secondMessage).ok()).toBe(true)
    await saveSuggestion(page, '保存为候选种子')

    await page.goto('/topics/candidates')
    await expect(page.getByText('当前候选 · 版本 2', { exact: true })).toBeVisible()
    await expect(page.getByRole('region', { name: '候选种子版本历史' }).getByRole('button')).toHaveCount(2)
    await page.getByRole('button', { name: '创建项目', exact: true }).click()
    const dialog = page.getByRole('dialog', { name: '从指定版本创建项目' })
    await expect(dialog.getByText('候选版本 2', { exact: true })).toBeVisible()
    await expect(dialog.getByLabel('项目名称')).toHaveValue('典镇山河')
    const handoff = waitForWrite(page, 'POST', /\/api\/topic-candidates\/[^/]+\/versions\/2\/projects$/u)
    await dialog.getByRole('button', { name: '创建项目并检查种子', exact: true }).click()
    expect((await handoff).status()).toBe(200)
    await expect(page).toHaveURL(/\/projects\/[^/]+\/seeds$/u)

    const seed = page.locator('.seed-record').filter({ hasText: '典镇山河' })
    await expect(seed.getByText('待确认', { exact: true })).toBeVisible()
    await expect(seed.getByText('来源：选题中心候选《典镇山河》版本 2', { exact: true })).toBeVisible()
    await expect(seed.getByText('县、州、国、天下四级扩张，可支撑二百万字以上', { exact: true })).toBeVisible()

    await seed.getByRole('button', { name: '编辑', exact: true }).click()
    const editor = page.getByRole('region', { name: '种子完整字段编辑器' })
    await editor.locator('label').filter({ hasText: '市场依据' }).locator('textarea').fill('作者复核：建设流与规则怪谈交叉方向成立。')
    const updateSeed = waitForWrite(page, 'PUT', /\/api\/projects\/[^/]+\/seeds\/[^/]+$/u)
    await editor.getByRole('button', { name: '保存种子', exact: true }).click()
    expect((await updateSeed).ok()).toBe(true)
    await expect(seed.getByText('作者复核：建设流与规则怪谈交叉方向成立。', { exact: true })).toBeVisible()
    await expect(page.locator('.seed-operation-veil')).toHaveCount(0)

    await seed.getByRole('button', { name: '确认这个种子并进入创作契约', exact: true }).click()
    const confirmDialog = page.locator('.seed-confirm-dialog').filter({ hasText: '确认创作种子' })
    await expect(confirmDialog).toBeVisible()
    const selectRequest = page.waitForRequest(request => (
      request.method() === 'PUT'
      && /\/api\/projects\/[^/]+\/selected-seed$/u.test(new URL(request.url()).pathname)
    ))
    const selectSeed = waitForWrite(page, 'PUT', /\/api\/projects\/[^/]+\/selected-seed$/u)
    const confirmSelection = confirmDialog.getByRole('button', { name: '确认这个种子并进入创作契约', exact: true })
    await expect(confirmSelection).toBeEnabled()
    await confirmSelection.click()
    const selectionOutcome = await Promise.race([
      selectRequest.then(() => 'request'),
      page.getByText(/当前种子操作不被服务端允许|种子确认失败/u).waitFor().then(() => 'client-rejection'),
    ])
    expect(selectionOutcome).toBe('request')
    expect((await selectSeed).ok()).toBe(true)
    await expect(seed.getByText('当前选定', { exact: true })).toBeVisible()
    await expect(seed.getByRole('button', { name: '编辑', exact: true })).toHaveCount(0)

    await page.goto('/topics/candidates')
    const archive = waitForWrite(page, 'POST', /\/api\/topic-candidates\/[^/]+\/archive$/u)
    await page.getByRole('button', { name: '归档', exact: true }).click()
    expect((await archive).ok()).toBe(true)
    await page.getByRole('button', { name: '归档记录', exact: true }).click()
    await page.locator('.record-list').getByRole('button', { name: /典镇山河/u }).click()
    await expect(page.getByText('已归档 · 版本 2', { exact: true })).toBeVisible()
    await expect(page.getByRole('region', { name: '候选种子版本历史' }).getByRole('button')).toHaveCount(2)

    await page.setViewportSize({ width: 390, height: 844 })
    await page.reload()
    await expect(page.locator('.topic-header').getByRole('heading', { name: '选题中心', exact: true })).toBeVisible()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  } catch (failure) {
    bodyFailure = failure
  } finally {
    try {
      const evidence = await runtime.finish()
      expect(evidence.networkAccess).toMatchObject({
        forbiddenRequestCount: 0,
        forbiddenResponseCount: 0,
      })
      expect(scanRuntimeEvidence(evidence, runtimeSensitiveValues()).matchCount).toBe(0)
      assertExactWrites(evidence, [
        { method: 'POST', path: /\/api\/market-sources\/[^/]+\/manual-import$/u, count: 1, statuses: [200] },
        { method: 'POST', path: /\/api\/market-sources\/[^/]+\/refresh$/u, count: 1, statuses: [503] },
        { method: 'POST', path: '/api/topic-discussions', count: 1, statuses: [200] },
        { method: 'POST', path: /\/api\/topic-discussions\/[^/]+\/messages$/u, count: 2, statuses: [200] },
        { method: 'POST', path: /\/api\/topic-discussions\/[^/]+\/directions$/u, count: 1, statuses: [200] },
        { method: 'POST', path: /\/api\/topic-discussions\/[^/]+\/candidates$/u, count: 2, statuses: [200] },
        { method: 'POST', path: /\/api\/topic-candidates\/[^/]+\/versions\/2\/projects$/u, count: 1, statuses: [200] },
        { method: 'PUT', path: /\/api\/projects\/[^/]+\/seeds\/[^/]+$/u, count: 1, statuses: [200] },
        { method: 'PUT', path: /\/api\/projects\/[^/]+\/selected-seed$/u, count: 1, statuses: [200] },
        { method: 'POST', path: /\/api\/topic-candidates\/[^/]+\/archive$/u, count: 1, statuses: [200] },
      ])
    } catch (failure) {
      auditFailure = failure
    }
  }

  if (bodyFailure) throw bodyFailure
  if (auditFailure) throw auditFailure
})
