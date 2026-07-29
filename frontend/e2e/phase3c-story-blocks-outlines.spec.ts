import { expect, test } from '@playwright/test'

import {
  assertExactWrites,
  assertNoPrivateEvidenceMarkers,
  assertRuntimeEvidenceHealthy,
  observeRuntime,
  publicRuntimeDiagnostic,
  runtimeSensitiveValues,
  scanRuntimeEvidence,
  settleNavigationBoundary,
} from './runtime-observer.mjs'


const PROJECT_ID = String(process.env.BROWSER_PROJECT_ID || '')
const SCENARIO = String(process.env.BROWSER_SCENARIO_MODE || '')
const FORMAL_SCENARIOS = [
  'manual',
  'gateway',
  'supersession',
  'archived',
  'missing-upstream',
  'canon-mismatch',
  'wrong-chapter',
]
if (!PROJECT_ID || !FORMAL_SCENARIOS.includes(SCENARIO)) {
  throw new Error('Phase 3C browser scenario is not configured')
}
let ALLOWED_RUNTIME_ORIGINS: string[]
try {
  ALLOWED_RUNTIME_ORIGINS = JSON.parse(
    process.env.BROWSER_ALLOWED_ORIGINS || '',
  )
} catch {
  throw new Error('Phase 3C browser origins are not configured')
}
if (
  !Array.isArray(ALLOWED_RUNTIME_ORIGINS)
  || ALLOWED_RUNTIME_ORIGINS.length !== 2
) {
  throw new Error('Phase 3C browser origins are not configured')
}

const OVERVIEW_PATH = `/projects/${PROJECT_ID}/overview`
const VOLUMES_PATH = `/projects/${PROJECT_ID}/planning/volumes`
const PLOTS_PATH = `/projects/${PROJECT_ID}/planning/plots`
const STORY_BLOCKS_PATH = `/projects/${PROJECT_ID}/planning/story-blocks`
const WRITER_PATH = `/projects/${PROJECT_ID}/write/chapters/1`
const WRONG_WRITER_PATH = `/projects/${PROJECT_ID}/write/chapters/2`
const PLANNING_PATH = `/api/projects/${PROJECT_ID}/planning`
const OUTLINE_CURRENT_PATH = `/api/projects/${PROJECT_ID}/chapter-outlines/current`
const PLANNING_DRAFT_PATH = new RegExp(
  `^/api/projects/${PROJECT_ID}/planning/drafts/[^/]+$`,
  'u',
)
const PLANNING_CONFIRM_PATH = new RegExp(
  `^/api/projects/${PROJECT_ID}/planning/drafts/[^/]+/confirm$`,
  'u',
)
const OUTLINE_DRAFTS_PATH = `/api/projects/${PROJECT_ID}/chapter-outlines/1/drafts`
const OUTLINE_DRAFT_PATH = new RegExp(
  `^${OUTLINE_DRAFTS_PATH}/[^/]+$`,
  'u',
)
const OUTLINE_CONFIRM_PATH = new RegExp(
  `^${OUTLINE_DRAFTS_PATH}/[^/]+/confirm$`,
  'u',
)
const OUTLINE_GENERATION_PATH = new RegExp(
  `^${OUTLINE_DRAFTS_PATH}/[^/]+/generate$`,
  'u',
)
const SESSION_PATH = `/api/projects/${PROJECT_ID}/chapter-sessions/1`


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
    ...(evidence?.consoleMessages || []),
    ...(evidence?.consoleErrors || []),
    ...(evidence?.pageErrors || []),
  ].map(value => String(value).toLowerCase())
}


