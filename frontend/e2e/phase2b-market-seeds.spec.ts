import { expect, test } from '@playwright/test'

import {
  assertExactWrites,
  observeRuntime,
  runtimeSensitiveValues,
  scanRuntimeEvidence,
} from './runtime-observer.mjs'


function requiredEnvironment(name: string) {
  const value = process.env[name]
  if (!value) throw new Error(`${name} is required from the Phase 2B runner`)
  return value
}


function requiredRunnerOrigin(name: string) {
  const value = requiredEnvironment(name)
  if (!/^http:\/\/127\.0\.0\.1:\d+$/u.test(value)) {
    throw new Error(`${name} must identify one exact runner-owned origin`)
  }
  return value
}


const PROJECT_ID = requiredEnvironment('BROWSER_PROJECT_ID')
const QIDIAN_FILE = requiredEnvironment('BROWSER_QIDIAN_SNAPSHOT_PATH')
const QQ_FILE = requiredEnvironment('BROWSER_QQ_SNAPSHOT_PATH')
const VITE_ORIGIN = requiredRunnerOrigin('BROWSER_VITE_ORIGIN')
const BACKEND_ORIGIN = requiredRunnerOrigin('BROWSER_BACKEND_ORIGIN')
if (VITE_ORIGIN === BACKEND_ORIGIN) {
  throw new Error('runner-owned Vite and backend origins must be distinct')
}
const PROJECT_PATH = `/projects/${PROJECT_ID}/seeds`


function sourceCard(page, name: string) {
  return page.locator('.source-sheet').filter({
    has: page.getByRole('heading', { name, exact: true }),
  })
}


function seedCard(page, name: string) {
  return page.locator('.seed-record').filter({
    has: page.getByRole('heading', { name, exact: true }),
  })
}


async function importSnapshot(page, sourceName: string, filePath: string) {
  const card = sourceCard(page, sourceName)
  const chooserPromise = page.waitForEvent('filechooser')
  await card.getByRole('button', { name: '手动导入快照', exact: true }).click()
  const chooser = await chooserPromise
  await chooser.setFiles(filePath)
  await expect(card.getByText('快照可用', { exact: true })).toBeVisible()
}


const SEED_FIELDS = Object.freeze([
  ['种子标题', 'title'],
  ['题材类型', 'genre'],
  ['一句话故事', 'logline'],
  ['主角底色', 'protagonist'],
  ['核心欲望', 'desire'],
  ['核心冲突', 'coreConflict'],
  ['世界压力', 'worldPressure'],
  ['开篇抓手', 'openingHook'],
  ['差异化支点', 'differentiation'],
])


function seedPayload(title: string, marker: string) {
  return {
    title,
    genre: '历史穿越',
    logline: `${marker}携残卷进入明代，以知识兑现换来一次次更危险的政治选择。`,
    protagonist: `${marker}谨慎、能忍，但无法坐视同伴被当作代价。`,
    desire: '建立一处能让普通人保存知识并改变命运的地方。',
    coreConflict: '每次利用知识破局，都会让更强势力来争夺解释权。',
    worldPressure: '朝堂、地方豪强与灾荒共同挤压人物的选择空间。',
    openingHook: '一页被焚毁的典籍在主角手中显出尚未发生的灾情。',
    differentiation: '知识并非万能外挂，而是持续制造群像立场冲突的筹码。',
  }
}


async function createManualSeed(page, title: string, marker: string) {
  await page.getByRole('button', { name: '新建种子', exact: true }).click()
  const editor = page.getByRole('region', { name: '种子九字段编辑器' })
  await expect(editor).toBeVisible()
  const payload = seedPayload(title, marker)
  for (const [label, key] of SEED_FIELDS) {
    const field = editor.locator('label').filter({ hasText: label })
    await expect(field).toHaveCount(1)
    await field.locator('input, textarea').fill(payload[key])
  }
  await editor.getByRole('button', { name: '保存种子', exact: true }).click()
  await expect(seedCard(page, title)).toBeVisible()
  await expect(editor).toHaveCount(0)
}


