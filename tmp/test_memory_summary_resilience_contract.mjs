import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const memoryStore = readFileSync('frontend/src/stores/memoryStore.js', 'utf8')
const summaryPrompt = readFileSync('frontend/src/prompts/summary.js', 'utf8')
const writer = readFileSync('frontend/src/views/WriterView.vue', 'utf8')

assert.match(
  memoryStore,
  /const requiredFinalizationSteps = new Set\(\[[^\]]*'facts'[^\]]*'settingChanges'[^\]]*\]\)/,
  'chapter summary failures must not be a hard blocker before story block review'
)
assert.doesNotMatch(
  memoryStore.match(/const requiredFinalizationSteps = new Set\(\[[\s\S]*?\]\)/)?.[0] || '',
  /'summary'/,
  'summary must not be marked as a required finalization step'
)

assert.match(
  summaryPrompt,
  /buildSummaryRepairPrompt/,
  'summary JSON parse failures need a dedicated repair prompt before fallback'
)
assert.match(
  memoryStore,
  /async function parseSummaryResult/,
  'summary parsing must go through a repairable parser'
)
assert.match(
  memoryStore,
  /buildFallbackChapterSummary/,
  'summary generation must have a local fallback when AI JSON repair fails'
)
assert.match(
  memoryStore,
  /summaryParseError/,
  'fallback summaries should preserve parse failure diagnostics'
)

const finalizeFn = writer.slice(
  writer.indexOf('async function performFinalize'),
  writer.indexOf('async function performStoryBlockReviewAfterFinalize')
)
assert.match(
  finalizeFn,
  /performStoryBlockReviewAfterFinalize/,
  'writer finalization must still call story block review after non-required postprocess errors'
)

console.log('memory summary resilience contract tests passed')