function assertNoPrivateEvidence(evidence: unknown) {
  assertNoPrivateEvidenceMarkers(privateEvidenceSurfaces(evidence))
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
  let safeEvidence: any = null
  try {
    const evidence = await runtime.finish()
    expect(scanRuntimeEvidence(
      evidence,
      runtimeSensitiveValues(process.env),
    )).toEqual({ matchCount: 0 })
    assertNoPrivateEvidence(evidence)
    safeEvidence = evidence
    const health = assertRuntimeEvidenceHealthy(evidence, {
      responseFailureAllowlist,
      consoleErrorAllowlist,
    })
    if (!health.networkAccess) {
      throw new Error('Runtime HTTP access evidence is missing')
    }
    test.info().annotations.push({
      type: 'network-audit',
      description: JSON.stringify(health.networkAccess),
    })
    assertExactWrites(evidence, writes)
  } catch (error) {
    const publicDiagnostic = safeEvidence
      ? JSON.stringify(publicRuntimeDiagnostic(safeEvidence))
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
        'Phase 3C behavior and runtime audit failed',
        `behavior: ${describe(bodyError)}`,
        `runtime audit: ${describe(auditError)}`,
      ].join('\n'),
    )
  }
  if (bodyError) throw bodyError
  if (auditError) throw auditError
}


function waitForNamedResponse(page, label: string, predicate) {
  return page.waitForResponse(predicate).catch(error => {
    throw new Error(
      `Timed out waiting for ${label}; current path: ${pathname(page.url())}`,
      { cause: error },
    )
  })
}


async function fillVolume(page, title = '北境立足卷') {
  const card = page.locator('.planning-editor .manuscript-card').first()
  await card.getByLabel('卷名', { exact: true }).fill(title)
  await card.getByLabel('核心变化', { exact: true })
    .fill('主角从逃亡者变成能保护同伴的人。')
  await card.getByLabel('主要压力', { exact: true })
    .fill('旧敌封锁北境商路。')
  await card.getByLabel('群像焦点（每行一项）', { exact: true })
    .fill('沈砚\n陆青禾')
  await card.getByLabel('本卷禁区（每行一项）', { exact: true })
    .fill('不提前揭露幕后人')
}


async function fillPlot(page) {
  const card = page.locator('.planning-editor .manuscript-card').first()
  await card.getByLabel('情节线名称', { exact: true }).fill('残卷来历')
  await card.getByRole('combobox').selectOption('main')
  await card.getByLabel('故事问题', { exact: true })
    .fill('残卷为何只在沈砚手中显字？')
  await card.getByLabel('未来走向', { exact: true })
    .fill('线索从边城指向京城旧档。')
  await card.getByLabel('预期回报', { exact: true }).fill('揭开第一层来历。')
  await card.getByLabel('相关人物（每行一项）', { exact: true })
    .fill('沈砚\n陆青禾')
}


async function fillStoryBlock(page) {
  const card = page.locator('.story-block-card').first()
  await card.getByLabel('故事块标题', { exact: true }).fill('夜渡封锁线')
  await card.locator('.block-fields select').selectOption({ index: 1 })
  await card.getByRole('checkbox').first().check()
  await card.getByLabel('进入情境', { exact: true }).fill('二人被困在废弃驿站。')
  await card.getByLabel('故事块目标', { exact: true }).fill('穿过封锁线。')
  await card.getByLabel('主要压力', { exact: true }).fill('追兵压缩路线。')
  await card.getByLabel('预期变化', { exact: true }).fill('二人建立信任。')
  await card.getByLabel('开放问题（每行一项）', { exact: true })
    .fill('内应是谁')
  await card.getByLabel('涉及人物（每行一项）', { exact: true })
    .fill('沈砚\n陆青禾')

  await card.getByRole('button', { name: '新增阶段' }).click()
  const stage = card.locator('.stage-card').first()
  await stage.getByLabel('阶段标题', { exact: true }).fill('寻找缺口')
  await stage.getByLabel('阶段目的', { exact: true }).fill('确认封锁薄弱处。')
  await stage.getByLabel('戏剧问题', { exact: true })
    .fill('能否在暴露前找到缺口？')
  await stage.getByRole('button', { name: '新增场景任务' }).click()
  const task = stage.locator('.scene-task').first()
  await task.getByLabel('场景任务', { exact: true }).fill('观察换岗。')
  await task.getByLabel('完成证据', { exact: true }).fill('取得换岗间隔。')
}


