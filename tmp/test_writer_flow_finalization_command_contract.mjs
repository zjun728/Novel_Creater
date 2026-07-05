import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const commandSource = readFileSync('frontend/src/application/writer-flow/finalization-command.js', 'utf8')
const writerView = readFileSync('frontend/src/views/WriterView.vue', 'utf8')
const { runFinalizeChapterCommand } = await import('../frontend/src/application/writer-flow/finalization-command.js')

function callRecorder(name, impl = async () => undefined) {
  const calls = []
  const fn = async (...args) => {
    calls.push(args)
    return impl(...args)
  }
  fn.calls = calls
  fn.called = () => calls.length > 0
  fn.count = () => calls.length
  fn.last = () => calls[calls.length - 1]
  fn.nameForContract = name
  return fn
}

function extractFunctionBlock(source, signature) {
  const start = source.indexOf(signature)
  assert.notEqual(start, -1, `missing function signature: ${signature}`)
  const bodyStart = source.indexOf('{', start)
  assert.notEqual(bodyStart, -1, `missing function body: ${signature}`)
  let depth = 0
  for (let index = bodyStart; index < source.length; index += 1) {
    const char = source[index]
    if (char === '{') depth += 1
    if (char === '}') {
      depth -= 1
      if (depth === 0) return source.slice(start, index + 1)
    }
  }
  assert.fail(`unterminated function body: ${signature}`)
}

function createCommandInput(overrides = {}) {
  const calls = {}
  const add = (name, impl) => {
    calls[name] = callRecorder(name, impl)
    return calls[name]
  }
  const input = {
    projectId: 'project-1',
    chapterNum: 88,
    version: { id: 'version-1', content: '正文内容' },
    correctionTaskIds: ['task-1'],
    beginFinalizationRun: add('beginFinalizationRun', async () => ({ started: true, runKey: 'run-1', runId: 'run-id-1', finalizationId: 'fin-id-1' })),
    finalizeVersion: add('finalizeVersion'),
    finishLinkedCorrectionTasks: add('finishLinkedCorrectionTasks'),
    clearTempDraft: add('clearTempDraft'),
    processChapterFinalization: add('processChapterFinalization', async () => ({
      facts: [{ id: 'fact-1' }, { id: 'fact-2' }],
      settingChanges: [{ id: 'setting-1' }],
      errors: []
    })),
    loadContextData: add('loadContextData'),
    performStoryBlockReviewAfterFinalize: add('performStoryBlockReviewAfterFinalize'),
    rerouteOutlineAfterFinalization: add('rerouteOutlineAfterFinalization'),
    buildRerouteContext: add('buildRerouteContext', async () => ({ context: true })),
    markFinalizationFailure: add('markFinalizationFailure'),
    endFinalizationRun: add('endFinalizationRun'),
    onVersionFinalized: add('onVersionFinalized'),
    onMemoryProcessed: add('onMemoryProcessed'),
    onStoryBlockReviewFailure: add('onStoryBlockReviewFailure'),
    onRerouteWarning: add('onRerouteWarning'),
    onPostFinalizeFailure: add('onPostFinalizeFailure'),
    onLinkedCorrectionTaskFailure: add('onLinkedCorrectionTaskFailure'),
    onClearTempDraftFailure: add('onClearTempDraftFailure'),
    saveDurableFinalizationMarker: add('saveDurableFinalizationMarker', async (_chapterNum, marker) => ({ ...marker, id: 'durable-marker-1' })),
    upsertDurableFinalizationMarker: add('upsertDurableFinalizationMarker')
  }
  Object.assign(input, overrides)
  return { input, calls }
}

function expectedEndOptions(keepPending) {
  return {
    keepPending,
    commitStatus: keepPending ? 'failed_after_chapter_commit' : 'pending',
    sourceVersionId: 'version-1',
    runId: 'run-id-1',
    finalizationId: 'fin-id-1'
  }
}

