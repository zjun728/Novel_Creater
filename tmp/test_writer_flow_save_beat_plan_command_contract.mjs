import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { pathToFileURL } from 'node:url'

const repoRoot = process.cwd()
const modulePath = path.join(repoRoot, 'frontend/src/application/writer-flow/save-beat-plan-command.js')
const draftCommandPath = path.join(repoRoot, 'frontend/src/application/writer-flow/draft-generation-command.js')
const writerViewPath = path.join(repoRoot, 'frontend/src/views/WriterView.vue')
const { runSaveBeatPlanCommand } = await import(pathToFileURL(modulePath).href)

function createHarness(overrides = {}) {
  const calls = []
  const state = {
    beatPlanText: '  细纲内容  ',
    beatPlanSavedText: '',
    snapshot: { stage: 'existing' },
  }

  const api = {
    showMessage: true,
    getBeatPlanText: () => state.beatPlanText,
    getBeatPlanStageSnapshot: () => state.snapshot,
    getProjectId: () => 'project-1',
    getChapterNum: () => 12,
    ensureCurrentChapterEditable: (label) => {
      calls.push(['editable', label])
      return true
    },
    ensureStoryBlockReady: async (label) => {
      calls.push(['storyBlockReady', label])
      return { id: 'block-1' }
    },
    captureCurrentBlockStageSnapshot: (block) => {
      calls.push(['capture', block.id])
      return { stage: 'captured', blockId: block.id }
    },
    setBeatPlanStageSnapshot: (snapshot) => {
      calls.push(['setSnapshot', snapshot.blockId])
      state.snapshot = snapshot
    },
    saveChapterBeatPlan: async (...args) => {
      calls.push(['save', ...args])
    },
    buildBeatPlanStoryBlockMetadata: () => {
      calls.push(['metadata'])
      return { snapshot: state.snapshot }
    },
    setBeatPlanText: (content) => {
      calls.push(['setText', content])
      state.beatPlanText = content
    },
    setBeatPlanSavedText: (content) => {
      calls.push(['setSavedText', content])
      state.beatPlanSavedText = content
    },
    warning: (text) => calls.push(['warning', text]),
    success: (text) => calls.push(['success', text]),
    error: (text) => calls.push(['error', text]),
  }

  Object.assign(api, overrides)
  return { api, calls, state }
}

{
  const { api, calls } = createHarness({ getBeatPlanText: () => '   ' })
  const result = await runSaveBeatPlanCommand(api)
  assert.equal(result, false)
  assert.deepEqual(calls, [
    ['editable', '保存小纲'],
    ['warning', '请先生成或填写本章小纲'],
  ])
}

{
  const { api, calls } = createHarness({
    ensureCurrentChapterEditable: (label) => {
      calls.push(['editable', label])
      return false
    },
  })
  const result = await runSaveBeatPlanCommand(api)
  assert.equal(result, false)
  assert.deepEqual(calls, [['editable', '保存小纲']])
}

{
  const { api, calls, state } = createHarness({
    getBeatPlanStageSnapshot: () => state.snapshot,
    ensureStoryBlockReady: async (label) => {
      calls.push(['storyBlockReady', label])
      return null
    },
  })
  state.snapshot = null
  const result = await runSaveBeatPlanCommand(api)
  assert.equal(result, false)
  assert.deepEqual(calls, [
    ['editable', '保存小纲'],
    ['storyBlockReady', '保存小纲'],
  ])
}

{
  const { api, calls, state } = createHarness({
    getBeatPlanStageSnapshot: () => state.snapshot,
  })
  state.snapshot = null
  const result = await runSaveBeatPlanCommand(api)
  assert.equal(result, true)
  assert.deepEqual(calls.slice(0, 5), [
    ['editable', '保存小纲'],
    ['storyBlockReady', '保存小纲'],
    ['capture', 'block-1'],
    ['setSnapshot', 'block-1'],
    ['metadata'],
  ])
  assert.equal(calls[5][0], 'save')
}

{
  const { api, calls, state } = createHarness()
  const result = await runSaveBeatPlanCommand(api)
  assert.equal(result, true)
  assert.equal(state.beatPlanText, '细纲内容')
  assert.equal(state.beatPlanSavedText, '细纲内容')
  assert.deepEqual(calls, [
    ['editable', '保存小纲'],
    ['metadata'],
    ['save', 'project-1', 12, '细纲内容', { snapshot: { stage: 'existing' } }],
    ['setText', '细纲内容'],
    ['setSavedText', '细纲内容'],
    ['success', '本章小纲已保存'],
  ])
}

{
  const { api, calls } = createHarness({ showMessage: false })
  const result = await runSaveBeatPlanCommand(api)
  assert.equal(result, true)
  assert.equal(calls.some((call) => call[0] === 'success'), false)
}

{
  const { api, calls } = createHarness({
    saveChapterBeatPlan: async () => {
      calls.push(['save'])
      throw new Error('boom')
    },
  })
  const result = await runSaveBeatPlanCommand(api)
  assert.equal(result, false)
  assert.deepEqual(calls.at(-1), ['error', '保存小纲失败：boom'])
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
    /generateChapter/,
    /ensureBeatPlan/,
  ]
  for (const pattern of forbidden) {
    assert.equal(pattern.test(source), false, `forbidden pattern found: ${pattern}`)
  }
}

{
  const source = fs.readFileSync(writerViewPath, 'utf8')
  const draftSource = fs.readFileSync(draftCommandPath, 'utf8')
  assert.match(source, /runSaveBeatPlanCommand/)
  assert.match(source, /async function saveCurrentBeatPlan\s*\(\s*showMessage\s*=\s*true\s*\)/)
  assert.match(
    source,
    /async function saveCurrentBeatPlan\s*\(\s*showMessage\s*=\s*true\s*\)\s*{\s*return runSaveBeatPlanCommand\(/,
  )
  assert.match(source, /@\/application\/writer-flow\/draft-generation-command/)
  assert.match(source, /runGenerateFromBeatPlanCommand/)
  assert.match(draftSource, /saveCurrentBeatPlan\(false\)/)
  assert.match(draftSource, /const confirmedPlan\s*=\s*String\(getBeatPlanText\(\) \|\| ''\)\.trim\(\)/)
  assert.ok(
    draftSource.indexOf('const confirmedPlan') <
      draftSource.indexOf('saveCurrentBeatPlan(false)'),
    'draft generation command must read confirmedPlan before saveCurrentBeatPlan(false)',
  )
}

console.log('writer-flow save beat plan command contract passed')