async function savePlanning(page) {
  const saved = waitForNamedResponse(page, 'Planning Draft save', response => (
    isResponse(response, 'PUT', PLANNING_DRAFT_PATH)
  ))
  await page.getByRole('button', { name: '保存工作稿' }).click()
  expect((await saved).status()).toBe(200)
}


async function confirmPlanning(page, { save = true } = {}) {
  if (save) await savePlanning(page)
  await expect(page.getByText(
    '聚合已完整。请先保存所有本地编辑，再确认不可变修订。',
  )).toBeVisible()
  await page.getByRole('button', { name: '预览并确认' }).click()
  const dialog = page.getByRole('dialog', { name: '确认故事规划' })
  const confirmed = waitForNamedResponse(page, 'Planning confirmation', response => (
    isResponse(response, 'POST', PLANNING_CONFIRM_PATH)
  ))
  await dialog.getByRole('button', { name: '确认并签印' }).click()
  expect((await confirmed).status()).toBe(201)
}


async function createCompletePlanning(page, runtime) {
  await settleNavigationBoundary(page, runtime)
  await page.goto(VOLUMES_PATH)
  await page.getByRole('button', { name: '建立空白规划工作稿' }).click()
  await expect(page.getByText('规划模型尚未就绪；手工规划仍可继续。'))
    .toBeVisible()
  await page.getByRole('button', { name: '新增分卷' }).click()
  await fillVolume(page)

  await settleNavigationBoundary(page, runtime)
  await page.getByRole('link', { name: '情节线', exact: true }).click()
  await page.getByRole('button', { name: '新增情节线' }).click()
  await fillPlot(page)

  await settleNavigationBoundary(page, runtime)
  await page.getByRole('link', { name: '故事块', exact: true }).click()
  await page.getByRole('button', { name: '新增故事块' }).click()
  await fillStoryBlock(page)
  const activate = page.getByRole('button', { name: '设为当前活动块' })
  if (await activate.count()) await activate.click()
  await savePlanning(page)

  await settleNavigationBoundary(page, runtime)
  await page.getByRole('link', { name: '分卷', exact: true }).click()
  await settleNavigationBoundary(page, runtime)
  await page.getByRole('link', { name: '情节线', exact: true }).click()
  await settleNavigationBoundary(page, runtime)
  await page.getByRole('link', { name: '故事块', exact: true }).click()
  await settleNavigationBoundary(page, runtime)
  await page.reload()
  await expect(page).toHaveURL(new RegExp(`${STORY_BLOCKS_PATH}$`, 'u'))
  await expect(page.getByLabel('故事块标题', { exact: true }))
    .toHaveValue('夜渡封锁线')
  await settleNavigationBoundary(page, runtime)
  await page.goBack()
  await expect(page).toHaveURL(new RegExp(`${PLOTS_PATH}$`, 'u'))
  await settleNavigationBoundary(page, runtime)
  await page.goBack()
  await expect(page).toHaveURL(new RegExp(`${VOLUMES_PATH}$`, 'u'))
  await settleNavigationBoundary(page, runtime)
  await page.goForward()
  await settleNavigationBoundary(page, runtime)
  await page.goForward()
  await expect(page).toHaveURL(new RegExp(`${STORY_BLOCKS_PATH}$`, 'u'))

  await confirmPlanning(page, { save: false })
}


async function fillOutline(page, goal = '找到封锁线缺口。') {
  const sheet = page.locator('.outline-sheet')
  const references = sheet.locator('.reference-grid select')
  await references.nth(0).selectOption({ index: 1 })
  await references.nth(1).selectOption({ index: 1 })
  const stages = sheet.getByRole('group', { name: '关联阶段' })
    .getByRole('checkbox')
  await expect(stages).toHaveCount(1)
  await stages.first().check()
  const sceneTasks = sheet.getByRole('group', { name: '关联场景任务' })
    .getByRole('checkbox')
  await expect(sceneTasks).toHaveCount(1)
  await sceneTasks.first().check()
  await sheet.getByLabel('本章目标', { exact: true }).fill(goal)
  await sheet.getByLabel('预计出场人物（每行一项）', { exact: true })
    .fill('沈砚\n陆青禾')
  await sheet.getByLabel('承接的未完成情节（每行一项）', { exact: true })
    .fill('承接被困局面')
  await sheet.getByLabel('计划推进的任务（每行一项）', { exact: true })
    .fill('观察换岗')
  await sheet.getByLabel('主要场景（每行一项）', { exact: true })
    .fill('废弃驿站侦察')
  await sheet.getByLabel('不应提前发生的内容（每行一项）', { exact: true })
    .fill('不可提前揭示内应')
}