async function selectSeed(page, title: string, expectedGeneration: number) {
  const responsePromise = page.waitForResponse(response => (
    response.request().method() === 'PUT'
    && new URL(response.url()).pathname === `/api/projects/${PROJECT_ID}/selected-seed`
  ))
  await seedCard(page, title)
    .getByRole('button', { name: '立即选定', exact: true })
    .click()
  await expect(page.locator('.seed-operation-veil')).toBeVisible()
  expect((await responsePromise).status()).toBe(200)
  await expect(page.getByText(`选定代次 ${expectedGeneration}`, { exact: true }))
    .toBeVisible()
  const card = seedCard(page, title)
  await expect(card).toHaveClass(/seed-record--selected/u)
  await expect(card.locator('.n-tag').getByText('当前选定', { exact: true }))
    .toBeVisible()
  await expect(card.getByRole('button', { name: '当前选定', exact: true }))
    .toBeDisabled()
}


function observedWrites(evidence) {
  return (evidence.apiResponses || [])
    .filter(entry => !['GET', 'HEAD', 'OPTIONS'].includes(entry.method))
    .map(entry => ({
      method: entry.method,
      path: `${new URL(entry.url).pathname}${new URL(entry.url).search}`,
      status: entry.status,
    }))
}


test('accepts evidence, inspiration, A→B→A seed generation, and read-only boundaries', async ({
  page,
}) => {
  const runtime = observeRuntime(page)
  const sensitiveValues = [
    ...runtimeSensitiveValues(),
    requiredEnvironment('BROWSER_MODEL_SENTINEL'),
    requiredEnvironment('BROWSER_TRANSCRIPT_SENTINEL'),
  ]
  const checkpointSurfaces: Array<{ dom: string; visibleText: string }> = []
  let bodyError: unknown = null
  let auditError: unknown = null
  let expectedRefreshFailureURL = ''
  const settleRuntime = async () => {
    await page.waitForLoadState('networkidle')
    await runtime.settle()
  }
  const checkpoint = async (label: string) => {
    await settleRuntime()
    const [dom, visibleText] = await Promise.all([
      page.content(),
      page.locator('body').innerText(),
    ])
    expect(
      scanRuntimeEvidence({
        checkpointSurfaces: [{ dom, visibleText }],
      }, sensitiveValues),
      `runtime-sensitive content found at ${label}`,
    ).toEqual({ matchCount: 0 })
    checkpointSurfaces.push({ dom, visibleText })
  }

  try {
    await page.goto(PROJECT_PATH)
    await expect(page.getByRole('heading', {
      name: 'Phase 2B 市场与种子项目',
      exact: true,
    })).toBeVisible()
    const qidian = sourceCard(page, '起点新签榜')
    const qq = sourceCard(page, 'QQ 阅读男生人气榜')
    await expect(qidian.getByText('公开来源已核验', { exact: true })).toBeVisible()
    await expect(qq.getByText('仅手动导入', { exact: true })).toBeVisible()
    await expect(qq.getByRole('button', { name: '启用定时', exact: true }))
      .toBeDisabled()
    await expect(qq).toContainText('该来源仅支持手动导入')

    await importSnapshot(page, '起点新签榜', QIDIAN_FILE)
    await importSnapshot(page, 'QQ 阅读男生人气榜', QQ_FILE)
    await expect(page.getByText('2 份可用快照', { exact: true })).toBeVisible()
    await expect(page.getByText('综合榜', { exact: true })).toHaveCount(0)

    const qidianEvidence = page.locator('.snapshot-evidence-list details').filter({
      hasText: '起点新签榜',
    })
    await qidianEvidence.locator('summary').click()
    await expect(qidianEvidence.getByText('山河典籍录', { exact: true })).toBeVisible()
    const qqEvidence = page.locator('.snapshot-evidence-list details').filter({
      hasText: 'QQ 阅读男生人气榜',
    })
    await qqEvidence.locator('summary').click()
    await expect(qqEvidence.getByText('北境火种', { exact: true })).toBeVisible()

    await qidian.getByRole('button', { name: '启用定时', exact: true }).click()
    await expect(qidian.getByRole('button', { name: '停用定时', exact: true }))
      .toBeVisible()
    await qidian.getByRole('button', { name: '停用定时', exact: true }).click()
    await expect(qidian.getByRole('button', { name: '启用定时', exact: true }))
      .toBeVisible()

    const refreshFailurePromise = page.waitForResponse(response => (
      response.request().method() === 'POST'
      && /^\/api\/market-sources\/[^/]+\/refresh$/u.test(
        new URL(response.url()).pathname,
      )
    ))
    await qidian.getByRole('button', { name: '手动刷新', exact: true }).click()
    const refreshFailureResponse = await refreshFailurePromise
    expectedRefreshFailureURL = refreshFailureResponse.url()
    expect(refreshFailureResponse.status()).toBe(503)
    const refreshFailurePayload = await refreshFailureResponse.json()
    expect(Object.keys(refreshFailurePayload).sort()).toEqual([
      'code',
      'correlationId',
      'message',
    ])
    expect(refreshFailurePayload).toMatchObject({
      code: 'MARKET_TRANSPORT_FAILED',
      message: 'Market source transport failed',
    })
    expect(refreshFailurePayload.correlationId).toEqual(expect.any(String))
    expect(refreshFailurePayload.correlationId.length).toBeGreaterThan(0)
    await expect(qidian.getByText(
      '保留上次成功 · 最新刷新失败',
      { exact: true },
    )).toBeVisible()
    await expect(qidian).toContainText('MARKET_TRANSPORT_FAILED')
    await expect(qidianEvidence.getByText('山河典籍录', { exact: true })).toBeVisible()

    await page.getByRole('button', {
      name: '分析上述 2 份证据',
      exact: true,
    }).click()
    await expect(page.getByText(
      '覆盖起点与 QQ 阅读两份独立冻结快照。',
      { exact: true },
    )).toBeVisible()
    await expect(page.getByText('推断', { exact: true })).toHaveCount(2)
    await checkpoint('market-evidence')

    await page.getByRole('button', { name: /灵感讨论/u }).click()
    await page.getByPlaceholder(/怎样让主角使用永乐大典知识/u)
      .fill('请给一个能推动长篇群像冲突的具体切口。')
    const inspirationResponsePromise = page.waitForResponse(response => (
      response.request().method() === 'POST'
      && new URL(response.url()).pathname
        === `/api/projects/${PROJECT_ID}/seed-inspiration`
    ))
    await page.getByRole('button', { name: '发送讨论', exact: true }).click()
    const inspirationResponse = await inspirationResponsePromise
    expect(inspirationResponse.status()).toBe(200)
    const inspirationPayload = await inspirationResponse.json()
    expect(inspirationPayload.publicErrorCode).toBeNull()
    expect(inspirationPayload).toMatchObject({
      status: 'succeeded',
      assistantTurn: {
        role: 'assistant',
        content: '让知识优势分三次兑现，每次都迫使不同配角争夺解释权。',
      },
    })
    await expect(page.locator('.transcript').getByText(
      '让知识优势分三次兑现，每次都迫使不同配角争夺解释权。',
      { exact: true },
    )).toBeVisible()
    await expect(page.locator('.proposal-slip').getByText(
      '让知识优势分三次兑现，每次都迫使不同配角争夺解释权。',
      { exact: true },
    )).toBeVisible()
    await expect(page.getByText('建议尚未保存', { exact: true })).toBeVisible()

    await page.getByRole('button', { name: /已存种子/u }).click()
    await expect(page.getByText(
      '还没有候选种子。可以手动登记，也可以先讨论灵感。',
      { exact: true },
    )).toBeVisible()
    await createManualSeed(page, '典镇山河 A', '沈砚')
    await createManualSeed(page, '北境工坊 B', '陆衡')
    await createManualSeed(page, '海贸新局 C', '顾川')
    await expect(page.locator('.seed-record')).toHaveCount(3)

    await selectSeed(page, '典镇山河 A', 1)
    await selectSeed(page, '北境工坊 B', 2)
    await selectSeed(page, '典镇山河 A', 3)
    await expect(page.getByText('继续创作契约', { exact: true })).toBeVisible()

    await seedCard(page, '海贸新局 C')
      .getByRole('button', { name: '永久删除', exact: true })
      .click()
    const deleteDialog = page.getByRole('dialog').filter({
      hasText: '永久删除种子',
    })
    await expect(deleteDialog).toBeVisible()
    await deleteDialog.getByRole('button', {
      name: '确认永久删除',
      exact: true,
    }).click()
    await expect(deleteDialog).toBeHidden()
    await expect(seedCard(page, '海贸新局 C')).toHaveCount(0)

    await settleRuntime()
    await page.reload()
    await expect(page.getByText('选定代次 3', { exact: true })).toBeVisible()
    await page.getByRole('button', { name: /已存种子/u }).click()
    const reloadedSelection = seedCard(page, '典镇山河 A')
    await expect(reloadedSelection).toHaveClass(/seed-record--selected/u)
    await expect(reloadedSelection.locator('.n-tag').getByText(
      '当前选定',
      { exact: true },
    )).toBeVisible()
    await expect(reloadedSelection.getByRole('button', {
      name: '当前选定',
      exact: true,
    })).toBeDisabled()
    await settleRuntime()
    await page.goto(`/projects/${PROJECT_ID}/overview`)
    await expect(page.getByText('PROJECT OVERVIEW', { exact: true })).toBeVisible()
    await settleRuntime()
    await page.goBack()
    await expect(page).toHaveURL(new RegExp(`${PROJECT_PATH}$`, 'u'))
    await expect(page.getByText('选定代次 3', { exact: true })).toBeVisible()
    await settleRuntime()
    await page.goForward()
    await expect(page).toHaveURL(new RegExp(`/projects/${PROJECT_ID}/overview$`, 'u'))
    await settleRuntime()
    await page.goBack()
    await page.setViewportSize({ width: 390, height: 844 })
    await expect(page.getByRole('heading', {
      name: 'Phase 2B 市场与种子项目',
      exact: true,
    })).toBeVisible()
    await checkpoint('seed-generation-three')

    await settleRuntime()
    await page.goto('/projects')
    const projectCard = page.locator('.project-card').filter({
      has: page.getByRole('heading', {
        name: 'Phase 2B 市场与种子项目',
        exact: true,
      }),
    })
    await projectCard.locator('summary').click()
    const archiveResponsePromise = page.waitForResponse(response => (
      response.request().method() === 'POST'
      && new URL(response.url()).pathname === `/api/projects/${PROJECT_ID}/archive`
    ))
    await projectCard.getByRole('button', { name: '归档', exact: true }).click()
    expect((await archiveResponsePromise).status()).toBe(200)
    await expect(projectCard).toHaveCount(0)
    await settleRuntime()
    await page.goto(PROJECT_PATH)
    await expect(page.getByText('已归档 · 只读', { exact: true })).toBeVisible()
    await expect(qidian.getByRole('button', { name: '手动导入快照', exact: true }))
      .toBeDisabled()
    await page.getByRole('button', { name: /已存种子/u }).click()
    await expect(page.getByRole('button', { name: '新建种子', exact: true }))
      .toBeDisabled()
    await checkpoint('archived-read-only')
  } catch (error) {
    bodyError = error
  } finally {
    try {
      const evidence = await runtime.finish()
      const auditedEvidence = { ...evidence, checkpointSurfaces }
      try {
        assertExactWrites(auditedEvidence, [
          {
            method: 'POST',
            path: /^\/api\/market-sources\/[^/]+\/manual-import$/u,
            statuses: [200],
            count: 2,
          },
          {
            method: 'PUT',
            path: /^\/api\/market-sources\/[^/]+\/schedule$/u,
            statuses: [200],
            count: 2,
          },
          {
            method: 'POST',
            path: /^\/api\/market-sources\/[^/]+\/refresh$/u,
            statuses: [503],
            count: 1,
          },
          {
            method: 'POST',
            path: `/api/projects/${PROJECT_ID}/market-analyses`,
            statuses: [200],
            count: 1,
          },
          {
            method: 'POST',
            path: `/api/projects/${PROJECT_ID}/seed-inspiration`,
            statuses: [200],
            count: 1,
          },
          {
            method: 'POST',
            path: `/api/projects/${PROJECT_ID}/seeds`,
            statuses: [200],
            count: 3,
          },
          {
            method: 'PUT',
            path: `/api/projects/${PROJECT_ID}/selected-seed`,
            statuses: [200],
            count: 3,
          },
          {
            method: 'DELETE',
            path: /^\/api\/projects\/[^/]+\/seeds\/[^/]+$/u,
            statuses: [200],
            count: 1,
          },
          {
            method: 'POST',
            path: `/api/projects/${PROJECT_ID}/archive`,
            statuses: [200],
            count: 1,
          },
        ])
      } catch (error) {
        throw new Error(
          `${error instanceof Error ? error.message : String(error)}; `
          + `observed=${JSON.stringify(observedWrites(auditedEvidence))}`,
          { cause: error },
        )
      }
      expect(evidence.responseFailures).toEqual([
        `503 POST ${expectedRefreshFailureURL}`,
      ])
      expect(evidence.consoleErrors).toHaveLength(1)
      expect(evidence.consoleErrors[0]).toMatch(
        /^error: Failed to load resource: the server responded with a status of 503\b/u,
      )
      expect(evidence.pageErrors).toEqual([])
      expect(evidence.requestFailures).toEqual([])
      expect(evidence.apiResponses.filter(entry => entry.bodyReadError)).toEqual([])
      expect(evidence.requests.filter(entry => entry.bodyReadError)).toEqual([])
      const capturedRefreshFailures = evidence.apiResponses.filter(entry => (
        entry.url === expectedRefreshFailureURL
      ))
      expect(capturedRefreshFailures).toHaveLength(1)
      expect(capturedRefreshFailures[0]).toMatchObject({
        method: 'POST',
        status: 503,
        bodyReadError: '',
      })
      const capturedRefreshPayload = JSON.parse(capturedRefreshFailures[0].body)
      expect(Object.keys(capturedRefreshPayload).sort()).toEqual([
        'code',
        'correlationId',
        'message',
      ])
      expect(capturedRefreshPayload).toMatchObject({
        code: 'MARKET_TRANSPORT_FAILED',
        message: 'Market source transport failed',
      })
      expect(capturedRefreshPayload.correlationId).toEqual(expect.any(String))
      expect(capturedRefreshPayload.correlationId.length).toBeGreaterThan(0)
      const runnerOrigins = new Set([VITE_ORIGIN, BACKEND_ORIGIN])
      expect(evidence.requests.every(entry => (
        runnerOrigins.has(new URL(entry.url).origin)
      ))).toBe(true)
      expect(evidence.responses.every(entry => (
        runnerOrigins.has(new URL(entry.url).origin)
      ))).toBe(true)
      expect(evidence.apiResponses.every(entry => (
        new URL(entry.url).origin === BACKEND_ORIGIN
      ))).toBe(true)
      expect(new URL(page.url()).origin).toBe(VITE_ORIGIN)
      expect(scanRuntimeEvidence(auditedEvidence, sensitiveValues)).toEqual({
        matchCount: 0,
      })
    } catch (error) {
      auditError = error
    }
    if (bodyError && auditError) {
      throw new AggregateError(
        [bodyError, auditError],
        'Phase 2B behavior and runtime audit both failed',
      )
    }
    if (bodyError) throw bodyError
    if (auditError) throw auditError
  }
})
