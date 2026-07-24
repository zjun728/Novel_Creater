import { expect, test } from '@playwright/test'

import {
  assertExactWrites,
  assertRuntimeEvidenceHealthy,
  observeRuntime,
  runtimeSensitiveValues,
  scanRuntimeEvidence,
} from './runtime-observer.mjs'


const PROJECT_ID = String(process.env.BROWSER_PROJECT_ID || '')
const SCENARIO = String(process.env.BROWSER_SCENARIO_MODE || '')
if (!PROJECT_ID || !['manual', 'gateway'].includes(SCENARIO)) {
  throw new Error('Phase 3B browser scenario is not configured')
}
const OVERVIEW_PATH = `/projects/${PROJECT_ID}/overview`
const VOLUMES_PATH = `/projects/${PROJECT_ID}/planning/volumes`
const PLOTS_PATH = `/projects/${PROJECT_ID}/planning/plots`
const PLANNING_PATH = `/api/projects/${PROJECT_ID}/planning`
const GENERATION_PATH = new RegExp(
  `^/api/projects/${PROJECT_ID}/planning/drafts/[^/]+/generate$`,
  'u',
)
const DRAFT_PATH = new RegExp(
  `^/api/projects/${PROJECT_ID}/planning/drafts/[^/]+$`,
  'u',
)
const CONFIRM_PATH = new RegExp(
  `^/api/projects/${PROJECT_ID}/planning/drafts/[^/]+/confirm$`,
  'u',
)


function pathname(value: string) {
  return new URL(value).pathname
}


function isResponse(response, method: string, expectedPath: string | RegExp) {
  const actualPath = pathname(response.url())
  const pathMatches = typeof expectedPath === 'string'
    ? actualPath === expectedPath
    : expectedPath.test(actualPath)
  return response.request().method() === method && pathMatches
}


function isApiEvidence(item: { url?: unknown }) {
  try {
    const path = pathname(String(item?.url || ''))
    return path === '/api' || path.startsWith('/api/')
  } catch {
    return false
  }
}


function privateEvidenceSurfaces(evidence: any) {
  return [
    ...(evidence?.requests || [])
      .filter(isApiEvidence)
      .map(item => item.body || ''),
    ...(evidence?.apiResponses || [])
      .filter(isApiEvidence)
      .map(item => item.body || ''),
    ...(evidence?.consoleErrors || []),
    ...(evidence?.pageErrors || []),
  ].map(value => String(value).toLowerCase())
}


function assertNoPrivateEvidence(evidence: unknown) {
  const rendered = privateEvidenceSurfaces(evidence).join('\n')
  expect(rendered).not.toMatch(
    /"(?:prompt|rawprovider|inputmanifest|corpustext|apikey|authorization|password|dsn)"\s*:/u,
  )
  expect(rendered).not.toMatch(
    /\b(?:raw provider|input manifest|corpus text)\b/u,
  )
}


async function finishRuntime(
  runtime,
  bodyError: unknown,
  {
    responseFailureAllowlist = [],
    consoleErrorAllowlist = [],
    writes,
  },
) {
  let auditError: unknown = null
  let safeEvidence: {
    consoleErrors?: unknown[],
    responseFailures?: unknown[],
    apiResponses?: {
      method?: unknown,
      status?: unknown,
      url?: unknown,
    }[],
  } | null = null
  try {
    const evidence = await runtime.finish()
    expect(scanRuntimeEvidence(
      evidence,
      runtimeSensitiveValues(process.env),
    )).toEqual({ matchCount: 0 })
    assertNoPrivateEvidence(evidence)
    safeEvidence = evidence
    assertRuntimeEvidenceHealthy(evidence, {
      responseFailureAllowlist,
      consoleErrorAllowlist,
    })
    assertExactWrites(evidence, writes)
  } catch (error) {
    const publicDiagnostic = safeEvidence
      ? JSON.stringify({
          consoleErrors: safeEvidence.consoleErrors || [],
          responseFailures: safeEvidence.responseFailures || [],
          apiResponses: (safeEvidence.apiResponses || []).map(item => ({
            method: item.method,
            status: item.status,
            path: new URL(String(item.url)).pathname,
          })),
        })
      : ''
    auditError = error instanceof Error && publicDiagnostic
      ? new Error(`${error.message}; safe evidence: ${publicDiagnostic}`, {
          cause: error,
        })
      : error
  }
  if (bodyError && auditError) {
    const describe = (error: unknown) => (
      error instanceof Error ? (error.stack || error.message) : String(error)
    )
    throw new AggregateError(
      [bodyError, auditError],
      [
        'behavior and runtime audit failed',
        `behavior: ${describe(bodyError)}`,
        `runtime audit: ${describe(auditError)}`,
      ].join('\n'),
    )
  }
  if (bodyError) throw bodyError
  if (auditError) throw auditError
}