async function saveAndConfirmOutline(page) {
  const saved = waitForNamedResponse(page, 'Outline Draft save', response => (
    isResponse(response, 'PUT', OUTLINE_DRAFT_PATH)
  ))
  await page.getByRole('button', { name: '保存小纲工作稿' }).click()
  expect((await saved).status()).toBe(200)
  await page.getByRole('button', { name: '预览并确认小纲' }).click()
  const dialog = page.getByRole('dialog', { name: '确认章节小纲' })
  const confirmed = waitForNamedResponse(page, 'Outline confirmation', response => (
    isResponse(response, 'POST', OUTLINE_CONFIRM_PATH)
  ))
  await dialog.getByRole('button', { name: '确认并签印' }).click()
  expect((await confirmed).status()).toBe(201)
}


async function createManualOutline(page, goal = '找到封锁线缺口。') {
  const authorityResponses: any[] = []
  const observeAuthority = response => {
    if (isResponse(response, 'GET', OUTLINE_CURRENT_PATH)) {
      authorityResponses.push(response)
    }
  }
  page.on('response', observeAuthority)
  const created = waitForNamedResponse(page, 'Outline Draft creation', response => (
    isResponse(response, 'POST', OUTLINE_DRAFTS_PATH)
  ))
  try {
    await page.getByRole('button', { name: '建立新工作稿' }).click()
    expect((await created).status()).toBe(201)
    await expect(page.getByText('已建立空白章节小纲工作稿')).toBeVisible()
    await expect.poll(() => authorityResponses.length).toBeGreaterThan(0)
  } finally {
    page.off('response', observeAuthority)
  }
  const authority = await authorityResponses.at(-1).json()
  const content = authority.planningAuthority?.content
  const activeBlock = content?.storyBlocks?.find(block => (
    block.id === content.activeStoryBlockId
  ))
  const activeVolume = content?.volumes?.find(
    volume => volume.id === activeBlock?.volumeId,
  )
  expect({
    activeStoryBlockId: content?.activeStoryBlockId,
    activeBlockFound: Boolean(activeBlock),
    activeBlockLifecycle: activeBlock?.lifecycle,
    activeVolumeFound: Boolean(activeVolume),
    activeVolumeLifecycle: activeVolume?.lifecycle,
    volumeCount: content?.volumes?.length,
    storyBlockCount: content?.storyBlocks?.length,
    editDraft: authority.capabilities?.editDraft,
  }).toEqual({
    activeStoryBlockId: expect.any(String),
    activeBlockFound: true,
    activeBlockLifecycle: 'active',
    activeVolumeFound: true,
    activeVolumeLifecycle: 'active',
    volumeCount: 1,
    storyBlockCount: 1,
    editDraft: true,
  })
  await expect(page.locator('.outline-sheet .reference-grid select').first()
    .locator('option')).toHaveCount(2)
  await fillOutline(page, goal)
  await saveAndConfirmOutline(page)
}


