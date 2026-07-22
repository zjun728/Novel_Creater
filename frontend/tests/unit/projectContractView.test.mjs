import assert from 'node:assert/strict'
import { access, readFile } from 'node:fs/promises'
import test from 'node:test'

import { api } from '../../src/api/db/client.js'

const file = relative => new URL(`../../${relative}`, import.meta.url)
const source = relative => readFile(file(relative), 'utf8')

function jsonResponse(value = {}) {
  return new Response(JSON.stringify(value), {
    status: 200,
    headers: { 'content-type': 'application/json' },
  })
}

async function captureRequests(run) {
  const originalFetch = global.fetch
  const calls = []
  global.fetch = async (url, options = {}) => {
    calls.push({ url: String(url), options })
    return jsonResponse()
  }
  try {
    await run()
    return calls
  } finally {
    global.fetch = originalFetch
  }
}

function requestBody(call) {
  return call.options.body == null ? undefined : JSON.parse(call.options.body)
}

test('formal client posts style trials and revision-specific clone commands to backend-only routes', async () => {
  assert.equal(typeof api.styleTrials?.generate, 'function')
  const command = {
    selectionRevision: 3,
    engineOptionId: 'engine-1',
    engineHash: 'a'.repeat(64),
    primaryStyleRevisionId: 'style-primary',
    primaryStyleHash: 'b'.repeat(64),
    secondaryStyleRevisionId: null,
    secondaryStyleHash: null,
    authorScenario: '主角必须在救人和守住秘密之间做选择。',
    idempotencyKey: 'i'.repeat(64),
    apiKey: 'must-not-send',
    prompt: 'must-not-send',
  }
  const calls = await captureRequests(async () => {
    await api.styleTrials.generate('project-1', command)
    await api.contracts.clone('project-1', 4)
  })

  assert.deepEqual(calls.map(call => [call.options.method, new URL(call.url).pathname]), [
    ['POST', '/api/projects/project-1/style-trials'],
    ['POST', '/api/projects/project-1/contracts/4/clone'],
  ])
  assert.deepEqual(requestBody(calls[0]), {
    selectionRevision: 3,
    engineOptionId: 'engine-1',
    engineHash: 'a'.repeat(64),
    primaryStyleRevisionId: 'style-primary',
    primaryStyleHash: 'b'.repeat(64),
    secondaryStyleRevisionId: null,
    secondaryStyleHash: null,
    authorScenario: '主角必须在救人和守住秘密之间做选择。',
    idempotencyKey: 'i'.repeat(64),
  })
  assert.equal(requestBody(calls[1]), undefined)
  assert.equal(JSON.stringify(calls).includes('must-not-send'), false)
})

test('contract page owns project states and keeps the selected seed read-only', async () => {
  const [view, wizard] = await Promise.all([
    source('src/views/ProjectContractView.vue'),
    source('src/components/project/CreationContractWizard.vue'),
  ])

  assert.match(view, /useRouteProject/)
  assert.match(view, /CreationContractWizard/)
  assert.match(view, /routeProject\.state\.value === 'active'/)
  assert.match(view, /routeProject\.state\.value === 'archived'/)
  assert.match(view, /:read-only="true"/)
  assert.match(wizard, /seedStore\.selectedSeed/)
  assert.match(wizard, /已选创作种子/)
  assert.match(wizard, /只读/)
  assert.match(wizard, /projectSeedsPath/)
  assert.match(wizard, /前往种子/)
  assert.doesNotMatch(wizard, /selectSeed|SeedSelectionStep/)
})

