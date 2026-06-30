import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const writerView = readFileSync('frontend/src/views/WriterView.vue', 'utf8')
const commandSource = readFileSync('frontend/src/application/writer-flow/finalization-command.js', 'utf8')

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

function countMatches(source, pattern) {
  return [...source.matchAll(pattern)].length
}

function objectLiteralBlock(source, propertyName) {
  const propertyIndex = source.indexOf(propertyName)
  assert.notEqual(propertyIndex, -1, `missing property: ${propertyName}`)
  const arrowIndex = source.indexOf('=>', propertyIndex)
  assert.notEqual(arrowIndex, -1, `missing callback arrow for ${propertyName}`)
  const bodyStart = source.indexOf('{', arrowIndex)
  assert.notEqual(bodyStart, -1, `missing callback body for ${propertyName}`)
  let depth = 0
  for (let index = bodyStart; index < source.length; index += 1) {
    const char = source[index]
    if (char === '{') depth += 1
    if (char === '}') {
      depth -= 1
      if (depth === 0) return source.slice(bodyStart, index + 1)
    }
  }
  assert.fail(`unterminated callback body: ${propertyName}`)
}

const performFinalizeBlock = extractFunctionBlock(writerView, 'async function performFinalize(version)')
for (const marker of [
  'runFinalizeChapterCommand({',
  'onPostFinalizeFailure',
  "result.code === 'finalization_run_blocked'",
  'result.chapterFinalized',
  'finalizeSubmitting.value = false',
  'memoryProcessing.value = false'
]) {
  assert.match(performFinalizeBlock, new RegExp(marker.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')), `balanced performFinalize block must include ${marker}`)
}
assert.equal(
  countMatches(performFinalizeBlock, /\brunFinalizeChapterCommand\s*\(/g),
  1,
  'performFinalize must call runFinalizeChapterCommand exactly once'
)
assert.doesNotMatch(
  performFinalizeBlock,
  /await\s+writerStore\.finalizeVersion|const\s+results\s*=\s*await\s+memoryStore\.processChapterFinalization|await\s+performStoryBlockReviewAfterFinalize|await\s+novelStore\.rerouteOutlineAfterFinalization/,
  'performFinalize must not keep a direct duplicate finalizeVersion -> process -> storyReview -> reroute state machine'
)

for (const injected of [
  'beginFinalizationRun: beginChapterFinalizationRun',
  'finalizeVersion: writerStore.finalizeVersion',
  'finishLinkedCorrectionTasks',
  'clearTempDraft: writerStore.clearTempDraft',
  'processChapterFinalization: memoryStore.processChapterFinalization',
  'loadContextData',
  'performStoryBlockReviewAfterFinalize',
  'rerouteOutlineAfterFinalization: novelStore.rerouteOutlineAfterFinalization',
  'buildRerouteContext: buildFinalizationRerouteContext',
  'markFinalizationFailure: markChapterFinalizationFailure',
  'endFinalizationRun: endChapterFinalizationRun'
]) {
  assert.match(performFinalizeBlock, new RegExp(injected.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')), `performFinalize must inject ${injected}`)
}

const postFailureCallback = objectLiteralBlock(performFinalizeBlock, 'onPostFinalizeFailure')
assert.match(
  postFailureCallback,
  /finalizationMarkerVersion\.value\s*\+=\s*1/,
  'onPostFinalizeFailure must refresh finalizationMarkerVersion so blocking marker UI recomputes'
)

assert.match(
  performFinalizeBlock,
  /if \(result\.ok\) \{[\s\S]*result\.factCount[\s\S]*result\.settingChangeCount/,
  'success message must use factCount/settingChangeCount returned by the command'
)
assert.match(
  performFinalizeBlock,
  /else if \(result\.code === 'finalization_run_blocked'\) \{[\s\S]*定稿处理中[\s\S]*\} else if \(result\.chapterFinalized\)/,
  'finalization_run_blocked must only show processing feedback and must not fall through to failure messaging'
)
assert.match(
  performFinalizeBlock,
  /else if \(result\.chapterFinalized\) \{[\s\S]*定稿后处理失败[\s\S]*\} else \{[\s\S]*定稿失败/,
  'post-finalized failure and pre-finalization failure UI branches must remain separated'
)

assert.doesNotMatch(
  commandSource,
  /from ['"]|import\s+|@\/stores|@\/api|chatCompletion|localStorage|from ['"]vue|naive-ui|use[A-Z][A-Za-z]+Store/,
  'finalization command must remain import-free and use injected dependencies only'
)
for (const dependency of [
  'beginFinalizationRun',
  'finalizeVersion',
  'finishLinkedCorrectionTasks',
  'clearTempDraft',
  'processChapterFinalization',
  'loadContextData',
  'performStoryBlockReviewAfterFinalize',
  'rerouteOutlineAfterFinalization',
  'buildRerouteContext',
  'markFinalizationFailure',
  'endFinalizationRun'
]) {
  assert.match(commandSource, new RegExp(`requiredFunction\\(input, '${dependency}'\\)`), `command must require injected ${dependency}`)
}

console.log('writer flow finalization callsite contract passed')