test('@manual manual StoryBlock Stage SceneTask Planning and Outline create one authoritative Session', async ({
  page,
}) => {
  const runtime = observeRuntime(page, { allowedOrigins: ALLOWED_RUNTIME_ORIGINS })
  let bodyError: unknown = null
  try {
    await createCompletePlanning(page, runtime)

    await createManualOutline(page)
    await settleNavigationBoundary(page, runtime)
    const preparation = waitForNamedResponse(page, 'project preparation', response => (
      isResponse(response, 'GET', `/api/projects/${PROJECT_ID}/preparation`)
    ))
    await page.goto(OVERVIEW_PATH)
    const preparationPayload = await (await preparation).json()
    expect(preparationPayload.authoritativeChapterNumber).toBe(1)
    expect(preparationPayload.targetPath).toBe(WRITER_PATH)
    const nextAction = page.locator('a.overview-next-action')
    await expect(nextAction).toHaveAttribute('href', WRITER_PATH)
    await settleNavigationBoundary(page, runtime)
    const sessionCreated = waitForNamedResponse(page, 'ChapterSession creation', response => (
      isResponse(response, 'POST', SESSION_PATH)
    ))
    await nextAction.click()
    expect((await sessionCreated).status()).toBe(201)
    await expect(page).toHaveURL(new RegExp(`${WRITER_PATH}$`, 'u'))
    await expect(page.getByText('第 1 章 · revision 1')).toBeVisible()
    await expect(page.getByText('Planning R1')).toBeVisible()
    await expect(page.getByText('Outline R1 · StoryBlock R1')).toBeVisible()
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
        { method: 'PUT', path: PLANNING_DRAFT_PATH, count: 1, statuses: [200] },
        { method: 'POST', path: PLANNING_CONFIRM_PATH, count: 1, statuses: [201] },
        { method: 'POST', path: OUTLINE_DRAFTS_PATH, count: 1, statuses: [201] },
        { method: 'PUT', path: OUTLINE_DRAFT_PATH, count: 1, statuses: [200] },
        { method: 'POST', path: OUTLINE_CONFIRM_PATH, count: 1, statuses: [201] },
        { method: 'POST', path: SESSION_PATH, count: 1, statuses: [201] },
      ],
    })
  }
})


