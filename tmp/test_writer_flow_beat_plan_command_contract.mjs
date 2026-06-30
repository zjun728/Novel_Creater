import fs from 'node:fs'
import assert from 'node:assert/strict'

import {
  normalizeBeatPlanCommandOptions,
  shouldReuseExistingBeatPlan,
  runEnsureBeatPlanCommand
} from '../frontend/src/application/writer-flow/beat-plan-command.js'

assert.deepEqual(normalizeBeatPlanCommandOptions(), { persist: true })
assert.deepEqual(normalizeBeatPlanCommandOptions({ persist: false }), { persist: false })
assert.equal(shouldReuseExistingBeatPlan({ existingPlan: '  a  ', force: false }), true)
assert.equal(shouldReuseExistingBeatPlan({ existingPlan: '  a  ', force: true }), false)
assert.equal(shouldReuseExistingBeatPlan({ existingPlan: '   ', force: false }), false)

function makeCallbacks(overrides = {}) {
  const calls = []
  const state = {
    snapshot: overrides.beatPlanStageSnapshot || null,
    beatPlanText: '',
    savedText: ''
  }
  const callbacks = {
    ensureAiContextReady: async (name) => { calls.push(['ensureAiContextReady', name]); return true },
    ensureCurrentChapterEditable: (name) => { calls.push(['ensureCurrentChapterEditable', name]); return true },
    ensurePreviousChapterFinalized: async (name) => { calls.push(['ensurePreviousChapterFinalized', name]); return true },
    ensureNoPendingSettingChanges: async (name) => { calls.push(['ensureNoPendingSettingChanges', name]); return true },
    ensureNoPendingStoryMemory: async (name) => { calls.push(['ensureNoPendingStoryMemory', name]); return true },
    ensureCorrectionTasksAllowGeneration: async (name) => { calls.push(['ensureCorrectionTasksAllowGeneration', name]); return true },
    ensureStoryBlockReady: async (name) => { calls.push(['ensureStoryBlockReady', name]); return { id: 'block-1' } },
    captureCurrentBlockStageSnapshot: (block) => { calls.push(['captureCurrentBlockStageSnapshot', block.id]); return { storyBlockId: block.id, stageId: 'stage-1' } },
    setBeatPlanStageSnapshot: (snapshot) => { calls.push(['setBeatPlanStageSnapshot', snapshot]); state.snapshot = snapshot },
    buildBaseContext: () => { calls.push(['buildBaseContext']); return { base: true, chapterNum: 8 } },
    buildChaseLoopDiagnosticsForBeatPlan: () => { calls.push(['buildChaseLoopDiagnosticsForBeatPlan']); return { consecutiveChaseDominant: 0 } },
    generateChapterBeatPlan: async (...args) => { calls.push(['generateChapterBeatPlan', ...args]); return 'generated plan' },
    setBeatPlanText: (text) => { calls.push(['setBeatPlanText', text]); state.beatPlanText = text },
    saveChapterBeatPlan: async (...args) => { calls.push(['saveChapterBeatPlan', ...args]) },
    buildBeatPlanStoryBlockMetadata: () => { calls.push(['buildBeatPlanStoryBlockMetadata']); return { storyBlockId: state.snapshot?.storyBlockId || null } },
    setBeatPlanSavedText: (text) => { calls.push(['setBeatPlanSavedText', text]); state.savedText = text },
    ...overrides.callbacks
  }
  return { calls, state, callbacks }
}

let fixture = makeCallbacks({ beatPlanStageSnapshot: { storyBlockId: 'block-existing' } })
let result = await runEnsureBeatPlanCommand({
  projectId: 'p1',
  chapterNum: 8,
  existingPlan: ' existing plan ',
  beatPlanStageSnapshot: { storyBlockId: 'block-existing' },
  callbacks: fixture.callbacks
})
assert.equal(result.plan, 'existing plan')
assert.deepEqual(fixture.calls, [['ensureAiContextReady', '小纲生成']])

fixture = makeCallbacks()
result = await runEnsureBeatPlanCommand({
  projectId: 'p1',
  chapterNum: 8,
  existingPlan: ' existing plan ',
  beatPlanStageSnapshot: null,
  options: { persist: true },
  callbacks: fixture.callbacks
})
assert.equal(result.plan, 'existing plan')
assert.deepEqual(fixture.calls.map(call => call[0]), [
  'ensureAiContextReady',
  'ensureStoryBlockReady',
  'captureCurrentBlockStageSnapshot',
  'setBeatPlanStageSnapshot',
  'buildBeatPlanStoryBlockMetadata',
  'saveChapterBeatPlan',
  'setBeatPlanSavedText'
])
assert.equal(fixture.state.savedText, 'existing plan')

