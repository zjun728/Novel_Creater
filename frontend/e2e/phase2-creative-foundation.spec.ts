import { expect, test } from '@playwright/test'
import { appendFileSync, writeFileSync } from 'node:fs'

import {
  assertExactWrites,
  assertRuntimeEvidenceHealthy,
  observeRuntime,
  runtimeSensitiveValues,
  scanRuntimeEvidence,
} from './runtime-observer.mjs'
import { SYNTHETIC_STORY_ENGINE_OPTIONS } from './synthetic-story-engine-options.mjs'


function requiredEnvironment(name: string) {
  const value = process.env[name]
  if (!value) throw new Error(`${name} is required from the Phase 2 runner`)
  return value
}


function requiredRunnerOrigin(name: string) {
  const value = requiredEnvironment(name)
  if (!/^http:\/\/127\.0\.0\.1:\d+$/u.test(value)) {
    throw new Error(`${name} must identify one exact runner-owned origin`)
  }
  return value
}


const VITE_ORIGIN = requiredRunnerOrigin('BROWSER_VITE_ORIGIN')
const BACKEND_ORIGIN = requiredRunnerOrigin('BROWSER_BACKEND_ORIGIN')
if (VITE_ORIGIN === BACKEND_ORIGIN) {
  throw new Error('runner-owned Vite and backend origins must be distinct')
}
const STEP_LEDGER = requiredEnvironment('BROWSER_STEP_LEDGER')
const RUNTIME_AUDIT_DIAGNOSTIC = requiredEnvironment(
  'BROWSER_RUNTIME_AUDIT_DIAGNOSTIC',
)
const CORPUS_FILE = requiredEnvironment('BROWSER_CORPUS_FILE')
const QIDIAN_FILE = requiredEnvironment('BROWSER_QIDIAN_SNAPSHOT_PATH')
const QQ_FILE = requiredEnvironment('BROWSER_QQ_SNAPSHOT_PATH')
const SENSITIVE_VALUES = [
  ...runtimeSensitiveValues(process.env),
  requiredEnvironment('BROWSER_TRANSCRIPT_SENTINEL'),
].filter(value => typeof value === 'string' && value.length > 0)
const STRICT_UUID = String.raw`[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}`
const PROJECT_TITLE = 'Phase 2 创作地基验收'
const SEED_A = Object.freeze([
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
const SEED_B = Object.freeze([
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


function recordStep(step: string) {
  appendFileSync(STEP_LEDGER, step + '\n', { encoding: 'utf8' })
}


function seedCard(page, name: string) {
  return page.locator('.seed-record').filter({
    has: page.getByRole('heading', { name, exact: true }),
  })
}


function sourceCard(page, name: string) {
  return page.locator('.source-sheet').filter({
    has: page.getByRole('heading', { name, exact: true }),
  })
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


function responseFailureCategory(value, projectId: string) {
  const match = String(value || '').match(/^(\d{3}) ([A-Z]+) (\S+)$/u)
  if (!match) {
    return {
      status: 'unparsed',
      method: 'UNKNOWN',
      pathnameCategory: 'unparsed',
    }
  }
  let pathname = ''
  try {
    pathname = new URL(match[3]).pathname
  } catch {
    return {
      status: Number(match[1]),
      method: match[2],
      pathnameCategory: 'unparsed',
    }
  }
  let pathnameCategory = 'non-api'
  if (pathname === `/api/projects/${projectId}/contract-draft`) {
    pathnameCategory = 'contract-draft'
  } else if (pathname === `/api/projects/${projectId}/bible/draft`) {
    pathnameCategory = 'bible-draft'
  } else if (pathname === '/api' || pathname.startsWith('/api/')) {
    pathnameCategory = 'other-api'
  }
  return {
    status: Number(match[1]),
    method: match[2],
    pathnameCategory,
  }
}


function pathCategory(value, projectId: string) {
  let pathname = ''
  try {
    pathname = new URL(value).pathname
  } catch {
    return 'unparsed'
  }
  const projectRoot = `/api/projects/${projectId}`
  if (pathname === '/api/projects' || pathname === projectRoot) return 'project'
  if (pathname === `${projectRoot}/preparation`) return 'overview-preparation'
  if (pathname === `${projectRoot}/contract-draft`) return 'contract-draft'
  if (pathname === `${projectRoot}/contract-head`) return 'contract-head'
  if (pathname === `${projectRoot}/bible/draft`) return 'bible-draft'
  if (pathname === `${projectRoot}/bible/head`) return 'bible-head'
  if (pathname.startsWith(`${projectRoot}/bible/history`)) return 'bible-history'
  if (pathname.startsWith('/api/market')) return 'market'
  if (
    pathname.startsWith('/api/corpus')
    || pathname.startsWith('/api/styles')
    || pathname.startsWith('/api/experience')
    || pathname.startsWith('/api/assets')
    || pathname.startsWith('/src/')
    || pathname.startsWith('/@vite/')
    || /\.(?:css|js|map|svg|png|woff2?)$/u.test(pathname)
  ) return 'assets'
  if (pathname === '/api' || pathname.startsWith('/api/')) return 'other-api'
  return 'non-api'
}


function runtimeErrorCategory(value) {
  const message = String(value || '')
  if (/cancel|ERR_ABORTED/iu.test(message)) return 'cancelled'
  if (/target.*closed|page.*closed|browser.*closed/iu.test(message)) {
    return 'target-closed'
  }
  if (/No resource with given identifier|Network\.getResponseBody/iu.test(message)) {
    return 'protocol-no-resource'
  }
  return 'other'
}


function requestFailureCategory(value, projectId: string) {
  const match = String(value || '').match(/^([A-Z]+) (\S+) (.*)$/u)
  if (!match) {
    return {
      method: 'UNKNOWN',
      pathCategory: 'unparsed',
      errorCategory: 'other',
    }
  }
  return {
    method: match[1],
    pathCategory: pathCategory(match[2], projectId),
    errorCategory: runtimeErrorCategory(match[3]),
  }
}


function consoleErrorCategory(value) {
  const message = String(value || '')
  if (/^error: \[界面错误\](?:\s|$)/u.test(message)) {
    return 'ui-error-boundary'
  }
  if (/status of 404\b/u.test(message)) return 'resource-404'
  if (/status of 4\d\d\b/u.test(message)) return 'resource-4xx'
  if (/status of 5\d\d\b/u.test(message)) return 'resource-5xx'
  return 'other-error'
}


function countedCategories(values, classify) {
  const counts = new Map()
  for (const value of values) {
    const category = classify(value)
    const key = JSON.stringify(category)
    const current = counts.get(key)
    counts.set(key, {
      ...category,
      count: Number(current?.count || 0) + 1,
    })
  }
  return [...counts.values()].sort((left, right) => (
    JSON.stringify(left).localeCompare(JSON.stringify(right))
  ))
}


function healthErrorCategories(evidence) {
  return [
    ['page-error', (evidence.pageErrors || []).length],
    ['request-failure', (evidence.requestFailures || []).length],
    [
      'api-response-header-read-error',
      (evidence.apiResponses || []).filter(entry => entry.headersReadError).length,
    ],
    [
      'api-response-body-read-error',
      (evidence.apiResponses || []).filter(entry => entry.bodyReadError).length,
    ],
    [
      'request-header-read-error',
      (evidence.requests || []).filter(entry => entry.headersReadError).length,
    ],
    [
      'request-body-read-error',
      (evidence.requests || []).filter(entry => entry.bodyReadError).length,
    ],
  ].filter(([, count]) => count > 0).map(([category, count]) => ({
    category,
    count,
  }))
}


function writeRuntimeAuditDiagnostic(evidence, projectId: string) {
  const responseFailures = countedCategories(
    evidence.responseFailures || [],
    value => responseFailureCategory(value, projectId),
  )
  const consoleErrors = countedCategories(
    evidence.consoleErrors || [],
    value => ({ category: consoleErrorCategory(value) }),
  )
  const healthErrors = healthErrorCategories(evidence)
  const requestFailureDetails = countedCategories(
    evidence.requestFailures || [],
    value => requestFailureCategory(value, projectId),
  )
  const apiResponseBodyReadErrorDetails = countedCategories(
    (evidence.apiResponses || []).filter(entry => entry.bodyReadError),
    entry => ({
      method: String(entry.method || 'UNKNOWN'),
      status: Number(entry.status || 0),
      pathCategory: pathCategory(entry.url, projectId),
      errorCategory: runtimeErrorCategory(entry.bodyReadError),
    }),
  )
  writeFileSync(
    RUNTIME_AUDIT_DIAGNOSTIC,
    JSON.stringify({
      responseFailures,
      consoleErrors,
      healthErrors,
      requestFailureDetails,
      apiResponseBodyReadErrorDetails,
    }),
    { encoding: 'utf8' },
  )
}


async function chooseVisibleSelectOption(page, select, label: string) {
  const trigger = select.locator('.n-base-selection')
  await trigger.click()
  await expect(trigger).toHaveClass(/n-base-selection--active/u)
  const filterInput = trigger.locator('input:not([readonly]):not([disabled])')
  if (await filterInput.count() === 1 && await filterInput.isEditable()) {
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


async function createProject(page) {
  await page.goto('/projects')
  await expect(page.getByRole('heading', { name: '项目库', exact: true }))
    .toBeVisible()
  recordStep('library-visible')
  await page.locator('.project-library-heading')
    .getByRole('button', { name: '新建项目', exact: true })
    .click()
  const dialog = page.getByRole('dialog', { name: '新建项目' })
  await dialog.getByLabel('项目名称').fill(PROJECT_TITLE)
  await dialog.getByRole('button', { name: '创建并打开', exact: true }).click()
  await expect.poll(() => new URL(page.url()).pathname).toMatch(
    new RegExp(String.raw`^/projects/${STRICT_UUID}/overview$`, 'u'),
  )
  const projectId = new URL(page.url()).pathname.split('/')[2]
  expect(projectId).toMatch(new RegExp(String.raw`^${STRICT_UUID}$`, 'u'))
  await expect(page.getByRole('heading', { name: PROJECT_TITLE, exact: true }))
    .toBeVisible()
  recordStep('project-created')
  return projectId
}


async function verifyAssetLibraries(page) {
  await page.goto('/assets/styles')
  await expect(page.getByRole('heading', { name: '风格模板库', exact: true }))
    .toBeVisible()
  await expect(page.locator('.style-grid article')).toHaveCount(10)
  await page.locator('.library-hero').getByRole('link', {
    name: '经验卡',
    exact: true,
  }).click()
  await expect(page).toHaveURL(/\/assets\/experience$/u)
  await expect(page.locator('.card-grid article')).toHaveCount(64)
  recordStep('assets-visible')
}


async function verifyBindings(page, projectId: string) {
  await page.goto(`/projects/${projectId}/settings/models`)
  await expect(page.getByRole('heading', { name: '项目模型绑定', exact: true }))
    .toBeVisible()
  await expect(page.getByText('Complete · 八项完整', { exact: true })).toBeVisible()
  await expect(page.getByText('Ready · 可调用', { exact: true })).toBeVisible()
  await page.getByRole('button', {
    name: '高级设置 · 分别绑定八项',
    exact: true,
  }).click()
  await expect(page.locator('.binding-row')).toHaveCount(8)
}


async function importCorpus(page) {
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
    relativePath: 'phase2-synthetic-corpus.txt',
    preflightStatus: 'eligible',
  }))
  const dialog = page.getByRole('dialog').filter({ hasText: 'CORPUS INTAKE' })
  await expect(dialog.getByText('导入为新的受管语料', { exact: true })).toBeVisible()
  await chooseVisibleSelectOption(page, dialog, 'phase2-synthetic-corpus.txt')
  await dialog.getByPlaceholder('例如：北境卷叙事样本')
    .fill('Phase 2 雾港参考片段')
  await dialog.getByRole('button', { name: '确认导入', exact: true }).click()
  await expect(page.getByRole('heading', {
    name: 'Phase 2 雾港参考片段',
    exact: true,
  })).toBeVisible()
  recordStep('corpus-imported')
}


async function importSnapshot(page, sourceName: string, filePath: string) {
  const card = sourceCard(page, sourceName)
  const chooserPromise = page.waitForEvent('filechooser')
  await card.getByRole('button', { name: '手动导入快照', exact: true }).click()
  const chooser = await chooserPromise
  await chooser.setFiles(filePath)
  await expect(card.getByText('快照可用', { exact: true })).toBeVisible()
}


async function createSeed(page, projectId: string, fields) {
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
    && new URL(response.url()).pathname === `/api/projects/${projectId}/seeds`
  ))
  await editor.getByRole('button', { name: '保存种子', exact: true }).click()
  expect((await created).status()).toBe(200)
  await expect(seedCard(page, fields[0][1])).toBeVisible()
}


async function selectSeed(
  page,
  projectId: string,
  name: string,
  expectedSelectionRevision: number,
) {
  const selected = page.waitForResponse(response => (
    response.request().method() === 'PUT'
    && new URL(response.url()).pathname
      === `/api/projects/${projectId}/selected-seed`
  ))
  await seedCard(page, name)
    .getByRole('button', { name: '立即选定', exact: true })
    .click()
  expect((await selected).status()).toBe(200)
  await expect(page.getByText(
    `选定代次 ${expectedSelectionRevision}`,
    { exact: true },
  )).toBeVisible()
}


async function prepareMarketAndSeeds(page, projectId: string) {
  await page.goto(`/projects/${projectId}/seeds`)
  const qidian = sourceCard(page, '起点新签榜')
  const qq = sourceCard(page, 'QQ 阅读男生人气榜')
  await expect(qidian).toBeVisible()
  await expect(qq).toBeVisible()
  await importSnapshot(page, '起点新签榜', QIDIAN_FILE)
  await importSnapshot(page, 'QQ 阅读男生人气榜', QQ_FILE)
  await expect(page.getByText('2 份可用快照', { exact: true })).toBeVisible()
  recordStep('market-snapshots-imported')

  await createSeed(page, projectId, SEED_A)
  await selectSeed(page, projectId, '雾港错钟', 1)
  recordStep('seed-a-selected')
  await createSeed(page, projectId, SEED_B)
  await selectSeed(page, projectId, '盐税暗潮', 2)
  recordStep('seed-b-selected')
  await selectSeed(page, projectId, '雾港错钟', 3)
  recordStep('seed-a-reselected')
}


async function fillManualEngines(page, projectId: string) {
  await page.locator('label').filter({ hasText: '渠道定位标识' })
    .locator('input').fill('phase2-manual-channel')
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
  const manualBatch = page.waitForResponse(response => (
    response.request().method() === 'POST'
    && new URL(response.url()).pathname
      === `/api/projects/${projectId}/story-engine-batches/manual`
  ))
  await sheet.getByRole('button', { name: '建立手动三案' }).click()
  expect((await manualBatch).status()).toBe(201)
  await expect(page.getByRole('radio')).toHaveCount(3)
  await page.getByRole('radio', { name: /潮钟追凶/u }).click()
  const draftSaved = page.waitForResponse(response => (
    response.request().method() === 'PUT'
    && new URL(response.url()).pathname
      === `/api/projects/${projectId}/contract-draft`
  ))
  const recommendationsLoaded = page.waitForResponse(response => (
    response.request().method() === 'POST'
    && new URL(response.url()).pathname
      === `/api/projects/${projectId}/asset-recommendations`
  ))
  await page.getByRole('button', { name: '保存草稿并继续' }).click()
  expect((await draftSaved).status()).toBe(200)
  expect((await recommendationsLoaded).status()).toBe(200)
}


async function selectStyles(page, projectId: string) {
  await expect(page.getByRole('heading', { name: '先定阅读感受，再谈写法' }))
    .toBeVisible()
  const selectionPanel = page.locator('section.selection-panel')
  const selectGrid = selectionPanel.locator('.select-grid')
  await chooseVisibleSelectOption(
    page,
    selectGrid.locator('label').filter({ hasText: '主风格' }),
    '克制悬疑型 · r1',
  )
  await chooseVisibleSelectOption(
    page,
    selectGrid.locator('label').filter({ hasText: '次风格' }),
    '沉浸群像型 · r1',
  )
  const saved = page.waitForResponse(response => (
    response.request().method() === 'PUT'
    && new URL(response.url()).pathname
      === `/api/projects/${projectId}/contract-draft`
  ))
  await page.getByRole('button', { name: '保存草稿并继续' }).click()
  expect((await saved).status()).toBe(200)
}


async function selectAssets(page, projectId: string) {
  await expect(page.getByRole('heading', { name: '逐项授权，片段级冻结' }))
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
  await chooseVisibleSelectOption(
    page,
    page.locator('.fragment-browser header .n-select'),
    '01 · 第一章 雾港错钟',
  )
  const fragment = page.locator('.fragment-browser article').filter({
    hasText: '片段 1',
  })
  await fragment.getByRole('button', { name: '选择片段' }).click()
  const rangeRow = page.locator('.range-ledger article')
  await rangeRow.locator('label').filter({ hasText: '起' })
    .locator('input').fill('0')
  await rangeRow.locator('label').filter({ hasText: '止' })
    .locator('input').fill('20')
  await chooseVisibleSelectOption(page, rangeRow.locator('.n-select'), '结构')
  const saved = page.waitForResponse(response => (
    response.request().method() === 'PUT'
    && new URL(response.url()).pathname
      === `/api/projects/${projectId}/contract-draft`
  ))
  await page.getByRole('button', { name: '保存草稿并继续' }).click()
  expect((await saved).status()).toBe(200)
}


async function enterCapacity(page, projectId: string) {
  await expect(page.getByRole('heading', { name: '给长篇一副可调整的骨架' }))
    .toBeVisible()
  for (const [label, value] of [
    ['目标总字数', '720000'],
    ['预计卷数', '8'],
    ['预计章节数', '240'],
    ['下限', '2200'],
    ['上限', '3200'],
  ]) {
    await page.locator('label').filter({ hasText: label })
      .locator('input').fill(value)
  }
  await page.locator('label').filter({ hasText: '禁止方向' }).locator('textarea')
    .fill('不写无代价升级\n不把配角当作一次性工具')
  await page.locator('label').filter({ hasText: '作者备注' }).locator('textarea')
    .fill('让每次知识兑现都改变群像关系。')
  const saved = page.waitForResponse(response => (
    response.request().method() === 'PUT'
    && new URL(response.url()).pathname
      === `/api/projects/${projectId}/contract-draft`
  ))
  await page.getByRole('button', { name: '保存草稿并继续' }).click()
  expect((await saved).status()).toBe(200)
}


async function confirmContract(page, projectId: string) {
  await page.goto(`/projects/${projectId}/contract`)
  await expect(page.getByRole('heading', { name: '本书创作契约' })).toBeVisible()
  await fillManualEngines(page, projectId)
  await selectStyles(page, projectId)
  await selectAssets(page, projectId)
  await enterCapacity(page, projectId)
  await expect(page.getByRole('heading', { name: '预览全部变化，再一次确认' }))
    .toBeVisible()
  const confirmed = page.waitForResponse(response => (
    response.request().method() === 'POST'
    && new URL(response.url()).pathname
      === `/api/projects/${projectId}/contracts/confirm`
  ))
  await page.getByRole('button', { name: '一次确认完整契约' }).click()
  expect((await confirmed).status()).toBe(201)
  await expect(page.getByRole('heading', { name: '当前生效的创作契约' }))
    .toBeVisible()
  recordStep('contract-confirmed')
}


function bibleEditor(page) {
  return page.getByRole('region', { name: '创作圣经编辑器' })
}


function bibleScalar(page, label: string) {
  return bibleEditor(page).locator('label').filter({ hasText: label })
    .locator('textarea')
}


async function confirmBible(page) {
  await page.getByRole('button', { name: '预览并确认', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: '确认新的未来设计' })
  await expect(dialog).toBeVisible()
  const confirmation = page.waitForResponse(response => (
    response.request().method() === 'POST'
    && /\/api\/projects\/[^/]+\/bible\/confirm$/u.test(
      new URL(response.url()).pathname,
    )
  ))
  await dialog.getByRole('button', { name: '确认签印', exact: true }).click()
  expect((await confirmation).status()).toBe(201)
  await expect(page.getByText('已确认新的创作圣经修订', { exact: true }))
    .toBeVisible()
}


async function completeBible(page, projectId: string) {
  await page.goto(`/projects/${projectId}/bible`)
  await expect(page.getByRole('heading', {
    name: `${PROJECT_TITLE} 的创作圣经`,
    exact: true,
  })).toBeVisible()
  await expect(page.getByLabel('AI 辅助状态')).toContainText('Ready')
  recordStep('bible-workspace-visible')
  const generationPanel = page.getByRole('region', { name: 'AI 生成创作圣经' })
  await generationPanel.getByLabel('作者补充要求（可选）')
    .fill('保持人物欲望、群像关系和现实代价具体。')
  const generated = page.waitForResponse(response => (
    response.request().method() === 'POST'
    && new URL(response.url()).pathname
      === `/api/projects/${projectId}/bible/generate`
  ))
  await generationPanel.getByRole('button', { name: '生成创作圣经' }).click()
  const generatedResponse = await generated
  recordStep('bible-generation-returned')
  expect(generatedResponse.status()).toBe(200)
  recordStep('bible-generation-http-ok')
  await expect(page.getByText('已生成新的创作圣经草稿', { exact: true }))
    .toBeVisible()
  recordStep('bible-generation-notice-visible')
  await expect(bibleScalar(page, '主角')).toHaveValue(/沈砚谨慎/u)
  recordStep('bible-generation-succeeded')

  await bibleScalar(page, '主角').fill(
    '沈砚谨慎、重证据，却会为了眼前的人主动承担公开判断的代价。',
  )
  const savedFirst = page.waitForResponse(response => (
    response.request().method() === 'PUT'
    && new URL(response.url()).pathname
      === `/api/projects/${projectId}/bible/draft`
  ))
  await page.getByRole('button', { name: '手动保存', exact: true }).click()
  expect((await savedFirst).status()).toBe(200)
  await expect(page.getByText('草稿已保存', { exact: true })).toBeVisible()
  recordStep('bible-first-saved')
  await confirmBible(page)
  await expect(page.getByRole('button', { name: '调整未来设计' })).toBeVisible()
  recordStep('bible-first-confirmed')

  const cloned = page.waitForResponse(response => (
    response.request().method() === 'POST'
    && new URL(response.url()).pathname
      === `/api/projects/${projectId}/bible/draft/clone`
  ))
  await page.getByRole('button', { name: '调整未来设计' }).click()
  expect((await cloned).status()).toBe(200)
  await expect(page.getByText('已创建未来设计草稿', { exact: true })).toBeVisible()
  recordStep('bible-adjustment-created')
  const preserved = await bibleScalar(page, '主角').inputValue()
  await generationPanel.getByLabel('作者补充要求（可选）')
    .fill('FAIL_SAFE')
  const failed = page.waitForResponse(response => (
    response.request().method() === 'POST'
    && new URL(response.url()).pathname
      === `/api/projects/${projectId}/bible/generate`
  ))
  await generationPanel.getByRole('button', { name: '生成创作圣经' }).click()
  const failedResponse = await failed
  recordStep('bible-failure-returned')
  expect(failedResponse.status()).toBe(200)
  expect(await failedResponse.json()).toMatchObject({
    attempt: {
      status: 'failed',
      publicErrorCode: 'BibleGenerationProviderFailed',
    },
  })
  await expect(page.getByRole('alert')).toContainText('创作圣经操作失败')
  await expect(bibleScalar(page, '主角')).toHaveValue(preserved)
  recordStep('bible-failure-preserved')

  await bibleScalar(page, '主角').fill(
    '沈砚仍重证据，但第二版要求他先听完同伴的代价，再作公开判断。',
  )
  const savedSecond = page.waitForResponse(response => (
    response.request().method() === 'PUT'
    && new URL(response.url()).pathname
      === `/api/projects/${projectId}/bible/draft`
  ))
  await page.getByRole('button', { name: '手动保存', exact: true }).click()
  expect((await savedSecond).status()).toBe(200)
  recordStep('bible-second-saved')
  await confirmBible(page)
  recordStep('bible-second-confirmed')

  await page.getByRole('button', { name: '修订历史', exact: true }).click()
  const history = page.getByRole('dialog', { name: '创作圣经历史' })
  await expect(history.getByText('Revision 2', { exact: true })).toBeVisible()
  await expect(history.getByText('Revision 1', { exact: true })).toBeVisible()
  await history.locator('article').filter({ hasText: 'Revision 2' })
    .getByRole('button', { name: '查看详情' }).click()
  await expect(
    history.locator('.history-detail')
      .getByRole('heading', { name: 'Revision 2' }),
  ).toBeVisible()
  await history.getByRole('button', { name: '关闭历史' }).click()
}


async function settleNavigationBoundary(page, runtime) {
  await page.waitForLoadState('networkidle')
  await runtime.settle()
}


async function verifyNavigationAndPreparation(page, projectId: string, runtime) {
  const biblePath = `/projects/${projectId}/bible`
  const overviewPath = `/projects/${projectId}/overview`
  await settleNavigationBoundary(page, runtime)
  await page.reload()
  await expect(page.getByRole('heading', {
    name: `${PROJECT_TITLE} 的创作圣经`,
    exact: true,
  })).toBeVisible()
  await settleNavigationBoundary(page, runtime)
  await page.setViewportSize({ width: 390, height: 844 })
  await expect(
    page.locator('.product-app-shell[data-sidebar-collapsed="true"]'),
  ).toBeVisible()
  await expect(page.getByRole('heading', {
    name: `${PROJECT_TITLE} 的创作圣经`,
    exact: true,
  })).toBeVisible()
  await page.goto(overviewPath)
  await expect(page).toHaveURL(new RegExp(`${overviewPath}$`, 'u'))
  await settleNavigationBoundary(page, runtime)
  await page.goto(biblePath)
  await expect(page).toHaveURL(new RegExp(`${biblePath}$`, 'u'))
  await settleNavigationBoundary(page, runtime)
  await page.goBack()
  await expect(page).toHaveURL(new RegExp(`${overviewPath}$`, 'u'))
  await settleNavigationBoundary(page, runtime)
  await page.goForward()
  await expect(page).toHaveURL(new RegExp(`${biblePath}$`, 'u'))
  await settleNavigationBoundary(page, runtime)
  recordStep('navigation-boundaries-verified')

  const preparationResponse = page.waitForResponse(response => (
    response.request().method() === 'GET'
    && new URL(response.url()).pathname
      === `/api/projects/${projectId}/preparation`
  ))
  await page.goto(overviewPath)
  const preparation = await preparationResponse
  expect(preparation.status()).toBe(200)
  expect((await preparation.json()).nextAction).toBe('phase_boundary_planning')
  await expect(page.getByText('创作准备已完成', { exact: true })).toBeVisible()
  await settleNavigationBoundary(page, runtime)
  recordStep('preparation-boundary-visible')
}


async function archiveAndVerifyReadOnly(page, projectId: string, runtime) {
  await page.setViewportSize({ width: 1280, height: 900 })
  await page.goto('/projects')
  const card = page.locator('.project-card').filter({
    has: page.getByRole('heading', { name: PROJECT_TITLE, exact: true }),
  })
  await expect(card).toBeVisible()
  await settleNavigationBoundary(page, runtime)
  recordStep('archive-project-card-visible')
  await card.getByText('更多', { exact: true }).click()
  const archived = page.waitForResponse(response => (
    response.request().method() === 'POST'
    && new URL(response.url()).pathname
      === `/api/projects/${projectId}/archive`
  ))
  await card.getByRole('button', { name: '归档', exact: true }).click()
  expect((await archived).status()).toBe(200)
  await settleNavigationBoundary(page, runtime)
  recordStep('archive-returned')
  await page.goto(`/projects/${projectId}/overview`)
  await expect(page.locator('.status-mark')).toHaveText('已归档')
  await settleNavigationBoundary(page, runtime)
  recordStep('archive-status-visible')
  await page.getByRole('link', { name: '查看只读创作圣经', exact: true }).click()
  await expect(page.getByText('此项目或当前服务端状态为只读。', { exact: true }))
    .toBeVisible()
  recordStep('archive-bible-visible')
  await expect(page.getByRole('button', { name: '生成创作圣经' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: '手动保存' })).toHaveCount(0)
  await settleNavigationBoundary(page, runtime)
  recordStep('project-archived-read-only')

  await page.goto('/not-found')
  await expect(page.getByRole('heading', {
    name: '此入口已升级或不存在',
    exact: true,
  })).toBeVisible()
  await settleNavigationBoundary(page, runtime)
  recordStep('not-found-visible')
}


async function auditRuntime(evidence, checkpoints, projectId: string) {
  const audited = { ...evidence, checkpointSurfaces: checkpoints }
  const contractDraftPath = `/api/projects/${projectId}/contract-draft`
  assertRuntimeEvidenceHealthy(evidence, {
    responseFailureAllowlist: [{
      status: 404,
      method: 'GET',
      pathname: contractDraftPath,
      count: 1,
    }],
    consoleErrorAllowlist: [{
      message: 'error: Failed to load resource: the server responded with a status of 404 (Not Found)',
      count: 1,
      linkedResponseFailure: {
        status: 404,
        method: 'GET',
        pathname: contractDraftPath,
      },
    }],
  })
  recordStep('audit-known-failures-verified')
  recordStep('audit-runtime-health-verified')
  assertExactWrites(audited, [
    { method: 'POST', path: '/api/projects', statuses: [200], count: 1 },
    { method: 'POST', path: '/api/corpus/imports', statuses: [200], count: 1 },
    {
      method: 'POST',
      path: /^\/api\/market-sources\/[^/]+\/manual-import$/u,
      statuses: [200],
      count: 2,
    },
    {
      method: 'POST',
      path: `/api/projects/${projectId}/seeds`,
      statuses: [200],
      count: 2,
    },
    {
      method: 'PUT',
      path: `/api/projects/${projectId}/selected-seed`,
      statuses: [200],
      count: 3,
    },
    {
      method: 'POST',
      path: `/api/projects/${projectId}/story-engine-batches/manual`,
      statuses: [201],
      count: 1,
    },
    {
      method: 'POST',
      path: `/api/projects/${projectId}/asset-recommendations`,
      statuses: [200],
      count: 2,
    },
    {
      method: 'PUT',
      path: `/api/projects/${projectId}/contract-draft`,
      statuses: [200],
      count: 4,
    },
    {
      method: 'POST',
      path: `/api/projects/${projectId}/contracts/preview`,
      statuses: [200],
      count: 1,
    },
    {
      method: 'POST',
      path: `/api/projects/${projectId}/contracts/confirm`,
      statuses: [201],
      count: 1,
    },
    {
      method: 'POST',
      path: `/api/projects/${projectId}/bible/generate`,
      statuses: [200],
      count: 2,
    },
    {
      method: 'PUT',
      path: `/api/projects/${projectId}/bible/draft`,
      statuses: [200],
      count: 2,
    },
    {
      method: 'POST',
      path: `/api/projects/${projectId}/bible/draft/clone`,
      statuses: [200],
      count: 1,
    },
    {
      method: 'POST',
      path: `/api/projects/${projectId}/bible/confirm`,
      statuses: [201],
      count: 2,
    },
    {
      method: 'POST',
      path: `/api/projects/${projectId}/archive`,
      statuses: [200],
      count: 1,
    },
  ])
  recordStep('audit-writes-verified')
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
  recordStep('audit-origins-verified')
  expect(scanRuntimeEvidence(audited, SENSITIVE_VALUES)).toEqual({
    matchCount: 0,
  })
  recordStep('audit-secret-scan-verified')
}


test('accepts the complete Phase 2 creative foundation through real UI', async ({
  page,
}) => {
  test.setTimeout(240_000)
  const runtime = observeRuntime(page)
  const checkpoints: Array<{ dom: string; visibleText: string }> = []
  let bodyError: unknown = null
  let auditError: unknown = null
  let projectId = ''
  const checkpoint = async () => {
    await page.waitForLoadState('networkidle')
    await runtime.settle()
    checkpoints.push({
      dom: await page.content(),
      visibleText: await page.locator('body').innerText(),
    })
  }
  try {
    projectId = await createProject(page)
    await verifyAssetLibraries(page)
    await verifyBindings(page, projectId)
    await importCorpus(page)
    await prepareMarketAndSeeds(page, projectId)
    await checkpoint()
    await confirmContract(page, projectId)
    await checkpoint()
    await completeBible(page, projectId)
    await checkpoint()
    await verifyNavigationAndPreparation(page, projectId, runtime)
    await archiveAndVerifyReadOnly(page, projectId, runtime)
    await checkpoint()
  } catch (error) {
    bodyError = error
  } finally {
    try {
      const evidence = await runtime.finish()
      writeRuntimeAuditDiagnostic(evidence, projectId)
      await auditRuntime(evidence, checkpoints, projectId)
    } catch (error) {
      auditError = error
    }
  }
  if (bodyError && auditError) {
    throw new AggregateError(
      [bodyError, auditError],
      `behavior and runtime audit failed; writes=${JSON.stringify(observedWrites({
        apiResponses: [],
      }))}`,
    )
  }
  if (bodyError) throw bodyError
  if (auditError) throw auditError
  recordStep('runtime-clean')
})