test('@gateway fake Outline exact Draft and unknown result reconcile only by GET', async ({
  page,
}) => {
  const runtime = observeRuntime(page, { allowedOrigins: ALLOWED_RUNTIME_ORIGINS })
  let bodyError: unknown = null
  let generationResponsePath = ''
  let outlineGenerationPostCount = 0
  page.on('request', request => {
    if (
      request.method() === 'POST'
      && OUTLINE_GENERATION_PATH.test(pathname(request.url()))
    ) outlineGenerationPostCount += 1
  })
  try {
    await settleNavigationBoundary(page, runtime)
    await page.goto(STORY_BLOCKS_PATH)
    const created = waitForNamedResponse(page, 'Outline Draft creation', response => (
      isResponse(response, 'POST', OUTLINE_DRAFTS_PATH)
    ))
    await page.getByRole('button', { name: '建立新工作稿' }).click()
    expect((await created).status()).toBe(201)
    await fillOutline(page, '作者保存的小纲目标。')
    const saved = waitForNamedResponse(page, 'Outline Draft save', response => (
      isResponse(response, 'PUT', OUTLINE_DRAFT_PATH)
    ))
    await page.getByRole('button', { name: '保存小纲工作稿' }).click()
    expect((await saved).status()).toBe(200)

    const generateButton = page.getByRole('button', {
      name: 'AI 生成当前小纲工作稿',
    })
    try {
      await expect(generateButton).toBeEnabled()
    } catch (error) {
      const reasonCategories = [
        ['上次小纲生成结果尚未核对，请先恢复权威状态。', 'recovery'],
        ['请先保存本地修改，再使用 AI 生成。', 'dirty'],
        ['当前章节小纲不可编辑。', 'read-only'],
        ['小纲模型尚未就绪；手工编辑仍可继续。', 'model-not-ready'],
        ['请等待当前小纲操作完成。', 'busy'],
      ]
      let category = 'none'
      for (const [message, name] of reasonCategories) {
        if (await page.getByText(message, { exact: true }).isVisible()) {
          category = name
          break
        }
      }
      throw new Error(`Outline generation disabled; category: ${category}`, {
        cause: error,
      })
    }
    const unknown = waitForNamedResponse(page, 'Outline generation transport', response => (
      isResponse(response, 'POST', OUTLINE_GENERATION_PATH)
    )).catch(async error => {
      const alert = page.getByRole('alert')
      const publicMessage = await alert.isVisible()
        ? String(await alert.locator('strong').textContent() || '')
        : ''
      const publicErrorCategory = new Map([
        ['章节小纲生成模型未就绪', 'model-not-ready'],
        ['请先保存本地小纲修改，再生成', 'unsaved-draft'],
        ['已有小纲操作正在进行', 'operation-busy'],
        ['Invalid ChapterOutline idempotency key', 'invalid-idempotency-key'],
        ['Invalid Chapter Outline draft id', 'invalid-draft-id'],
        ['请求失败', 'request-failed'],
      ]).get(publicMessage) || (publicMessage ? 'other' : 'none')
      const overlayVisible = await page.locator('.outline-local-overlay').isVisible()
      const generateEnabled = await page
        .getByRole('button', { name: 'AI 生成当前小纲工作稿' })
        .isEnabled()
      throw new Error(
        `${error.message}; generation request count: ${String(outlineGenerationPostCount)}; public error category: ${publicErrorCategory}; overlay visible: ${String(overlayVisible)}; generate enabled: ${String(generateEnabled)}`,
        { cause: error },
      )
    })
    const [unknownResponse] = await Promise.all([
      unknown,
      (async () => {
        await generateButton.click()
        await expect(page.locator('.outline-local-overlay'))
          .toContainText('小纲生成只读模式')
      })(),
    ])
    generationResponsePath = pathname(unknownResponse.url())
    expect(unknownResponse.status()).toBe(503)
    expect(outlineGenerationPostCount).toBe(1)
    await expect(page.getByText('小纲生成结果尚未完成权威核对，本地文字保持不变。'))
      .toBeVisible()

    const byKey = waitForNamedResponse(page, 'operation reconciliation by key', response => (
      response.request().method() === 'GET'
      && pathname(response.url()).includes('/chapter-outlines/operations/by-key/')
    ))
    await page.getByRole('button', { name: '核对原操作' }).click()
    const pending = await byKey
    expect((await pending.json()).status).toBe('pending')

    const byId = waitForNamedResponse(page, 'operation reconciliation by id', response => (
      response.request().method() === 'GET'
      && pathname(response.url()).includes('/chapter-outlines/operations/')
      && !pathname(response.url()).includes('/by-key/')
    ))
    const authority = waitForNamedResponse(page, 'Outline authority refresh', response => (
      isResponse(response, 'GET', OUTLINE_CURRENT_PATH)
    ))
    await page.getByRole('button', { name: '核对原操作' }).click()
    const terminal = await byId
    expect((await terminal.json()).status).toBe('succeeded')
    expect((await authority).status()).toBe(200)
    expect(outlineGenerationPostCount).toBe(1)
    await expect(page.getByLabel('本章目标', { exact: true }))
      .toHaveValue('AI 精确小纲：趁换岗空隙穿过封锁线。')
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
        { method: 'POST', path: OUTLINE_DRAFTS_PATH, count: 1, statuses: [201] },
        { method: 'PUT', path: OUTLINE_DRAFT_PATH, count: 1, statuses: [200] },
        { method: 'POST', path: OUTLINE_GENERATION_PATH, count: 1, statuses: [503] },
      ],
    })
  }
})


async function openPlanningVolumes(page, runtime) {
  await settleNavigationBoundary(page, runtime)
  if (page.url() === 'about:blank') {
    await page.goto(VOLUMES_PATH)
  } else {
    await page.getByRole('link', { name: '故事规划', exact: true }).click()
  }
  await expect(page).toHaveURL(new RegExp(`${VOLUMES_PATH}$`, 'u'))
  const createDraft = page.getByRole('button', { name: '建立空白规划工作稿' })
  await expect(createDraft).toBeVisible()
  await expect(createDraft).toBeEnabled()
  return createDraft
}


async function revisePlanning(page, title: string, runtime) {
  const createDraft = await openPlanningVolumes(page, runtime)
  await createDraft.click()
  await page.getByLabel('卷名', { exact: true }).first().fill(title)
  await confirmPlanning(page)
}


