import { expect, test } from '@playwright/test'

import {
  assertRuntimeEvidenceHealthy,
  observeRuntime,
  runtimeSensitiveValues,
  scanRuntimeEvidence,
} from './runtime-observer.mjs'
import { expectedMissingDraftFailureCount } from './phase2c-runtime-policy.mjs'
import { SYNTHETIC_STORY_ENGINE_OPTIONS } from './synthetic-story-engine-options.mjs'


function requiredEnvironment(name: string) {
  const value = process.env[name]
  if (!value) throw new Error(name + ' is required from the Phase 2C runner')
  return value
}


const PROJECT_ID = requiredEnvironment('BROWSER_PROJECT_ID')
const PROJECT_PATH = '/projects/' + PROJECT_ID + '/contract'
const SEEDS_PATH = '/projects/' + PROJECT_ID + '/seeds'
const CORPUS_FILE = requiredEnvironment('BROWSER_CORPUS_FILE')
const MISSING_DRAFT_FAILURE_COUNT = expectedMissingDraftFailureCount(
  requiredEnvironment('BROWSER_SCENARIO_MODE'),
)
const DIAGNOSTIC_REDACTIONS = Object.freeze([
  ...runtimeSensitiveValues(process.env),
  process.env.BROWSER_TEST_DATABASE,
].filter(value => typeof value === 'string' && value.length > 0))
const SEED_FIELDS = Object.freeze([
  ['种子标题', '雾港错钟'],
  ['题材类型', '历史穿越'],
  ['一句话故事', '守钟学徒发现潮汐钟会提前刻下尚未发生的海难。'],
  ['主角底色', '谨慎克制，但无法坐视同伴被当作代价。'],
  ['核心欲望', '找回失踪导师并证明错误钟鸣来自人为篡改。'],
  ['核心冲突', '每次用测量证据破局，都会让港务议会更快封存钟室。'],
  ['世界压力', '风暴季、商会船期与失踪者家属共同挤压选择空间。'],
  ['开篇抓手', '第三声钟鸣提前落下，整座港口却在无风夜里退潮。'],
  ['差异化支点', '钟表误差是制造伦理选择的证据，不是万能解谜外挂。'],
])
const SECOND_SEED_FIELDS = Object.freeze([
  ['种子标题', '盐税暗潮'],
  ['题材类型', '历史穿越'],
  ['一句话故事', '账房学徒发现每次减免盐税都会把灾民名册交给走私同盟。'],
  ['主角底色', '精于账目，却对公开承担责任心存畏惧。'],
  ['核心欲望', '找回被删去的赈灾账本并保护证人。'],
  ['核心冲突', '每公开一笔假账，都会让一处合法救济仓失去保护。'],
  ['世界压力', '盐荒、漕运封锁与地方豪强共同压缩调查时间。'],
  ['开篇抓手', '一袋官盐里缝着一页写有未来死者姓名的账纸。'],
  ['差异化支点', '会计证据只改变责任分配，不能直接消除政治代价。'],
])


function seedCard(page, name: string) {
  return page.locator('.seed-record').filter({
    has: page.getByRole('heading', { name, exact: true }),
  })
}


async function chooseVisibleSelectOption(page, select, label: string) {
  const trigger = select.locator('.n-base-selection')
  await trigger.click()
  await expect(trigger).toHaveClass(/n-base-selection--active/u)
  const filterInput = trigger.locator('input:not([readonly]):not([disabled])')
  if (
    await filterInput.count() === 1
    && await filterInput.isEditable()
  ) {
    await filterInput.fill(label)
  }

  const labelPattern = new RegExp(
    label.replace(/[.*+?^${}()|[\]\\]/gu, '\\$&'),
    'u',
  )
  const candidateOptions = page.locator('.n-base-select-option:visible').filter({
    hasText: labelPattern,
  })
  await expect(candidateOptions).not.toHaveCount(0)
  let activeLayer = null
  let highestZIndex = -Infinity
  const seenZIndexes = new Set<number>()
  for (const candidateOption of await candidateOptions.all()) {
    const layer = candidateOption.locator(
      'xpath=ancestor::div[contains(concat(" ", normalize-space(@class), " "), " v-binder-follower-container ")][1]',
    )
    await expect(layer).toHaveCount(1)
    const style = await layer.getAttribute('style')
    const match = style?.match(/(?:^|;)\s*z-index:\s*(\d+)/u)
    if (!match) continue
    const zIndex = Number(match[1])
    if (seenZIndexes.has(zIndex)) continue
    seenZIndexes.add(zIndex)
    if (zIndex > highestZIndex) {
      activeLayer = layer
      highestZIndex = zIndex
    }
  }
  expect(activeLayer).not.toBeNull()
  const option = activeLayer.locator('.n-base-select-option:visible').filter({
    hasText: labelPattern,
  })
  await expect(option).toHaveCount(1)
  await option.click()
}