fixture = makeCallbacks({
  callbacks: {
    ensureAiContextReady: async (name) => { fixture.calls.push(['ensureAiContextReady', name]); return false }
  }
})
result = await runEnsureBeatPlanCommand({
  projectId: 'p1',
  chapterNum: 8,
  existingPlan: '',
  callbacks: fixture.callbacks
})
assert.equal(result.plan, '')
assert.deepEqual(fixture.calls, [['ensureAiContextReady', '小纲生成']])

fixture = makeCallbacks()
result = await runEnsureBeatPlanCommand({
  projectId: 'p1',
  chapterNum: 8,
  existingPlan: '',
  options: { persist: true },
  callbacks: fixture.callbacks
})
assert.equal(result.plan, 'generated plan')
assert.deepEqual(fixture.calls.map(call => call[0]), [
  'ensureAiContextReady',
  'ensureCurrentChapterEditable',
  'ensurePreviousChapterFinalized',
  'ensureNoPendingSettingChanges',
  'ensureNoPendingStoryMemory',
  'ensureCorrectionTasksAllowGeneration',
  'ensureStoryBlockReady',
  'captureCurrentBlockStageSnapshot',
  'setBeatPlanStageSnapshot',
  'buildBaseContext',
  'buildChaseLoopDiagnosticsForBeatPlan',
  'generateChapterBeatPlan',
  'setBeatPlanText',
  'buildBeatPlanStoryBlockMetadata',
  'saveChapterBeatPlan',
  'setBeatPlanSavedText'
])
const generateCall = fixture.calls.find(call => call[0] === 'generateChapterBeatPlan')
assert.equal(generateCall[1], 'p1')
assert.equal(generateCall[2], 8)
assert.deepEqual(generateCall[3], {
  base: true,
  chapterNum: 8,
  storyBlock: { id: 'block-1' },
  blockStageSnapshot: { storyBlockId: 'block-1', stageId: 'stage-1' },
  chaseLoopDiagnostics: { consecutiveChaseDominant: 0 }
})

fixture = makeCallbacks()
result = await runEnsureBeatPlanCommand({
  projectId: 'p1',
  chapterNum: 8,
  existingPlan: '',
  options: { persist: false },
  callbacks: fixture.callbacks
})
assert.equal(result.plan, 'generated plan')
assert.equal(fixture.calls.some(call => call[0] === 'saveChapterBeatPlan'), false)
assert.equal(fixture.calls.some(call => call[0] === 'setBeatPlanSavedText'), false)

const moduleSource = fs.readFileSync('frontend/src/application/writer-flow/beat-plan-command.js', 'utf8')
const forbiddenPurePatterns = [
  /from ['"]vue['"]/,
  /pinia/,
  /stores\//,
  /api\//,
  /router/,
  /naive/i,
  /prompts\//,
  /chatCompletion/,
  /localStorage|sessionStorage/,
  /\bwindow\b|\bdocument\b/
]
for (const pattern of forbiddenPurePatterns) {
  assert.equal(pattern.test(moduleSource), false, `beat plan command module must stay adapter-pure: ${pattern}`)
}

const writerViewSource = fs.readFileSync('frontend/src/views/WriterView.vue', 'utf8')
assert.match(writerViewSource, /@\/application\/writer-flow\/beat-plan-command/)
assert.match(writerViewSource, /async function ensureBeatPlan/)
assert.match(writerViewSource, /AI 小纲质量不足，已生成安全小纲，请审阅后再生成正文。/)
assert.match(writerViewSource, /result\.code === 'generatedPlan' && writerStore\.beatPlanQualityNotice\?\.source === 'local_safety_rebuild'/)
assert.match(writerViewSource, /async function handlePlanBeats/)
assert.match(writerViewSource, /async function handleRefreshBeatPlan/)
assert.match(writerViewSource, /async function handleGenerate/)
assert.match(writerViewSource, /runEnsureBeatPlanCommand/)

console.log('writer flow beat plan command contract passed')