test('@supersession Planning R2 supersedes an unpinned Outline while Session keeps exact old pins', async ({
  page,
}) => {
  const runtime = observeRuntime(page, { allowedOrigins: ALLOWED_RUNTIME_ORIGINS })
  let bodyError: unknown = null
  try {
    await revisePlanning(page, '北境立足卷 · R2', runtime)
    await settleNavigationBoundary(page, runtime)
    const currentResponse = waitForNamedResponse(page, 'superseded Outline authority', response => (
      isResponse(response, 'GET', OUTLINE_CURRENT_PATH)
    ))
    await page.goto(STORY_BLOCKS_PATH)
    const state = await (await currentResponse).json()
    expect(state.planningAuthority.revision).toBe(2)
    expect(state.confirmedOutline.status).toBe('superseded')
    await page.getByRole('button', { name: '小纲历史' }).click()
    const history = page.getByRole('dialog', { name: '章节小纲历史' })
    await expect(history).toContainText('已被后续依据取代')
    await history.getByRole('button', { name: '关闭' }).click()

    await createManualOutline(page, 'R2 小纲：穿过封锁线。')
    await settleNavigationBoundary(page, runtime)
    const sessionCreated = waitForNamedResponse(page, 'supersession ChapterSession creation', response => (
      isResponse(response, 'POST', SESSION_PATH)
    ))
    await page.goto(WRITER_PATH)
    expect((await sessionCreated).status()).toBe(201)
    await expect(page.getByText('Planning R2')).toBeVisible()
    await expect(page.getByText('Outline R2 · StoryBlock R1')).toBeVisible()

    await revisePlanning(page, '北境立足卷 · R3', runtime)
    let replayPostCount = 0
    page.on('request', request => {
      if (request.method() === 'POST' && pathname(request.url()) === SESSION_PATH) {
        replayPostCount += 1
      }
    })
    await settleNavigationBoundary(page, runtime)
    const preparation = waitForNamedResponse(page, 'supersession project preparation', response => (
      isResponse(response, 'GET', `/api/projects/${PROJECT_ID}/preparation`)
    ))
    await page.getByRole('link', { name: '项目概览', exact: true }).click()
    expect((await preparation).status()).toBe(200)
    await expect(page).toHaveURL(new RegExp(`${OVERVIEW_PATH}$`, 'u'))
    const nextAction = page.locator('a.overview-next-action')
    await expect(nextAction).toHaveAttribute('href', WRITER_PATH)
    await settleNavigationBoundary(page, runtime)
    const replay = waitForNamedResponse(page, 'pinned ChapterSession replay', response => (
      isResponse(response, 'GET', SESSION_PATH)
    ))
    await nextAction.click()
    expect((await replay).status()).toBe(200)
    expect(replayPostCount).toBe(0)
    await expect(page.getByText('Planning R2')).toBeVisible()
    await expect(page.getByText('Outline R2 · StoryBlock R1')).toBeVisible()
  } catch (error) {
    bodyError = error
  } finally {
    await finishRuntime(runtime, bodyError, {
      writes: [
        {
          method: 'POST',
          path: `/api/projects/${PROJECT_ID}/planning/drafts`,
          count: 2,
          statuses: [201],
        },
        { method: 'PUT', path: PLANNING_DRAFT_PATH, count: 2, statuses: [200] },
        { method: 'POST', path: PLANNING_CONFIRM_PATH, count: 2, statuses: [201] },
        { method: 'POST', path: OUTLINE_DRAFTS_PATH, count: 1, statuses: [201] },
        { method: 'PUT', path: OUTLINE_DRAFT_PATH, count: 1, statuses: [200] },
        { method: 'POST', path: OUTLINE_CONFIRM_PATH, count: 1, statuses: [201] },
        { method: 'POST', path: SESSION_PATH, count: 1, statuses: [201] },
      ],
    })
  }
})