test('wizard is exactly five formal steps and the retired seed step is deleted', async () => {
  const wizard = await source('src/components/project/CreationContractWizard.vue')
  const expected = ['故事发动机', '风格契约', '素材范围', '容量约定', '预览并确认']

  for (const label of expected) assert.match(wizard, new RegExp(label))
  assert.match(wizard, /StoryEngineStep/)
  assert.match(wizard, /StyleSelectionStep/)
  assert.match(wizard, /AssetScopeStep/)
  assert.match(wizard, /CapacityStep/)
  assert.match(wizard, /ContractPreviewStep/)
  assert.match(wizard, /repeat\(5/)
  await assert.rejects(
    access(file('src/components/project/contract/SeedSelectionStep.vue')),
    error => error?.code === 'ENOENT',
  )
})

test('manual story engines use named fields without JSON or channel and genre assumptions', async () => {
  const engine = await source('src/components/project/contract/StoryEngineStep.vue')
  for (const label of ['方案名称', '故事承诺', '主角欲望', '持续压力', '成长方向', '冲突循环', '优势与代价', '结局锚点']) {
    assert.match(engine, new RegExp(label))
  }
  assert.doesNotMatch(engine, /manualJson|JSON\.parse|高级手动 JSON|qidian-qq|['"]玄幻['"]/)
  assert.match(engine, /createManualEngineBatch/)
  assert.match(engine, /保存草稿并继续/)
})

test('style trial panel is temporary, shows safe provider identity, and never selects a style', async () => {
  const [style, trial] = await Promise.all([
    source('src/components/project/contract/StyleSelectionStep.vue'),
    source('src/components/project/contract/StyleTrialPanel.vue'),
  ])
  assert.match(style, /StyleTrialPanel/)
  assert.match(style, /完整应用示例|完整风格样例/)
  assert.match(trial, /runStyleTrial/)
  assert.match(trial, /loading|试写中/)
  assert.match(trial, /failed|失败/)
  assert.match(trial, /succeeded|已完成/)
  assert.match(trial, /providerType/)
  assert.match(trial, /modelName/)
  assert.match(trial, /临时试写/)
  assert.match(trial, /不会自动选择/)
  assert.doesNotMatch(trial, /localStorage|chatCompletion|candidate|Canon|setPrimary/)
})

test('asset scope starts empty and saves explicit fragment ranges within a visible budget', async () => {
  const assets = await source('src/components/project/contract/AssetScopeStep.vue')
  assert.doesNotMatch(assets, /selectedExperienceIds\.value\s*=\s*uniqueIds\(recommendedCards/)
  assert.match(assets, /selectedExperienceIds\.value\s*=\s*\[\]/)
  assert.match(assets, /selectedCorpusFragments/)
  assert.match(assets, /fragmentHash/)
  assert.match(assets, /chapterCharStart/)
  assert.match(assets, /chapterCharEnd/)
  assert.match(assets, /contentHash/)
  assert.match(assets, /4000/)
  assert.match(assets, /完整经验库/)
  assert.match(assets, /完整语料库/)
  assert.match(assets, /当前没有.*推荐/)
  assert.match(assets, /fragmentPage\.value\?\.nextCursor/)
  assert.match(assets, /loadMoreFragments/)
})

test('capacity step captures all formal length and author-direction fields', async () => {
  const [capacity, preview] = await Promise.all([
    source('src/components/project/contract/CapacityStep.vue'),
    source('src/components/project/contract/ContractPreviewStep.vue'),
  ])
  for (const field of [
    'targetTotalWords',
    'expectedVolumeCount',
    'expectedChapterCount',
    'chapterWordRangePreference',
    'prohibitedDirections',
    'authorNotes',
  ]) assert.match(capacity, new RegExp(field))
  assert.match(capacity, /保存草稿并继续/)
  assert.match(capacity, /aria-live="assertive"/)
  assert.match(preview, /返回容量约定/)
})

test('workspace guards unsaved edits, scopes its overlay, and focuses live errors', async () => {
  const files = await Promise.all([
    source('src/components/project/CreationContractWizard.vue'),
    source('src/components/project/contract/StoryEngineStep.vue'),
    source('src/components/project/contract/StyleSelectionStep.vue'),
    source('src/components/project/contract/AssetScopeStep.vue'),
    source('src/components/project/contract/CapacityStep.vue'),
    source('src/components/project/contract/ContractPreviewStep.vue'),
  ])
  const combined = files.join('\n')
  assert.match(combined, /onBeforeRouteLeave/)
  assert.match(combined, /beforeunload/)
  assert.match(combined, /hasUnsavedChanges/)
  assert.match(combined, /contract-operation-overlay/)
  assert.match(combined, /position:\s*absolute/)
  assert.doesNotMatch(combined, /contract-operation-overlay[^}]*position:\s*fixed/s)
  assert.match(combined, /aria-live="polite"/)
  assert.match(combined, /aria-live="assertive"/)
  assert.match(combined, /tabindex="-1"/)
  assert.match(combined, /\.focus\(/)
  assert.match(combined, /requiresReload/)
  assert.match(combined, /重新加载并核对/)
  assert.doesNotMatch(combined, /删除契约|重置契约|resetContract|deleteContract/)
})

test('history shows immutable pinned revisions and enables clone only for compatible generations', async () => {
  const [history, preview] = await Promise.all([
    source('src/components/project/contract/ContractHistoryDrawer.vue'),
    source('src/components/project/contract/ContractPreviewStep.vue'),
  ])
  assert.match(history, /loadHistory/)
  assert.match(history, /pinnedHistoricalRevision/)
  assert.match(history, /supersededReasons/)
  assert.match(history, /selectionRevision/)
  assert.match(history, /cloneRevision\([^)]*revision/)
  assert.match(history, /调整未来设计/)
  assert.match(history, /:disabled="[^"\n]*(superseded|canClone)/)
  assert.match(preview, /一次确认完整契约/)
  assert.match(preview, /不可覆盖|只读/)
  assert.doesNotMatch(`${history}\n${preview}`, /删除|重置/)
})