function safeDiagnosticText(value: unknown) {
  let rendered = String(value || '').replace(/\s+/gu, ' ').trim().slice(0, 240)
  for (const sensitive of DIAGNOSTIC_REDACTIONS) {
    rendered = rendered.replaceAll(sensitive, '[redacted]')
  }
  return rendered.replace(/novel_creator_test_[0-9a-f]{32}/gu, '[database]') || 'none'
}


async function safeResponseSummary(label: string, response) {
  let body: Record<string, unknown> = {}
  if (!response.ok()) {
    try {
      const parsed = await response.json()
      if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) body = parsed
    } catch {
      body = {}
    }
  }
  const detail = body.detail && typeof body.detail === 'object' && !Array.isArray(body.detail)
    ? body.detail as Record<string, unknown>
    : {}
  const detailMessage = typeof body.detail === 'string' ? body.detail : detail.message
  return `${label}:status=${response.status()},code=${safeDiagnosticText(body.code || detail.code)},message=${safeDiagnosticText(body.message || detailMessage)}`
}


async function createSeedCandidate(page, fields) {
  await page.goto(SEEDS_PATH)
  await page.getByRole('button', { name: /已存种子/u }).click()
  await page.getByRole('button', { name: '新建种子', exact: true }).click()
  const editor = page.getByRole('region', { name: '种子九字段编辑器' })
  await expect(editor).toBeVisible()
  for (const [label, value] of fields) {
    const field = editor.locator('label').filter({ hasText: label })
    await expect(field).toHaveCount(1)
    await field.locator('input, textarea').fill(value)
  }
  const created = page.waitForResponse(response => (
    response.request().method() === 'POST'
    && new URL(response.url()).pathname === '/api/projects/' + PROJECT_ID + '/seeds'
  ))
  await editor.getByRole('button', { name: '保存种子', exact: true }).click()
  expect((await created).status()).toBe(200)
  const card = seedCard(page, fields[0][1])
  await expect(card).toBeVisible()
  return card
}


async function selectSeed(page, name: string, expectedSelectionRevision: number) {
  const card = seedCard(page, name)
  await expect(card).toBeVisible()
  const selected = page.waitForResponse(response => (
    response.request().method() === 'PUT'
    && new URL(response.url()).pathname
      === '/api/projects/' + PROJECT_ID + '/selected-seed'
  ))
  await card.getByRole('button', { name: '立即选定', exact: true }).click()
  expect((await selected).status()).toBe(200)
  await expect(page.getByText(
    `选定代次 ${expectedSelectionRevision}`,
    { exact: true },
  )).toBeVisible()
}


async function createAndSelectSeed(page) {
  await createSeedCandidate(page, SEED_FIELDS)
  await selectSeed(page, '雾港错钟', 1)
  await expect(page.getByText('继续创作契约', { exact: true })).toBeVisible()
  await page.getByRole('link', { name: '创作契约', exact: true }).click()
  await expect(page).toHaveURL(new RegExp('/projects/' + PROJECT_ID + '/contract$','u'))
}


async function importCorpusThroughSettings(page) {
  await page.goto('/assets/corpus')
  await expect(page.getByRole('heading', { name: '语料档案室' })).toBeVisible()
  const discovery = page.waitForResponse(response => (
    response.request().method() === 'GET'
    && new URL(response.url()).pathname === '/api/corpus/discovery'
  ))
  await page.getByRole('button', { name: '导入语料', exact: true }).click()
  const discoveryResponse = await discovery
  expect(discoveryResponse.status()).toBe(200)
  const discoveryPayload = await discoveryResponse.json()
  expect(discoveryPayload.items).toContainEqual(expect.objectContaining({
    relativePath: 'phase2c-synthetic-corpus.txt',
    preflightStatus: 'eligible',
  }))
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByText('导入为新的受管语料', { exact: true })).toBeVisible()
  await chooseVisibleSelectOption(page, dialog, 'phase2c-synthetic-corpus.txt')
  await dialog.getByPlaceholder('例如：北境卷叙事样本').fill('Phase 2C 雾港参考片段')
  await dialog.getByRole('button', { name: '确认导入', exact: true }).click()
  await expect(page.getByRole('heading', {
    name: 'Phase 2C 雾港参考片段',
    exact: true,
  })).toBeVisible()
}


