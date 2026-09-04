import { expect, test, type Locator, type Page } from '@playwright/test'

import {
  assertExactWrites,
  assertRuntimeEvidenceHealthy,
  observeRuntime,
  publicRuntimeDiagnostic,
  runtimeSensitiveValues,
  scanRuntimeEvidence,
} from './runtime-observer.mjs'

function required(name: string) {
  const value = process.env[name]
  if (!value) throw new Error(`${name} is required from the P0-D runner`)
  return value
}

const PROJECT_ID = required('BROWSER_PROJECT_ID')
const VITE_ORIGIN = required('BROWSER_VITE_ORIGIN')
const BACKEND_ORIGIN = required('BROWSER_BACKEND_ORIGIN')
const SENSITIVE_VALUES = runtimeSensitiveValues({
  BROWSER_SECRET_SENTINEL: required('BROWSER_SECRET_SENTINEL'),
})

const FINAL_SEED_PAYLOAD = Object.freeze({
  title: '典镇山河',
  genre: '东方玄幻',
  targetAudience: '偏爱建设流、群像成长与规则悬疑的男频长篇读者',
  logline: '守典人沈砚从一座被舆图抹去的县城起步，以公开规则重建失序山河。',
  protagonist: '谨慎克制、相信证据但必须学会承担公共代价的守典人沈砚',
  desire: '保住故乡、找回失踪师父，并让普通人拥有可依赖的秩序',
  coreConflict: '每次借残典修复一层秩序，都会暴露沈砚并惊动更高层的既得势力',
  worldPressure: '王朝崩解、诡异复苏和地方豪强同时挤压基层生存空间',
  openingHook: '县城一夜从王朝舆图上消失，只有沈砚手中的残典仍记得它。',
  differentiation: '把基层制度建设写成可见行动、人物选择和玄幻成长，而非设定说明',
  storyPromise: '每卷解决一层秩序危机，同时让人物为扩张后的责任支付更高代价',
  longFormPotential: '县、州、国、天下四级扩张，二十四卷与七百二十章都有独立矛盾及回收点',
  marketBasis: '作者复核：建设流、规则压力与人物代价能够共同支撑二百万字长篇。',
})

const FINAL_ENGINE = Object.freeze({
  name: '山河重建',
  storyPromise: '每卷修复一层公共秩序，同时揭开残典来源。',
  protagonistDesire: '守住故乡并找回师父。',
  sustainedPressure: '每次改革都会触发更高层反扑。',
  growthDirection: '从独自校勘成长为公开承担责任的治理者。',
  conflictLoop: '发现失序、核验证据、建立规则、承受反扑。',
  ensembleRoles: [{ role: '县吏陆青禾', purpose: '把制度变化落实到普通人的代价。' }],
  advantageAndCost: '残典能指出规则裂缝，但每次使用都会暴露持有者。',
  satisfactionSources: ['秩序重建', '证据反转'],
  longFormVariation: ['县州国天下四级扩张', '不同群体对秩序的竞争'],
  endingAnchor: '天下建立可公开校验的新典制。',
  risks: ['避免制度说明挤压人物行动。'],
  differentiation: '制度建设本身构成玄幻升级。',
})

const FINAL_SEED_CONTENT = Object.freeze({
  positioning: [
    '典镇山河',
    '东方玄幻',
    '偏爱建设流、群像成长与规则悬疑的男频长篇读者',
  ],
  core: [
    '守典人沈砚从一座被舆图抹去的县城起步，以公开规则重建失序山河。',
    '谨慎克制、相信证据但必须学会承担公共代价的守典人沈砚',
    '保住故乡、找回失踪师父，并让普通人拥有可依赖的秩序',
    '每次借残典修复一层秩序，都会暴露沈砚并惊动更高层的既得势力',
  ],
  pressure: [
    '王朝崩解、诡异复苏和地方豪强同时挤压基层生存空间',
    '县城一夜从王朝舆图上消失，只有沈砚手中的残典仍记得它。',
  ],
  promise: [
    '把基层制度建设写成可见行动、人物选择和玄幻成长，而非设定说明',
    '每卷解决一层秩序危机，同时让人物为扩张后的责任支付更高代价',
    '县、州、国、天下四级扩张，二十四卷与七百二十章都有独立矛盾及回收点',
    '作者复核：建设流、规则压力与人物代价能够共同支撑二百万字长篇。',
  ],
})

