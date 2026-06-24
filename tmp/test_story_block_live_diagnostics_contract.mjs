import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const store = readFileSync('frontend/src/stores/storyBlockStore.js', 'utf8')
const writer = readFileSync('frontend/src/views/WriterView.vue', 'utf8')

for (const field of [
  'providerId',
  'modelName',
  'supportsJSON',
  'promptChars',
  'promptTokensApprox',
  'rawHead',
  'rawTail',
  'containsMarkdownCodeBlock',
  'likelyTruncated',
  'repairTriggered',
  'repairSucceeded',
  'repairError'
]) {
  assert.match(store, new RegExp(field), `storyBlockStore should record ${field}`)
}

assert.match(writer, /planningDiagnostics/)
assert.match(writer, /storyBlockStore\.lastPlanningDiagnostics/)
assert.match(writer, /aiPlanningFallback/)
assert.match(writer, /requiresReview/)

console.log('story block live diagnostics contract tests passed')