async function openFromAuthoritativeNextAction(page) {
  const preparationLoaded = page.waitForResponse(response => (
    isResponse(
      response,
      'GET',
      `/api/projects/${PROJECT_ID}/preparation`,
    )
  ))
  await page.goto(OVERVIEW_PATH)
  const preparationResponse = await preparationLoaded
  expect(preparationResponse.status()).toBe(200)
  const preparation = await preparationResponse.json()
  expect(
    ['establish_planning', 'continue_planning'],
    JSON.stringify({
      nextAction: preparation.nextAction,
      contract: preparation.contract,
      bible: preparation.bible,
      reasons: preparation.reasons,
    }),
  ).toContain(
    preparation.nextAction,
  )
  expect(preparation.targetPath).toBe(VOLUMES_PATH)
  const nextAction = page.locator('a.overview-next-action')
  await expect(nextAction).toHaveAttribute('href', VOLUMES_PATH)
  await nextAction.click()
  await expect(page).toHaveURL(new RegExp(`${VOLUMES_PATH}$`, 'u'))
  await expect(page.getByRole('heading', { name: '故事规划工作台' })).toBeVisible()
}


async function fillVolume(card, values) {
  await card.getByLabel('卷名', { exact: true }).fill(values.title)
  await card.getByLabel('核心变化', { exact: true }).fill(values.coreChange)
  await card.getByLabel('主要压力', { exact: true }).fill(values.mainPressure)
  await card.getByLabel('群像焦点（每行一项）', { exact: true })
    .fill(values.ensembleFocus)
  await card.getByLabel('本卷禁区（每行一项）', { exact: true })
    .fill(values.forbiddenEvents)
}


async function fillPlot(card, values) {
  await card.getByLabel('情节线名称', { exact: true }).fill(values.title)
  await card.getByRole('combobox').selectOption(values.plotType)
  await card.getByLabel('故事问题', { exact: true }).fill(values.storyQuestion)
  await card.getByLabel('未来走向', { exact: true }).fill(values.futureDirection)
  await card.getByLabel('预期回报', { exact: true }).fill(values.expectedPayoff)
  await card.getByLabel('相关人物（每行一项）', { exact: true })
    .fill(values.relatedCharacters)
}