const FINAL_BIBLE_CONTENT = Object.freeze({
  premise: ['秩序每扩张一级，沈砚都必须公开承担新的制度代价。'],
  world_rules: ['任何借残典改变的规则都必须公开记录，否则会转化为新的诡异缺口。'],
  progression: ['沈砚通过校勘、试行和公众见证修复典制；成长不是单纯战力，而是能承担更大范围规则后果的能力。'],
  core_characters: [
    '沈砚谨慎克制，擅长核验证据，初期只想保住故乡，最终必须学会把权力交给可被监督的共同制度。',
    '陆青禾负责把抽象规则落到民生现场，她既是同盟也是最严格的质疑者。',
  ],
  factions: ['守典司掌握旧档与合法性，却因维护封闭权威而成为改革阻力。'],
  long_term_conflicts: ['秩序扩张越快，地方自主与统一规则之间的冲突越尖锐。'],
  relationships: ['沈砚与陆青禾的信任建立在公开分歧和共同承担后果之上。'],
  tone_boundaries: ['叙事克制、具体、以行动和选择展示设定；不靠无代价升级解决矛盾，不用旁白替代人物冲突。'],
  continuity_guardrails: ['每次残典介入必须留下可追踪代价，已经公开的规则不能无解释失效。'],
  open_questions: ['师父为何主动留下残缺而非完整典籍，留待中后期逐层回答。'],
})

const SEED_WRITE_BUTTONS = Object.freeze([
  '新建候选种子', '编辑本区', '完成本区编辑', '创建候选种子', '保存种子',
  '确认项目种子', '归档', '恢复', '永久删除', '选择项目种子',
])
const CONTRACT_WRITE_BUTTONS = Object.freeze([
  '编辑本节', '普通字段手动录入', '生成三套方案', '生成新三案', '建立手动三案',
  '保存本节', '设为主风格', '设为次风格', '取消次风格', '运行临时试写',
  '明确纳入', '移出范围', '明确纳入推荐范围', '移出推荐范围', '选择片段', '移出',
  '核对并签印完整契约', '一次确认完整契约', '使用同一命令重试',
])
const BIBLE_WRITE_BUTTONS = Object.freeze([
  '编辑本区', '完成本区编辑', 'AI 生成初稿', 'AI 补充/重写本区',
  '手动保存', '采纳建议', '预览并确认', '确认签印',
])

function section(page: Page, id: string): Locator {
  return page.locator(`#${id}`).locator('..').locator('..')
}

async function expectVisibleContent(target: Locator, values: readonly string[]) {
  for (const value of values) await expect(target.getByText(value, { exact: true })).toBeVisible()
}

async function expectReadOnlyDocument(page: Page, writeButtons: readonly string[]) {
  const document = page.getByRole('region', { name: '创作正文' })
  const workspace = page.locator('.foundation-workspace')
  await expect(document.locator('input, textarea, select, [contenteditable="true"]')).toHaveCount(0)
  for (const name of writeButtons) {
    await expect(workspace.getByRole('button', { name, exact: true })).toHaveCount(0)
  }
}

async function readPublicApi(page: Page, resource: string) {
  return page.evaluate(async ({ backend, path }) => {
    const response = await fetch(`${backend}${path}`)
    if (!response.ok) throw new Error(`Public API read failed: ${response.status}`)
    return response.json()
  }, { backend: BACKEND_ORIGIN, path: resource })
}

async function chooseVisibleSelectOption(page: Page, select: Locator, label: string) {
  const trigger = select.locator('.n-base-selection')
  await trigger.click()
  const filterInput = trigger.locator('input:not([readonly]):not([disabled])')
  if (await filterInput.count() === 1 && await filterInput.isEditable()) {
    await filterInput.fill(label)
  }
  const escaped = label.replace(/[.*+?^${}()|[\]\\]/gu, '\\$&')
  const options = page.locator('.n-base-select-option:visible').filter({
    hasText: new RegExp(escaped, 'u'),
  })
  await expect(options).toHaveCount(1)
  await options.click()
}

function waitForWrite(page: Page, method: string, path: RegExp) {
  return page.waitForResponse(response => (
    response.request().method() === method
    && path.test(new URL(response.url()).pathname)
  ))
}