assert.match(commandSource, /export async function runFinalizeChapterCommand/, 'command must export runFinalizeChapterCommand')
assert.doesNotMatch(
  commandSource,
  /from ['"]@\/stores|from ['"]@\/api|chatCompletion|from ['"].*prompts|localStorage|from ['"]vue|use[A-Z][A-Za-z]+Store|useDialog|useMessage|naive-ui/,
  'finalization command must only use injected dependencies and must not import stores/api/chat/prompts/localStorage/Vue/UI'
)

assert.match(writerView, /runFinalizeChapterCommand/, 'WriterView.performFinalize must call the command')
const performFinalizeBlock = extractFunctionBlock(writerView, 'async function performFinalize(version)')
assert.match(performFinalizeBlock, /runFinalizeChapterCommand/, 'performFinalize must delegate post-preflight orchestration to command')
assert.doesNotMatch(
  performFinalizeBlock,
  /await\s+writerStore\.finalizeVersion|const\s+results\s*=\s*await\s+memoryStore\.processChapterFinalization|await\s+performStoryBlockReviewAfterFinalize|await\s+novelStore\.rerouteOutlineAfterFinalization/,
  'WriterView must not directly execute the full finalization state machine after extraction'
)
assert.doesNotMatch(
  commandSource,
  /auditChapter|ensureChapterAboveHardWordMinBeforeFinalize|ensureCorrectionTasksAllowGeneration/,
  'preflight audit and hard gates must remain outside the finalization command'
)

{
  const { input, calls } = createCommandInput({
    beginFinalizationRun: callRecorder('beginFinalizationRun', async () => ({ started: false, reason: 'pending_marker', runKey: 'blocked-run' }))
  })
  const result = await runFinalizeChapterCommand(input)
  assert.equal(result.ok, false)
  assert.equal(result.code, 'finalization_run_blocked')
  assert.equal(result.reason, 'pending_marker')
  for (const name of [
    'finalizeVersion',
    'processChapterFinalization',
    'performStoryBlockReviewAfterFinalize',
    'rerouteOutlineAfterFinalization',
    'endFinalizationRun'
  ]) {
    assert.equal(calls[name].count(), 0, `blocked begin must not call ${name}`)
  }
}

{
  const finalizeError = new Error('version store failed')
  const { input, calls } = createCommandInput({
    finalizeVersion: callRecorder('finalizeVersion', async () => { throw finalizeError })
  })
  const result = await runFinalizeChapterCommand(input)
  assert.equal(result.ok, false)
  assert.equal(result.code, 'finalization_failed')
  assert.equal(result.chapterFinalized, false)
  assert.equal(calls.markFinalizationFailure.count(), 0, 'pre-version failure must not mark post-finalize failure')
  assert.deepEqual(calls.endFinalizationRun.last(), ['run-1', 'project-1', 88, expectedEndOptions(false)])
}

{
  const { input, calls } = createCommandInput({
    processChapterFinalization: callRecorder('processChapterFinalization', async () => ({
      facts: [],
      settingChanges: [],
      errors: [{ step: 'facts', message: 'facts failed', required: true }]
    }))
  })
  const result = await runFinalizeChapterCommand(input)
  assert.equal(result.ok, false)
  assert.equal(result.code, 'post_finalize_failed')
  assert.equal(result.chapterFinalized, true)
  assert.equal(calls.markFinalizationFailure.count(), 1)
  assert.equal(calls.saveDurableFinalizationMarker.count(), 1)
  assert.equal(calls.upsertDurableFinalizationMarker.count(), 1)
  assert.deepEqual(calls.endFinalizationRun.last(), ['run-1', 'project-1', 88, expectedEndOptions(true)])
}

{
  const storyError = new Error('story_block_stage_update_conflict')
  const { input, calls } = createCommandInput({
    performStoryBlockReviewAfterFinalize: callRecorder('performStoryBlockReviewAfterFinalize', async () => { throw storyError })
  })
  const result = await runFinalizeChapterCommand(input)
  assert.equal(result.ok, false)
  assert.equal(result.code, 'post_finalize_failed')
  assert.equal(calls.onStoryBlockReviewFailure.count(), 1)
  assert.equal(calls.markFinalizationFailure.count(), 1)
  assert.equal(calls.saveDurableFinalizationMarker.count(), 1)
  assert.deepEqual(calls.endFinalizationRun.last(), ['run-1', 'project-1', 88, expectedEndOptions(true)])
}

{
  const rerouteError = new Error('outline unavailable')
  const { input, calls } = createCommandInput({
    rerouteOutlineAfterFinalization: callRecorder('rerouteOutlineAfterFinalization', async () => { throw rerouteError })
  })
  const result = await runFinalizeChapterCommand(input)
  assert.equal(result.ok, true)
  assert.equal(result.code, 'finalization_completed')
  assert.equal(result.warnings.length, 1)
  assert.equal(calls.onRerouteWarning.count(), 1)
  assert.equal(calls.markFinalizationFailure.count(), 0)
  assert.deepEqual(calls.endFinalizationRun.last(), ['run-1', 'project-1', 88, expectedEndOptions(false)])
}

{
  const { input, calls } = createCommandInput()
  const result = await runFinalizeChapterCommand(input)
  assert.equal(result.ok, true)
  assert.equal(result.code, 'finalization_completed')
  assert.equal(result.factCount, 2)
  assert.equal(result.settingChangeCount, 1)
  assert.equal(calls.markFinalizationFailure.count(), 0)
  assert.deepEqual(calls.finalizeVersion.last()[1], {
    projectId: 'project-1',
    sourceChapterNum: 88,
    sourceVersionId: 'version-1',
    runId: 'run-id-1',
    finalizationId: 'fin-id-1',
    commitStatus: 'final'
  })
  assert.deepEqual(calls.endFinalizationRun.last(), ['run-1', 'project-1', 88, expectedEndOptions(false)])
}

console.log('writer flow finalization command contract passed')