test('@manual model-unready manual Draft saves reordered Volumes and Plots with canonical route history', async ({
  page,
}) => {
  const runtime = observeRuntime(page)
  let bodyError: unknown = null
  try {
    await openFromAuthoritativeNextAction(page)
    await page.getByRole('button', { name: '建立空白规划工作稿' }).click()
    await expect(page.getByText('规划模型尚未就绪；手工规划仍可继续。'))
      .toBeVisible()
    await expect(page.getByRole('button', {
      name: 'AI 生成当前规划工作稿',
    })).toBeDisabled()

    await page.getByRole('button', { name: '新增分卷' }).click()
    await page.getByRole('button', { name: '新增分卷' }).click()
    let cards = page.locator('.planning-editor .manuscript-card')
    await expect(cards).toHaveCount(2)
    await fillVolume(cards.nth(0), {
      title: '北境立足卷',
      coreChange: '主角从逃亡者变成能保护同伴的人。',
      mainPressure: '旧敌封锁北境商路。',
      ensembleFocus: '沈砚\n陆青禾',
      forbiddenEvents: '不提前揭露幕后人',
    })
    await fillVolume(cards.nth(1), {
      title: '京城暗潮卷',
      coreChange: '群像从临时结盟走向公开分裂。',
      mainPressure: '朝堂与边军同时索取代价。',
      ensembleFocus: '沈砚\n裴照',
      forbiddenEvents: '不让矛盾凭误会解决',
    })
    await cards.nth(1).getByRole('button', { name: '上移' }).click()
    cards = page.locator('.planning-editor .manuscript-card')
    await expect(cards.nth(0).getByLabel('卷名', { exact: true }))
      .toHaveValue('京城暗潮卷')

    await page.getByRole('link', { name: '情节线', exact: true }).click()
    await expect(page).toHaveURL(new RegExp(`${PLOTS_PATH}$`, 'u'))
    await page.getByRole('button', { name: '新增情节线' }).click()
    await page.getByRole('button', { name: '新增情节线' }).click()
    cards = page.locator('.planning-editor .manuscript-card')
    await expect(cards).toHaveCount(2)
    await fillPlot(cards.nth(0), {
      title: '残卷来历',
      plotType: 'main',
      storyQuestion: '残卷为何只在沈砚手中显字？',
      futureDirection: '线索从边城指向京城旧档。',
      expectedPayoff: '揭开第一层来历。',
      relatedCharacters: '沈砚\n陆青禾',
    })
    await fillPlot(cards.nth(1), {
      title: '旧盟裂缝',
      plotType: 'relationship',
      storyQuestion: '共同求生的人会因何分道扬镳？',
      futureDirection: '每次选择都改变彼此信任。',
      expectedPayoff: '一次有代价的重新结盟。',
      relatedCharacters: '沈砚\n裴照',
    })
    await cards.nth(1).getByRole('button', { name: '上移' }).click()
    cards = page.locator('.planning-editor .manuscript-card')
    await expect(cards.nth(0).getByLabel('情节线名称', { exact: true }))
      .toHaveValue('旧盟裂缝')

    const saved = page.waitForResponse(response => (
      isResponse(response, 'PUT', DRAFT_PATH)
    ))
    await page.getByRole('button', { name: '保存工作稿' }).click()
    expect((await saved).status()).toBe(200)
    await expect(page.getByText(
      '当前可保存为工作稿，但尚缺完整故事块 / 阶段 / 场景任务，不能确认。',
    )).toBeVisible()
    await expect(page.getByRole('button', { name: '预览并确认' })).toBeDisabled()

    await page.reload()
    await expect(page).toHaveURL(new RegExp(`${PLOTS_PATH}$`, 'u'))
    await expect(page.getByLabel('情节线名称', { exact: true }).first())
      .toHaveValue('旧盟裂缝')
    await page.getByRole('link', { name: '分卷', exact: true }).click()
    await expect(page).toHaveURL(new RegExp(`${VOLUMES_PATH}$`, 'u'))
    await page.goBack()
    await expect(page).toHaveURL(new RegExp(`${PLOTS_PATH}$`, 'u'))
    await page.goForward()
    await expect(page).toHaveURL(new RegExp(`${VOLUMES_PATH}$`, 'u'))
    await expect(page.getByLabel('卷名', { exact: true }).first())
      .toHaveValue('京城暗潮卷')
  } catch (error) {
    bodyError = error
  } finally {
    await finishRuntime(runtime, bodyError, {
      writes: [
        {
          method: 'POST',
          path: `/api/projects/${PROJECT_ID}/planning/drafts`,
          count: 1,
          statuses: [201],
        },
        {
          method: 'PUT',
          path: DRAFT_PATH,
          count: 1,
          statuses: [200],
        },
      ],
    })
  }
})