async function readBibleDraft(page: Page) {
  return page.evaluate(async ({ backend, project }) => {
    const response = await fetch(`${backend}/api/projects/${project}/bible/draft`)
    if (!response.ok) throw new Error(`Bible draft read failed: ${response.status}`)
    return response.json()
  }, { backend: BACKEND_ORIGIN, project: PROJECT_ID })
}

function expectCompleteConfirmedContract(
  head: Record<string, any>,
  preview: Record<string, any>,
  selectedExperienceIdentity: Record<string, unknown>,
  selectedStyleIdentity: Record<string, unknown>,
) {
  expect(preview.contractReady).toBe(true)
  expect(head).toEqual({
    projectId: PROJECT_ID,
    revision: 1,
    selectionRevision: preview.selectionRevision,
    hasContract: true,
    creationContractId: expect.stringMatching(/^[0-9a-f-]{36}$/u),
    styleContractId: expect.stringMatching(/^[0-9a-f-]{36}$/u),
    contractReady: true,
    reasons: [],
    supersededReasons: [],
    seedRef: preview.seedRef,
    engineRef: preview.engineRef,
    bindingRef: preview.bindingRef,
    styleRefs: preview.styleRefs,
    experienceCardRefs: preview.experienceCardRefs,
    corpusSourceRefs: preview.corpusSourceRefs,
    creationContract: preview.creationContract,
    styleContract: preview.styleContract,
    likes: preview.likes,
    dislikes: preview.dislikes,
    creationHash: preview.creationHash,
    styleHash: preview.styleHash,
  })
  expect(head.creationContract).toEqual({
    schemaVersion: 'creation-contract-v1',
    channelProfileKey: '男频长篇',
    genreProfileKey: '东方玄幻',
    qualityCharterVersion: 'story-first-quality-v1',
    selectionRevision: preview.selectionRevision,
    selectedSeed: FINAL_SEED_PAYLOAD,
    seedRevisionId: preview.seedRef.revisionId,
    seedHash: preview.seedRef.contentHash,
    selectedEngine: FINAL_ENGINE,
    engineOptionId: preview.engineRef.id,
    engineHash: preview.engineRef.contentHash,
    primaryStyleRef: selectedStyleIdentity,
    secondaryStyleRef: null,
    experienceCardRefs: [selectedExperienceIdentity],
    corpusSourceRefs: [],
    targetTotalWords: 2_400_000,
    expectedVolumeCount: 24,
    expectedChapterCount: 720,
    chapterWordRangePreference: [2_800, 4_200],
    prohibitedDirections: ['不写无代价升级', '不以旁白替代人物行动'],
    authorNotes: '以人物选择推动每卷秩序升级，保持长线伏笔可回收。',
    modelBindingRef: {
      id: preview.bindingRef.id,
      revision: preview.bindingRef.revision,
      contentHash: preview.bindingRef.contentHash,
    },
  })
  expect(head.styleRefs).toEqual([{ role: 'primary', ...selectedStyleIdentity }])
  expect(head.experienceCardRefs).toEqual([selectedExperienceIdentity])
  expect(head.creationContract.experienceCardRefs).toEqual([selectedExperienceIdentity])
}

async function expectNoHorizontalOverflow(page: Page) {
  await expect(page.locator('.foundation-workspace')).toBeVisible()
  const overflowingElements = await page.evaluate(() => {
    const workspace = document.querySelector('.foundation-workspace')
    if (!workspace) return [{ element: '[missing-workspace]' }]
    const viewportWidth = window.innerWidth
    return [workspace, ...workspace.querySelectorAll('*')].flatMap((element) => {
      const style = window.getComputedStyle(element)
      const rect = element.getBoundingClientRect()
      if (
        style.display === 'none'
        || style.visibility === 'hidden'
        || rect.width === 0
        || rect.height === 0
      ) return []
      const escapesViewport = rect.left < -1 || rect.right > viewportWidth + 1
      if (!escapesViewport) return []
      return [{
        element: element.tagName.toLowerCase(),
        className: typeof element.className === 'string' ? element.className : '',
        left: Math.round(rect.left),
        right: Math.round(rect.right),
        clientWidth: element.clientWidth,
        scrollWidth: element.scrollWidth,
      }]
    }).slice(0, 20)
  })
  expect(overflowingElements).toEqual([])
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
}