test('@archived archived Outline and Writer remain read-only with zero Session writes', async ({
  page,
}) => {
  const runtime = observeRuntime(page, { allowedOrigins: ALLOWED_RUNTIME_ORIGINS })
  let bodyError: unknown = null
  try {
    await settleNavigationBoundary(page, runtime)
    await page.goto(STORY_BLOCKS_PATH)
    await expect(page.getByText('当前小纲为只读权威记录；本地字段与正式引用均不会被改写。'))
      .toBeVisible()
    await expect(page.getByRole('button', { name: '建立新工作稿' })).toHaveCount(0)
    await expect(page.getByRole('button', { name: '保存小纲工作稿' })).toHaveCount(0)
    await settleNavigationBoundary(page, runtime)
    await page.goto(WRITER_PATH)
    await expect(page.getByText('项目已归档')).toBeVisible()
  } catch (error) {
    bodyError = error
  } finally {
    await finishRuntime(runtime, bodyError, { writes: [] })
  }
})


test('@missing-upstream missing Planning authority fails closed before Outline writes', async ({
  page,
}) => {
  const runtime = observeRuntime(page, { allowedOrigins: ALLOWED_RUNTIME_ORIGINS })
  let bodyError: unknown = null
  try {
    await settleNavigationBoundary(page, runtime)
    const loaded = page.waitForResponse(response => (
      isResponse(response, 'GET', OUTLINE_CURRENT_PATH)
    ))
    await page.goto(STORY_BLOCKS_PATH)
    const state = await (await loaded).json()
    expect(state.reasons).toContain('planningOrProjectionUnavailable')
    await expect(page.getByText('去补齐故事规划')).toBeVisible()
    await expect(page.getByRole('button', { name: '建立新工作稿' })).toHaveCount(0)
  } catch (error) {
    bodyError = error
  } finally {
    await finishRuntime(runtime, bodyError, { writes: [] })
  }
})


test('@canon-mismatch Canon Projection mismatch disables Outline confirmation and Session', async ({
  page,
}) => {
  const runtime = observeRuntime(page, { allowedOrigins: ALLOWED_RUNTIME_ORIGINS })
  let bodyError: unknown = null
  try {
    await settleNavigationBoundary(page, runtime)
    const loaded = page.waitForResponse(response => (
      isResponse(response, 'GET', OUTLINE_CURRENT_PATH)
    ))
    await page.goto(STORY_BLOCKS_PATH)
    const state = await (await loaded).json()
    expect(state.reasons).toContain('canonProjectionMismatch')
    expect(state.capabilities.createDraft).toBe(true)
    expect(state.capabilities.confirm).toBe(false)
    await expect(page.getByLabel('Canon R0')).toBeVisible()
    await expect(page.getByLabel('Projection R1')).toBeVisible()
    const createDraft = page.getByRole('button', { name: '建立新工作稿' })
    await expect(createDraft).toBeVisible()
    await expect(createDraft).toBeEnabled()
    await settleNavigationBoundary(page, runtime)
    await page.goto(WRITER_PATH)
    await expect(
      page.getByRole('alert').getByText('请先完成并确认本章小纲'),
    ).toBeVisible()
    await expect(
      page.getByRole('button', { name: '请先完成并确认本章小纲' }),
    ).toBeDisabled()
  } catch (error) {
    bodyError = error
  } finally {
    await finishRuntime(runtime, bodyError, { writes: [] })
  }
})


test('@wrong-chapter direct wrong chapter URL fails closed without redirect or Session POST', async ({
  page,
}) => {
  const runtime = observeRuntime(page, { allowedOrigins: ALLOWED_RUNTIME_ORIGINS })
  let bodyError: unknown = null
  try {
    await settleNavigationBoundary(page, runtime)
    await page.goto(WRONG_WRITER_PATH)
    await expect(page).toHaveURL(new RegExp(`${WRONG_WRITER_PATH}$`, 'u'))
    await expect(page.getByText('章节地址与服务端权威不一致')).toBeVisible()
    await expect(page.getByText('当前地址不是服务端确认的权威章节；系统不会自动跳转，也不会读取或创建错误章节的会话。'))
      .toBeVisible()
    await expect(page.getByRole('link', { name: '前往第 1 章' }))
      .toHaveAttribute('href', WRITER_PATH)
  } catch (error) {
    bodyError = error
  } finally {
    await finishRuntime(runtime, bodyError, { writes: [] })
  }
})


// Closed acceptance evidence: real provider calls = 0; product DB reads/writes = 0/0;
// live website access = 0.