async function fillManualEngines(page) {
  await page.locator('label').filter({ hasText: '渠道定位标识' })
    .locator('input').fill('phase2c-manual-channel')
  await page.locator('label').filter({ hasText: '题材定位标识' })
    .locator('input').fill('历史穿越')
  await page.getByRole('button', { name: '普通字段手动录入' }).click()
  const sheet = page.locator('.manual-sheet')
  const labels = [
    ['方案名称', option => option.name],
    ['故事承诺', option => option.storyPromise],
    ['主角欲望', option => option.protagonistDesire],
    ['持续压力', option => option.sustainedPressure],
    ['成长方向', option => option.growthDirection],
    ['冲突循环', option => option.conflictLoop],
    ['群像角色', option => option.ensembleRoles.map(
      role => role.role + '：' + role.purpose,
    ).join('\n')],
    ['优势与代价', option => option.advantageAndCost],
    ['满足感来源', option => option.satisfactionSources.join('\n')],
    ['长线变化', option => option.longFormVariation.join('\n')],
    ['结局锚点', option => option.endingAnchor],
    ['风险', option => option.risks.join('\n')],
    ['差异化', option => option.differentiation],
  ]
  const articles = sheet.locator('article')
  await expect(articles).toHaveCount(3)
  for (let index = 0; index < SYNTHETIC_STORY_ENGINE_OPTIONS.length; index += 1) {
    const article = articles.nth(index)
    const option = SYNTHETIC_STORY_ENGINE_OPTIONS[index]
    for (const [label, value] of labels) {
      await article.locator('label').filter({ hasText: label })
        .locator('input, textarea').fill(value(option))
    }
  }
  await sheet.getByRole('button', { name: '建立手动三案' }).click()
  await expect(page.getByRole('radio')).toHaveCount(3)
  await page.getByRole('radio', { name: /潮钟追凶/u }).click()
  const draftSaved = page.waitForResponse(response => (
    response.request().method() === 'PUT'
    && new URL(response.url()).pathname
      === '/api/projects/' + PROJECT_ID + '/contract-draft'
  ))
  const styleTemplatesLoaded = page.waitForResponse(response => (
    response.request().method() === 'GET'
    && new URL(response.url()).pathname === '/api/assets/style-templates'
  ))
  const recommendationsLoaded = page.waitForResponse(response => (
    response.request().method() === 'POST'
    && new URL(response.url()).pathname
      === '/api/projects/' + PROJECT_ID + '/asset-recommendations'
  ))
  await page.getByRole('button', { name: '保存草稿并继续' }).click()
  const [draftResponse, styleResponse, recommendationResponse] = await Promise.all([
    draftSaved,
    styleTemplatesLoaded,
    recommendationsLoaded,
  ])
  expect(draftResponse.status()).toBe(200)
  expect(Object.keys(recommendationResponse.request().postDataJSON()).sort()).toEqual([
    'creationStage',
    'engineOptionId',
    'genre',
    'idempotencyKey',
    'prohibitedDirections',
    'status',
    'taxonomyHash',
    'taxonomyVersion',
  ])
  if (!styleResponse.ok() || !recommendationResponse.ok()) {
    throw new Error(`Step 2 request diagnostic: ${[
      await safeResponseSummary('style-templates', styleResponse),
      await safeResponseSummary('asset-recommendations', recommendationResponse),
    ].join('; ')}`)
  }
}