async function openContractSection(page: Page, id: string) {
  const target = section(page, id)
  await target.scrollIntoViewIfNeeded()
  const edit = target.getByRole('button', { name: '编辑本节', exact: true })
  if (await edit.count()) await edit.click()
  return target
}

test('accepts the complete P0-D seed, contract, and Bible author flow', async ({ page }) => {
  // A missing draft is normal before the first save; keep that read from polluting the strict console audit.
  await page.route(/\/api\/projects\/[^/]+\/contract-draft$/u, async route => {
    if (route.request().method() !== 'GET') return route.continue()
    const response = await route.fetch()
    if (response.status() !== 404) return route.fulfill({ response })
    return route.fulfill({ status: 200, contentType: 'application/json', body: 'null' })
  })
  const runtime = observeRuntime(page, { allowedOrigins: [VITE_ORIGIN, BACKEND_ORIGIN] })
  let bodyFailure: unknown = null
  let auditFailure: unknown = null

  try {
    await page.goto(`/projects/${PROJECT_ID}/seeds`)
    await expect(page.getByRole('heading', { name: '创作种子', exact: true })).toBeVisible()
    const candidate = page.locator('.seed-card').filter({ hasText: '典镇山河' })
    await candidate.getByRole('button', { name: /查看完整内容/u }).click()
    const seedDocument = page.getByRole('article', { name: '项目种子完整文档' })
    for (const label of [
      '标题', '题材', '目标读者', '一句话故事', '主角', '核心欲望', '核心冲突',
      '世界压力', '开篇钩子', '差异化', '故事承诺', '长篇潜力', '市场依据',
    ]) await expect(seedDocument.getByText(label, { exact: true })).toBeVisible()

    await section(page, 'seed-promise').getByRole('button', { name: '编辑本区', exact: true }).click()
    await section(page, 'seed-promise').locator('label').filter({ hasText: '市场依据' }).locator('textarea').fill('作者复核：建设流、规则压力与人物代价能够共同支撑二百万字长篇。')
    await section(page, 'seed-promise').getByRole('button', { name: '完成本区编辑', exact: true }).click()
    const seedSave = waitForWrite(page, 'PUT', /\/api\/projects\/[^/]+\/seeds\/[^/]+$/u)
    await page.getByRole('button', { name: '保存种子', exact: true }).click()
    expect((await seedSave).status()).toBe(200)

    await page.getByRole('button', { name: '确认项目种子', exact: true }).click()
    const seedDialog = page.getByRole('dialog', { name: '确认项目种子', exact: true })
    const seedConfirm = waitForWrite(page, 'PUT', /\/api\/projects\/[^/]+\/selected-seed$/u)
    await seedDialog.getByRole('button', { name: '确认项目种子', exact: true }).click()
    expect((await seedConfirm).status()).toBe(200)
    await expect(page).toHaveURL(new RegExp(`/projects/${PROJECT_ID}/seeds$`, 'u'))
    await expect(page.getByText('当前选定 · 已冻结', { exact: true })).toBeVisible()
    await expect(page.getByRole('button', { name: /编辑本区|保存种子|确认项目种子/u })).toHaveCount(0)
    const otherCandidates = page.getByText('其他候选（只读）', { exact: true })
    await otherCandidates.click()
    await expect(page.getByText('山河夜巡', { exact: true })).toBeVisible()

    await page.getByRole('link', { name: '创作契约', exact: true }).click()
    await expect(page.getByRole('heading', { name: '本书创作契约', exact: true })).toBeVisible()

    const engine = await openContractSection(page, 'contract-section-engine')
    await engine.locator('label').filter({ hasText: '渠道定位标识' }).locator('input').fill('男频长篇')
    await engine.locator('label').filter({ hasText: '题材定位标识' }).locator('input').fill('东方玄幻')
    const engineGenerate = waitForWrite(page, 'POST', /\/api\/projects\/[^/]+\/story-engine-batches$/u)
    await engine.getByRole('button', { name: '生成三套方案', exact: true }).click()
    expect((await engineGenerate).status()).toBe(201)
    await engine.getByRole('radio', { name: /山河重建/u }).click()
    const engineSave = waitForWrite(page, 'PUT', /\/api\/projects\/[^/]+\/contract-draft$/u)
    await engine.getByRole('button', { name: '保存本节', exact: true }).click()
    expect((await engineSave).status()).toBe(200)

    const style = await openContractSection(page, 'contract-section-style')
    await expect(style.getByRole('button', { name: '设为主风格', exact: true }).first()).toBeVisible()
    await style.getByRole('button', { name: '设为主风格', exact: true }).first().click()
    const styleSave = waitForWrite(page, 'PUT', /\/api\/projects\/[^/]+\/contract-draft$/u)
    await style.getByRole('button', { name: '保存本节', exact: true }).click()
    const styleSaveResponse = await styleSave
    expect(styleSaveResponse.status()).toBe(200)
    const styleDraft = await styleSaveResponse.json()
    const selectedStyleIdentity = styleDraft.draft.primaryStyleRef

    const assets = await openContractSection(page, 'contract-section-assets')
    const experienceCatalog = await readPublicApi(page, '/api/assets/experience-cards')
    const matchingCards = experienceCatalog.filter(card => card.title === '目标旁边放私人成本')
    expect(matchingCards).toHaveLength(1)
    const selectedExperienceIdentity = {
      id: matchingCards[0].id,
      revision: matchingCards[0].revision,
      contentHash: matchingCards[0].contentHash,
    }
    const experienceLibrary = assets.locator('label.library-selector').filter({ hasText: '完整经验库' })
    await chooseVisibleSelectOption(page, experienceLibrary, '目标旁边放私人成本')
    await expect(assets.locator('.selection-ledger')).toContainText('目标旁边放私人成本 · r1')
    const assetsSave = waitForWrite(page, 'PUT', /\/api\/projects\/[^/]+\/contract-draft$/u)
    await assets.getByRole('button', { name: '保存本节', exact: true }).click()
    expect((await assetsSave).status()).toBe(200)

    const capacity = await openContractSection(page, 'contract-section-capacity')
    await capacity.locator('label').filter({ hasText: '目标总字数' }).locator('input').fill('2400000')
    await capacity.locator('label').filter({ hasText: '预计卷数' }).locator('input').fill('24')
    await capacity.locator('label').filter({ hasText: '预计章节数' }).locator('input').fill('720')
    await capacity.locator('label').filter({ hasText: '下限' }).locator('input').fill('2800')
    await capacity.locator('label').filter({ hasText: '上限' }).locator('input').fill('4200')
    await capacity.locator('label').filter({ hasText: '作者备注' }).locator('textarea').fill('以人物选择推动每卷秩序升级，保持长线伏笔可回收。')
    const capacitySave = waitForWrite(page, 'PUT', /\/api\/projects\/[^/]+\/contract-draft$/u)
    await capacity.getByRole('button', { name: '保存本节', exact: true }).click()
    expect((await capacitySave).status()).toBe(200)

    const prohibitions = await openContractSection(page, 'contract-section-prohibitions')
    await prohibitions.locator('label').filter({ hasText: '禁止方向' }).locator('textarea').fill('不写无代价升级\n不以旁白替代人物行动')
    const prohibitionSave = waitForWrite(page, 'PUT', /\/api\/projects\/[^/]+\/contract-draft$/u)
    await prohibitions.getByRole('button', { name: '保存本节', exact: true }).click()
    expect((await prohibitionSave).status()).toBe(200)

    const previewResponse = waitForWrite(page, 'POST', /\/api\/projects\/[^/]+\/contracts\/preview$/u)
    await page.getByRole('navigation', { name: '文档章节' }).getByRole('button', { name: /完整预览/u }).click()
    const preview = section(page, 'contract-section-preview')
    const previewHttpResponse = await previewResponse
    expect(previewHttpResponse.status()).toBe(200)
    const expectedConfirmedContract = await previewHttpResponse.json()
    await expect(preview.getByText('服务器允许签印', { exact: true })).toBeVisible()
    await preview.getByRole('button', { name: '核对并签印完整契约', exact: true }).click()
    const contractDialog = page.getByRole('dialog', { name: '确认签印这份完整创作契约', exact: true })
    const contractConfirm = waitForWrite(page, 'POST', /\/api\/projects\/[^/]+\/contracts\/confirm$/u)
    await contractDialog.getByRole('button', { name: '一次确认完整契约', exact: true }).click()
    expect((await contractConfirm).status()).toBe(201)
    await expect(page.getByText('已签印 · 第 1 版', { exact: true }).first()).toBeVisible()

    await page.getByRole('link', { name: '创作圣经', exact: true }).click()
    await expect(page.getByRole('heading', { name: 'P0-D 创作地基验收 · 创作圣经', exact: true })).toBeVisible()
    const beforeWhole = await readBibleDraft(page)
    const wholeProposal = waitForWrite(page, 'POST', /\/api\/projects\/[^/]+\/bible\/proposals$/u)
    await page.getByRole('button', { name: 'AI 生成初稿', exact: true }).click()
    expect((await wholeProposal).status()).toBe(200)
    const wholeDialog = page.getByRole('dialog', { name: '完整创作圣经建议对照', exact: true })
    await expect(wholeDialog.getByText('采纳前不会改动草稿', { exact: true })).toBeVisible()
    expect(await readBibleDraft(page)).toEqual(beforeWhole)
    await wholeDialog.getByRole('button', { name: '采纳建议', exact: true }).click()
    const wholeSave = waitForWrite(page, 'PUT', /\/api\/projects\/[^/]+\/bible\/draft$/u)
    await page.getByRole('button', { name: '手动保存', exact: true }).click()
    expect((await wholeSave).status()).toBe(200)
    const afterWholeSave = await readBibleDraft(page)
    expect(afterWholeSave).not.toEqual(beforeWhole)
    expect(afterWholeSave.draftVersion).toBe(1)

    const beforeSection = await readBibleDraft(page)
    const sectionProposal = waitForWrite(page, 'POST', /\/api\/projects\/[^/]+\/bible\/proposals$/u)
    await page.getByRole('button', { name: 'AI 补充/重写本区', exact: true }).click()
    expect((await sectionProposal).status()).toBe(200)
    const premiseDialog = page.getByRole('dialog', { name: '作品承诺建议对照', exact: true })
    expect(await readBibleDraft(page)).toEqual(beforeSection)
    await premiseDialog.getByRole('button', { name: '采纳建议', exact: true }).click()
    const sectionSave = waitForWrite(page, 'PUT', /\/api\/projects\/[^/]+\/bible\/draft$/u)
    await page.getByRole('button', { name: '手动保存', exact: true }).click()
    expect((await sectionSave).status()).toBe(200)
    const afterSectionSave = await readBibleDraft(page)
    expect(afterSectionSave.draftVersion).toBe(2)
    expect(afterSectionSave.contentHash).not.toBe(afterWholeSave.contentHash)

    await page.getByRole('button', { name: '预览并确认', exact: true }).click()
    const bibleDialog = page.getByRole('dialog', { name: '确认创作圣经', exact: true })
    const bibleConfirm = waitForWrite(page, 'POST', /\/api\/projects\/[^/]+\/bible\/confirm$/u)
    await bibleDialog.getByRole('button', { name: '确认签印', exact: true }).click()
    expect((await bibleConfirm).status()).toBe(201)
    await expect(page.getByText('已确认，作为项目永久基线。', { exact: true })).toBeVisible()

    await page.waitForLoadState('networkidle')
    await page.reload()
    const finalBible = page.getByRole('article', { name: '创作圣经完整文档' })
    for (const [key, values] of Object.entries(FINAL_BIBLE_CONTENT)) {
      await expectVisibleContent(finalBible.locator(`#bible-section-${key}`), values)
    }
    await expectReadOnlyDocument(page, BIBLE_WRITE_BUTTONS)

    await page.goto(`/projects/${PROJECT_ID}/contract`)
    await page.waitForLoadState('networkidle')
    await page.reload()
    await expectVisibleContent(page.getByLabel('签印时冻结的创作种子，只读摘要'), [
      '典镇山河',
      '守典人沈砚从一座被舆图抹去的县城起步，以公开规则重建失序山河。',
      '东方玄幻',
    ])
    await expectVisibleContent(section(page, 'contract-section-engine'), ['每卷修复一层公共秩序，同时揭开残典来源。'])
    await expectVisibleContent(section(page, 'contract-section-capacity'), ['以人物选择推动每卷秩序升级，保持长线伏笔可回收。'])
    await expectVisibleContent(section(page, 'contract-section-assets'), ['1 张', '已冻结引用 · R1'])
    await expectVisibleContent(section(page, 'contract-section-style'), [
      '已冻结引用 · R1',
      '读者在长期冷压与不可逆失去中看见人物逐渐认清处境，并因他明知代价仍选择反抗而受到震动。',
    ])
    await expectVisibleContent(section(page, 'contract-section-prohibitions'), ['不写无代价升级；不以旁白替代人物行动'])
    await expectVisibleContent(section(page, 'contract-section-preview'), [
      '县城一夜从王朝舆图上消失，只有沈砚手中的残典仍记得它。',
      '天下建立可公开校验的新典制。',
    ])
    const confirmedContract = await readPublicApi(page, `/api/projects/${PROJECT_ID}/contracts/head`)
    expectCompleteConfirmedContract(
      confirmedContract,
      expectedConfirmedContract,
      selectedExperienceIdentity,
      selectedStyleIdentity,
    )
    await expectReadOnlyDocument(page, CONTRACT_WRITE_BUTTONS)

    await page.goto(`/projects/${PROJECT_ID}/seeds`)
    await page.waitForLoadState('networkidle')
    await page.reload()
    const finalSeed = page.getByRole('article', { name: '项目种子完整文档' })
    await expect(finalSeed).toBeVisible()
    for (const [key, values] of Object.entries(FINAL_SEED_CONTENT)) {
      await expectVisibleContent(section(page, `seed-${key}`), values)
    }
    await expectReadOnlyDocument(page, SEED_WRITE_BUTTONS)

    const scrollState = await page.locator('#main-content').evaluate(element => {
      element.scrollTop = element.scrollHeight
      return { scrollable: element.scrollHeight > element.clientHeight, top: element.scrollTop }
    })
    expect(scrollState.scrollable).toBe(true)
    expect(scrollState.top).toBeGreaterThan(0)
    await page.setViewportSize({ width: 360, height: 800 })
    await page.waitForLoadState('networkidle')
    await page.reload()
    await expectNoHorizontalOverflow(page)
  } catch (failure) {
    bodyFailure = failure
  } finally {
    try {
      const evidence = await runtime.finish()
      expect(publicRuntimeDiagnostic(evidence).requestFailures).toEqual([])
      expect(assertRuntimeEvidenceHealthy(evidence)).toMatchObject({
        healthy: true,
        networkAccess: { forbiddenRequestCount: 0, forbiddenResponseCount: 0 },
      })
      expect(SENSITIVE_VALUES.length).toBeGreaterThan(0)
      expect(scanRuntimeEvidence(evidence, SENSITIVE_VALUES).matchCount).toBe(0)
      assertExactWrites(evidence, [
        { method: 'PUT', path: /\/api\/projects\/[^/]+\/seeds\/[^/]+$/u, count: 1, statuses: [200] },
        { method: 'PUT', path: /\/api\/projects\/[^/]+\/selected-seed$/u, count: 1, statuses: [200] },
        { method: 'POST', path: /\/api\/projects\/[^/]+\/story-engine-batches$/u, count: 1, statuses: [201] },
        { method: 'POST', path: /\/api\/projects\/[^/]+\/asset-recommendations$/u, count: 2, statuses: [200] },
        { method: 'PUT', path: /\/api\/projects\/[^/]+\/contract-draft$/u, count: 5, statuses: [200] },
        { method: 'POST', path: /\/api\/projects\/[^/]+\/contracts\/preview$/u, count: 1, statuses: [200] },
        { method: 'POST', path: /\/api\/projects\/[^/]+\/contracts\/confirm$/u, count: 1, statuses: [201] },
        { method: 'POST', path: /\/api\/projects\/[^/]+\/bible\/proposals$/u, count: 2, statuses: [200] },
        { method: 'PUT', path: /\/api\/projects\/[^/]+\/bible\/draft$/u, count: 2, statuses: [200] },
        { method: 'POST', path: /\/api\/projects\/[^/]+\/bible\/confirm$/u, count: 1, statuses: [201] },
      ])
    } catch (failure) {
      auditFailure = failure
    }
  }

  if (bodyFailure) throw bodyFailure
  if (auditFailure) throw auditFailure
})
