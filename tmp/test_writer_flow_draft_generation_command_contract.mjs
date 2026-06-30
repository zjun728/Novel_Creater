import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { pathToFileURL } from 'node:url'

const repoRoot = process.cwd()
const modulePath = path.join(repoRoot, 'frontend/src/application/writer-flow/draft-generation-command.js')
const writerViewPath = path.join(repoRoot, 'frontend/src/views/WriterView.vue')
const { runGenerateFromBeatPlanCommand } = await import(pathToFileURL(modulePath).href)

function createHarness(overrides = {}) {
  const calls = []
  const state = {
    intent: 'single',
    beatPlanText: '  确认后的小纲  ',
    showBeatPlanModal: true,
  }

  const api = {
    getBeatPlanIntent: () => state.intent,
    getBeatPlanText: () => state.beatPlanText,
    ensureCurrentChapterEditable: (label) => {
      calls.push(['editable', label])
      return true
    },
    warning: (text) => calls.push(['warning', text]),
    saveCurrentBeatPlan: async (showMessage) => {
      calls.push(['saveCurrentBeatPlan', showMessage])
      return true
    },
    setShowBeatPlanModal: (value) => {
      calls.push(['setShowBeatPlanModal', value])
      state.showBeatPlanModal = value
    },
    generateMultiVariantsFromPlan: async (plan) => calls.push(['generateMultiVariantsFromPlan', plan]),
    openCompareWithPlan: async (plan) => calls.push(['openCompareWithPlan', plan]),
    generateChapterFromPlan: async (plan) => calls.push(['generateChapterFromPlan', plan]),
  }

  Object.assign(state, overrides.state || {})
  Object.assign(api, overrides.api || {})
  return { api, calls, state }
}

{
  const { api, calls } = createHarness({
    api: {
      ensureCurrentChapterEditable: (label) => {
        calls.push(['editable', label])
        return false
      },
    },
  })
  const result = await runGenerateFromBeatPlanCommand(api)
  assert.deepEqual(result, { ok: false, code: 'currentChapterNotEditable' })
  assert.deepEqual(calls, [['editable', '正文生成']])
}

{
  const { api, calls } = createHarness({ state: { beatPlanText: '   ' } })
  const result = await runGenerateFromBeatPlanCommand(api)
  assert.deepEqual(result, { ok: false, code: 'emptyBeatPlan' })
  assert.deepEqual(calls, [
    ['editable', '正文生成'],
    ['warning', '请先生成或填写本章小纲'],
  ])
}

{
  const { api, calls } = createHarness({
    api: {
      saveCurrentBeatPlan: async (showMessage) => {
        calls.push(['saveCurrentBeatPlan', showMessage])
        return false
      },
    },
  })
  const result = await runGenerateFromBeatPlanCommand(api)
  assert.deepEqual(result, { ok: false, code: 'beatPlanSaveFailed' })
  assert.deepEqual(calls, [
    ['editable', '正文生成'],
    ['saveCurrentBeatPlan', false],
  ])
}

{
  const { api, calls, state } = createHarness()
  const result = await runGenerateFromBeatPlanCommand(api)
  assert.deepEqual(result, { ok: true, code: 'singleDraftStarted', plan: '确认后的小纲' })
  assert.equal(state.showBeatPlanModal, false)
  assert.deepEqual(calls, [
    ['editable', '正文生成'],
    ['saveCurrentBeatPlan', false],
    ['setShowBeatPlanModal', false],
    ['generateChapterFromPlan', '确认后的小纲'],
  ])
}

{
  const { api, calls } = createHarness({ state: { intent: 'multi' } })
  const result = await runGenerateFromBeatPlanCommand(api)
  assert.deepEqual(result, { ok: true, code: 'multiVariantsStarted', plan: '确认后的小纲' })
  assert.deepEqual(calls, [
    ['editable', '多候选生成'],
    ['saveCurrentBeatPlan', false],
    ['setShowBeatPlanModal', false],
    ['generateMultiVariantsFromPlan', '确认后的小纲'],
  ])
}

{
  const { api, calls } = createHarness({ state: { intent: 'compare' } })
  const result = await runGenerateFromBeatPlanCommand(api)
  assert.deepEqual(result, { ok: true, code: 'compareStarted', plan: '确认后的小纲' })
  assert.deepEqual(calls, [
    ['editable', '多模型对比'],
    ['saveCurrentBeatPlan', false],
    ['setShowBeatPlanModal', false],
    ['openCompareWithPlan', '确认后的小纲'],
  ])
}

{
  const source = fs.readFileSync(modulePath, 'utf8')
  const forbidden = [
    /from ['"]vue['"]/,
    /from ['"].*stores/,
    /from ['"].*api/,
    /from ['"].*router/,
    /naive-ui/,
    /prompts/,
    /chatCompletion/,
    /localStorage/,
    /sessionStorage/,
    /\bwindow\b/,
    /\bdocument\b/,
    /writerStore/,
    /generateChapter\(/,
    /generateMultiVariants\(/,
  ]
  for (const pattern of forbidden) {
    assert.equal(pattern.test(source), false, `forbidden pattern found: ${pattern}`)
  }
}

{
  const source = fs.readFileSync(writerViewPath, 'utf8')
  assert.match(source, /@\/application\/writer-flow\/draft-generation-command/)
  assert.match(source, /runGenerateFromBeatPlanCommand/)
  assert.match(source, /async function handleGenerateFromBeatPlan\s*\(\s*\)/)
  assert.match(
    source,
    /async function handleGenerateFromBeatPlan\s*\(\s*\)\s*{\s*return runGenerateFromBeatPlanCommand\(/,
  )
  assert.match(source, /generateChapterFromPlan/)
  assert.match(source, /generateMultiVariantsFromPlan/)
  assert.match(source, /openCompareWithPlan/)
  assert.match(source, /saveCurrentBeatPlan/)
}

console.log('writer-flow draft generation command contract passed')