async function generateGatewayEngines(page) {
  await page.locator('label').filter({ hasText: '渠道定位标识' })
    .locator('input').fill('phase2c-gateway-channel')
  await page.locator('label').filter({ hasText: '题材定位标识' })
    .locator('input').fill('历史穿越')
  const generated = page.waitForResponse(response => (
    response.request().method() === 'POST'
    && new URL(response.url()).pathname
      === '/api/projects/' + PROJECT_ID + '/story-engine-batches'
  ))
  await page.getByRole('button', { name: '生成三套方案', exact: true }).click()
  expect((await generated).status()).toBe(201)
  const options = page.getByRole('radio')
  await expect(options).toHaveCount(3)
  for (const name of [
    'Tide Clock Pursuit',
    'Ledger of Borrowed Storms',
    'The Third Bell Witnesses',
  ]) {
    await expect(page.getByRole('heading', { name, exact: true })).toHaveCount(1)
  }
  await page.getByRole('radio', { name: /Tide Clock Pursuit/u }).click()

  const draftSaved = page.waitForResponse(response => (
    response.request().method() === 'PUT'
    && new URL(response.url()).pathname
      === '/api/projects/' + PROJECT_ID + '/contract-draft'
  ))
  const recommendationsLoaded = page.waitForResponse(response => (
    response.request().method() === 'POST'
    && new URL(response.url()).pathname
      === '/api/projects/' + PROJECT_ID + '/asset-recommendations'
  ))
  await page.getByRole('button', { name: '保存草稿并继续', exact: true }).click()
  expect((await draftSaved).status()).toBe(200)
  expect((await recommendationsLoaded).status()).toBe(200)
}


async function selectGatewayStyleAndRunTrial(page) {
  await expect(page.getByRole('heading', { name: '先定阅读感受，再谈写法' }))
    .toBeVisible()
  const selectionPanel = page.locator('section.selection-panel')
  const primarySelect = selectionPanel.locator('label').filter({ hasText: '主风格' })
  await chooseVisibleSelectOption(page, primarySelect, '克制悬疑型 · r1')
  await expect(selectionPanel.getByText('主风格：克制悬疑型', { exact: true })).toBeVisible()

  const trial = page.locator('.trial-panel')
  await trial.locator('label').filter({ hasText: '作者场景' }).locator('textarea')
    .fill('主角必须在公开唯一证据与先救被困船队之间作出选择。')
  const trialResponse = page.waitForResponse(response => (
    response.request().method() === 'POST'
    && new URL(response.url()).pathname
      === '/api/projects/' + PROJECT_ID + '/style-trials'
  ))
  await trial.getByRole('button', { name: '运行临时试写', exact: true }).click()
  expect((await trialResponse).status()).toBe(200)
  await expect(trial.getByText('已完成', { exact: true })).toBeVisible()
  await expect(trial.getByText(/第三声钟鸣压过雾里的潮声/u)).toBeVisible()

  const saved = page.waitForResponse(response => (
    response.request().method() === 'PUT'
    && new URL(response.url()).pathname
      === '/api/projects/' + PROJECT_ID + '/contract-draft'
  ))
  await page.getByRole('button', { name: '保存草稿并继续', exact: true }).click()
  expect((await saved).status()).toBe(200)
}


async function selectStyles(page) {
  await expect(page.getByRole('heading', { name: '先定阅读感受，再谈写法' }))
    .toBeVisible()
  await expect(page.getByRole('alert').filter({ hasText: '风格模板未能加载' }))
    .toHaveCount(0)

  const selectionPanel = page.locator('section.selection-panel')
  await expect(selectionPanel).toBeVisible()
  const selectGrid = selectionPanel.locator('.select-grid')
  const primarySelect = selectGrid.locator('label').filter({ hasText: '主风格' })
  await chooseVisibleSelectOption(page, primarySelect, '克制悬疑型 · r1')
  await expect(selectionPanel.getByText('主风格：克制悬疑型', { exact: true })).toBeVisible()

  const secondarySelect = selectGrid.locator('label').filter({ hasText: '次风格' })
  await chooseVisibleSelectOption(page, secondarySelect, '沉浸群像型 · r1')
  await expect(selectionPanel.getByText('次风格：沉浸群像型', { exact: true })).toBeVisible()

  const saveResponse = page.waitForResponse(response => (
    response.request().method() === 'PUT'
    && response.url().endsWith(`/api/projects/${PROJECT_ID}/contract-draft`)
  ))
  await page.getByRole('button', { name: '保存草稿并继续' }).click()
  expect((await saveResponse).status()).toBe(200)
}


