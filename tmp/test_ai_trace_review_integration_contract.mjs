import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const memoryStore = readFileSync('frontend/src/stores/memoryStore.js', 'utf8')

for (const type of [
  'sensory_checklist',
  'decorative_number',
  'emotion_label',
  'overfunctional_density',
  'skipped_loss'
]) {
  assert.match(
    memoryStore,
    new RegExp(`'${type}'`),
    `audit normalizer should preserve AI trace issue type ${type}`
  )
}

assert.match(memoryStore, /buildAiTraceReviewSystemPrompt/, 'audit flow should import AI trace second review system prompt')
assert.match(memoryStore, /buildAiTraceReviewPrompt/, 'audit flow should import AI trace second review prompt')
assert.match(memoryStore, /reviewAiTraceIssuesIfNeeded/, 'audit flow should run AI trace second review after first audit')
assert.doesNotMatch(
  memoryStore,
  /new Set\(\[\.\.\.AI_TRACE_ISSUE_TYPES/,
  'AI trace second review should not directly review every generic rule type such as logic or pacing'
)
assert.match(memoryStore, /decision\s*===\s*'ignore'/, 'AI trace second review should be able to dismiss false-positive issues')
assert.match(memoryStore, /aiTraceReview/, 'audit result should keep AI trace review metadata for transparency')