test('@gateway unknown result reconciles by GET into a complete valid aggregate and archived and superseded history stays read-only', async ({
  page,
}) => {
  const runtime = observeRuntime(page)
  let bodyError: unknown = null
  let generationPostCount = 0
  let generationResponsePath = ''
  page.on('request', outgoing => {
    if (
      outgoing.method() === 'POST'
      && GENERATION_PATH.test(pathname(outgoing.url()))
    ) generationPostCount += 1
  })
  try {
    await openFromAuthoritativeNextAction(page)
    const titleInput = page.getByLabel('卷名', { exact: true }).first()
    await expect(titleInput).toHaveValue('作者保存的第一卷')
    const beforeGeneration = await titleInput.inputValue()
    const unknown = page.waitForResponse(response => (
      isResponse(response, 'POST', GENERATION_PATH)
    ))
    await page.getByRole('button', {
      name: 'AI 生成当前规划工作稿',
    }).click()

    const overlay = page.locator('.streaming-overlay')
    await expect(overlay).toContainText('只读流式模式')
    await expect(page.locator('.workspace-scroll')).toHaveAttribute('inert', '')
    await expect(titleInput).toBeDisabled()
    await titleInput.fill('不得覆盖作者输入', { force: true }).catch(() => {})
    await expect(titleInput).toHaveValue(beforeGeneration)
    const unknownResponse = await unknown
    generationResponsePath = pathname(unknownResponse.url())
    expect(unknownResponse.status()).toBe(503)
    await expect(page.getByText('生成结果尚未完成权威核对')).toBeVisible()
    expect(generationPostCount).toBe(1)

    const byKey = page.waitForResponse(response => (
      response.request().method() === 'GET'
      && pathname(response.url()).includes('/planning/operations/by-idempotency-key/')
    ))
    await page.getByRole('button', { name: '核对原操作' }).click()
    const pendingResponse = await byKey
    expect(pendingResponse.status()).toBe(200)
    expect((await pendingResponse.json()).status).toBe('pending')
    await expect(page.getByText('原操作仍在进行，稍后核对')).toBeVisible()

    const operationRead = page.waitForResponse(response => (
      response.request().method() === 'GET'
      && pathname(response.url()).startsWith(
        `/api/projects/${PROJECT_ID}/planning/operations/`,
      )
      && !pathname(response.url()).includes('/by-idempotency-key/')
    ))
    const authorityReload = page.waitForResponse(response => (
      isResponse(response, 'GET', PLANNING_PATH)
    ))
    await page.getByRole('button', { name: '核对原操作' }).click()
    const terminalResponse = await operationRead
    const terminal = await terminalResponse.json()
    expect(terminal.status).toBe('succeeded')
    expect(terminal.loaded).toBe(true)
    expect((await authorityReload).status()).toBe(200)
    expect(generationPostCount).toBe(1)

    await expect(overlay).toHaveCount(0)
    await expect(titleInput).toHaveValue('AI 生成卷 1')
    const summary = page.locator('.aggregate-summary')
    await expect(summary).toContainText('完整规划摘要')
    await expect(summary).toContainText('夜渡封锁线')
    await expect(summary).toContainText('寻找缺口')
    await expect(summary).toContainText('观察换岗。')
    await expect(summary.locator('input, textarea, select, button')).toHaveCount(0)
    await expect(page.getByText(
      '聚合已完整。请先保存所有本地编辑，再确认不可变修订。',
    )).toBeVisible()

    await page.getByRole('button', { name: '预览并确认' }).click()
    const confirmation = page.getByRole('dialog', { name: '确认故事规划' })
    await expect(confirmation).toContainText('确认完整规划修订')
    await expect(confirmation).toContainText('故事块')
    const confirmedOne = page.waitForResponse(response => (
      isResponse(response, 'POST', CONFIRM_PATH)
    ))
    await confirmation.getByRole('button', { name: '确认并签印' }).click()
    expect((await confirmedOne).status()).toBe(201)

    await page.getByRole('button', { name: '建立空白规划工作稿' }).click()
    const adjustedTitle = page.getByLabel('卷名', { exact: true }).first()
    await adjustedTitle.fill('AI 生成卷 1 · 作者修订')
    const savedSecond = page.waitForResponse(response => (
      isResponse(response, 'PUT', DRAFT_PATH)
    ))
    await page.getByRole('button', { name: '保存工作稿' }).click()
    expect((await savedSecond).status()).toBe(200)
    await page.getByRole('button', { name: '预览并确认' }).click()
    const secondConfirmation = page.getByRole('dialog', { name: '确认故事规划' })
    const confirmedTwo = page.waitForResponse(response => (
      isResponse(response, 'POST', CONFIRM_PATH)
    ))
    await secondConfirmation.getByRole('button', { name: '确认并签印' }).click()
    expect((await confirmedTwo).status()).toBe(201)

    await page.getByRole('button', { name: '修订历史' }).click()
    let history = page.getByRole('dialog', { name: '规划修订历史' })
    const revisions = history.locator('.revision-card')
    await expect(revisions).toHaveCount(2)
    await expect(revisions.filter({ hasText: 'R2' })).toContainText('当前版本')
    await expect(revisions.filter({ hasText: 'R1' }))
      .toContainText('已被后续规划取代')
    await expect(history.getByRole('button')).toHaveCount(1)
    await history.getByRole('button', { name: '关闭' }).click()

    await page.goto('/projects')
    const projectCard = page.locator('.project-card').filter({
      has: page.getByRole('heading', { name: 'contract integration' }),
    })
    await projectCard.locator('summary').click()
    const archived = page.waitForResponse(response => (
      isResponse(response, 'POST', `/api/projects/${PROJECT_ID}/archive`)
    ))
    await projectCard.getByRole('button', { name: '归档', exact: true }).click()
    expect((await archived).status()).toBe(200)
    await expect(projectCard).toHaveCount(0)

    await page.goto(VOLUMES_PATH)
    await expect(page.getByText(
      '当前项目或规划修订为只读状态；可以查阅正文规划与历史，不能克隆、编辑或写入。',
    )).toBeVisible()
    await expect(page.getByRole('button', { name: '新增分卷' })).toHaveCount(0)
    await expect(page.getByRole('button', {
      name: 'AI 生成当前规划工作稿',
    })).toHaveCount(0)
    await expect(page.getByRole('button', { name: '保存工作稿' })).toHaveCount(0)
    await expect(page.getByRole('button', { name: '预览并确认' })).toHaveCount(0)
    await expect(page.getByLabel('卷名', { exact: true }).first()).toBeDisabled()

    await page.getByRole('button', { name: '修订历史' }).click()
    history = page.getByRole('dialog', { name: '规划修订历史' })
    const archivedCards = history.locator('.revision-card')
    await expect(archivedCards).toHaveCount(2)
    for (const card of await archivedCards.all()) {
      await expect(card.getByText('项目已归档', { exact: true })).toHaveCount(2)
      await expect(card.locator('button, input, textarea, select')).toHaveCount(0)
    }
    await expect(history.getByRole('button')).toHaveCount(1)
  } catch (error) {
    bodyError = error
  } finally {
    await finishRuntime(runtime, bodyError, {
      responseFailureAllowlist: [{
        status: 503,
        method: 'POST',
        pathname: generationResponsePath,
        count: 1,
      }],
      consoleErrorAllowlist: [{
        message: 'error: Failed to load resource: the server responded with a status of 503 (Service Unavailable)',
        count: 1,
        linkedResponseFailure: {
          status: 503,
          method: 'POST',
          pathname: generationResponsePath,
        },
      }],
      writes: [
        {
          method: 'POST',
          path: GENERATION_PATH,
          count: 1,
          statuses: [503],
        },
        {
          method: 'POST',
          path: CONFIRM_PATH,
          count: 2,
          statuses: [201],
        },
        {
          method: 'POST',
          path: `/api/projects/${PROJECT_ID}/planning/drafts`,
          count: 1,
          statuses: [201],
        },
        {
          method: 'PUT',
          path: DRAFT_PATH,
          count: 1,
          statuses: [200],
        },
        {
          method: 'POST',
          path: `/api/projects/${PROJECT_ID}/archive`,
          count: 1,
          statuses: [200],
        },
      ],
    })
  }
})