async function selectAssets(page) {
  await expect(page.getByRole('heading', { name: '逐项授权，片段级冻结' })).toBeVisible()
  await expect(page.getByText('当前没有经验卡推荐；完整经验库仍可浏览'))
    .toBeVisible()
  const experience = page.locator('label.library-selector').filter({
    hasText: '完整经验库',
  })
  await chooseVisibleSelectOption(
    page,
    experience,
    '目标旁边放私人成本 · plot_organization',
  )

  const sources = page.locator('.source-list button')
  await expect(sources).toHaveCount(1)
  await sources.click()
  const chapterSelect = page.locator('.fragment-browser header .n-select')
  await chooseVisibleSelectOption(page, chapterSelect, '01 · 第一章 雾港错钟')
  const fragment = page.locator('.fragment-browser article').filter({ hasText: '片段 1' })
  await expect(fragment).toHaveCount(1)
  await fragment.getByRole('button', { name: '选择片段' }).click()
  await expect(page.getByRole('heading', { name: '已选片段与范围' })).toBeVisible()
  const rangeRow = page.locator('.range-ledger article')
  await expect(rangeRow).toHaveCount(1)
  const startInput = rangeRow.locator('label').filter({ hasText: '起' }).locator('input')
  const endInput = rangeRow.locator('label').filter({ hasText: '止' }).locator('input')
  await startInput.fill('0')
  await endInput.fill('20')
  const referenceUseSelect = rangeRow.locator('.n-select')
  await chooseVisibleSelectOption(page, referenceUseSelect, '结构')
  await expect(startInput).toHaveValue('0')
  await expect(endInput).toHaveValue('20')
  await expect(referenceUseSelect).toContainText('结构')
  await expect(page.getByText('20 / 4000 字', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: '保存草稿并继续' }).click()
}


async function enterCapacity(page) {
  await expect(page.getByRole('heading', { name: '给长篇一副可调整的骨架' }))
    .toBeVisible()
  const values = [
    ['目标总字数', '720000'],
    ['预计卷数', '8'],
    ['预计章节数', '240'],
    ['下限', '2200'],
    ['上限', '3200'],
  ]
  for (const [label, value] of values) {
    await page.locator('label').filter({ hasText: label }).locator('input').fill(value)
  }
  await page.locator('label').filter({ hasText: '禁止方向' }).locator('textarea')
    .fill('不写无代价升级\n不把配角当作一次性工具')
  await page.locator('label').filter({ hasText: '作者备注' }).locator('textarea')
    .fill('让每次知识兑现都改变群像关系。')
  await page.getByRole('button', { name: '保存草稿并继续' }).click()
}


async function finishRuntime(runtime, bodyError: unknown) {
  let auditError: unknown = null
  try {
    const evidence = await runtime.finish()
    const evidenceAuditErrors: unknown[] = []
    try {
      assertRuntimeEvidenceHealthy(evidence, {
        responseFailureAllowlist: [{
          status: 404,
          method: 'GET',
          pathname: '/api/projects/' + PROJECT_ID + '/contract-draft',
          count: MISSING_DRAFT_FAILURE_COUNT,
        }],
        consoleErrorAllowlist: [{
          message: 'error: Failed to load resource: the server responded with a status of 404 (Not Found)',
          count: MISSING_DRAFT_FAILURE_COUNT,
          linkedResponseFailure: {
            status: 404,
            method: 'GET',
            pathname: '/api/projects/' + PROJECT_ID + '/contract-draft',
          },
        }],
      })
    } catch (error) {
      evidenceAuditErrors.push(error)
    }
    try {
      expect(scanRuntimeEvidence(evidence, runtimeSensitiveValues())).toEqual({
        matchCount: 0,
      })
    } catch (error) {
      evidenceAuditErrors.push(error)
    }
    if (evidenceAuditErrors.length === 1) throw evidenceAuditErrors[0]
    if (evidenceAuditErrors.length > 1) {
      throw new AggregateError(evidenceAuditErrors, 'runtime evidence audits failed')
    }
  } catch (error) {
    auditError = error
  }
  if (bodyError && auditError) {
    throw new AggregateError([bodyError, auditError], 'behavior and runtime audit failed')
  }
  if (bodyError) throw bodyError
  if (auditError) throw auditError
}


test('@manual manual no-model path freezes the complete author-selected contract', async ({
  page,
}) => {
  const runtime = observeRuntime(page)
  let bodyError: unknown = null
  try {
    await importCorpusThroughSettings(page)
    await createAndSelectSeed(page)
    await expect(page.getByRole('heading', { name: '本书创作契约' })).toBeVisible()
    await fillManualEngines(page)
    await selectStyles(page)
    await selectAssets(page)
    await enterCapacity(page)

    await expect(page.getByRole('heading', { name: '预览全部变化，再一次确认' }))
      .toBeVisible()
    await expect(page.getByRole('heading', { name: '冻结快照' })).toBeVisible()
    await expect(page.getByText('八项模型任务绑定', { exact: true })).toBeVisible()
    await expect(page.getByText('720,000')).toBeVisible()
    await expect(page.getByText('不写无代价升级')).toBeVisible()
    await page.getByRole('button', { name: '一次确认完整契约' }).click()

    await expect(page.getByRole('heading', { name: '当前生效的创作契约' }))
      .toBeVisible()
    await page.getByRole('button', { name: '历史修订' }).click()
    const historyDialog = page.getByRole('dialog').filter({
      has: page.getByText('创作契约历史', { exact: true }),
    })
    await expect(historyDialog).toHaveCount(1)
    const frozenIdentities = historyDialog.locator('.pinned-identities')
    await expect(frozenIdentities).toHaveCount(1)
    await expect(frozenIdentities.getByText('完整冻结身份', { exact: true }))
      .toHaveCount(1)
    await expect(frozenIdentities.getByText('种子', { exact: true })).toHaveCount(1)
    await expect(frozenIdentities.getByText('故事发动机', { exact: true })).toHaveCount(1)
    await expect(frozenIdentities.getByText('风格模板', { exact: true })).toHaveCount(2)
    await expect(frozenIdentities.getByText('经验卡', { exact: true })).toHaveCount(1)
    await expect(frozenIdentities.getByText('语料来源', { exact: true })).toHaveCount(1)
    await expect(frozenIdentities.getByText('冻结片段 · 1', { exact: true })).toHaveCount(1)
  } catch (error) {
    bodyError = error
  } finally {
    await finishRuntime(runtime, bodyError)
  }
})


test('@gateway owned gateway completes one formal path and fences A-B-A history', async ({
  page,
}) => {
  const runtime = observeRuntime(page)
  let bodyError: unknown = null
  try {
    await importCorpusThroughSettings(page)
    await createAndSelectSeed(page)
    await generateGatewayEngines(page)
    await selectGatewayStyleAndRunTrial(page)
    await selectAssets(page)
    await enterCapacity(page)

    await expect(page.getByRole('heading', { name: '预览全部变化，再一次确认' }))
      .toBeVisible()
    const confirmed = page.waitForResponse(response => (
      response.request().method() === 'POST'
      && new URL(response.url()).pathname
        === '/api/projects/' + PROJECT_ID + '/contracts/confirm'
    ))
    await page.getByRole('button', { name: '一次确认完整契约', exact: true }).click()
    expect((await confirmed).status()).toBe(201)
    await expect(page.getByRole('heading', { name: '当前生效的创作契约' }))
      .toBeVisible()

    await createSeedCandidate(page, SECOND_SEED_FIELDS)
    await selectSeed(page, '盐税暗潮', 2)
    await selectSeed(page, '雾港错钟', 3)

    await page.goto(PROJECT_PATH)
    await expect(page.getByRole('heading', { name: '当前生效的创作契约' }))
      .toHaveCount(0)
    await expect(page.getByRole('navigation', { name: '创作契约五个步骤' }))
      .toBeVisible()
    await expect(page.getByRole('button', { name: /故事发动机/ })).toBeVisible()
    await expect(page.getByRole('heading', { name: '选择能持续制造故事的发动机' }))
      .toBeVisible()
    const historyLoaded = page.waitForResponse(response => (
      response.request().method() === 'GET'
      && new URL(response.url()).pathname
        === '/api/projects/' + PROJECT_ID + '/contracts/history'
    ))
    await page.getByRole('button', { name: '历史修订', exact: true }).click()
    expect((await historyLoaded).status()).toBe(200)
    const historyDialog = page.getByRole('dialog').filter({
      has: page.getByText('创作契约历史', { exact: true }),
    })
    await expect(historyDialog).toHaveCount(1)
    const revisionOne = historyDialog.locator('.history-card').filter({
      has: page.getByRole('heading', { name: 'R1', exact: true }),
    })
    await expect(revisionOne).toHaveCount(1)
    await expect(revisionOne.getByText('种子选择代次已改变', { exact: true }))
      .toBeVisible()
    await expect(revisionOne.getByText('selection_revision_changed', { exact: true }))
      .toHaveCount(0)
    await expect(revisionOne.getByRole('button', { name: '调整未来设计', exact: true }))
      .toBeDisabled()
  } catch (error) {
    bodyError = error
  } finally {
    await finishRuntime(runtime, bodyError)
  }
})
