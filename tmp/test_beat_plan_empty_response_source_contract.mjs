import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const writerStore = readFileSync('frontend/src/stores/writerStore.js', 'utf8')
const writerView = readFileSync('frontend/src/views/WriterView.vue', 'utf8')

assert.match(writerStore, /deriveChapterBeatPlanFromStoryBlock/, 'writer store must derive a beat plan from the story block after empty AI responses')
assert.match(writerStore, /BEAT_PLAN_SOURCES/, 'writer store must use explicit beat plan source constants')
assert.match(writerStore, /BEAT_PLAN_SOURCES\.derivedFromStoryBlock|derived_from_story_block/, 'writer store must record derived_from_story_block source')
assert.match(writerStore, /BEAT_PLAN_SOURCES\.localSafetyRequiresReview|local_safety_requires_review/, 'writer store must record review-required source when stage snapshot is incomplete')
assert.match(writerStore, /BEAT_PLAN_REQUIRES_REVIEW|beat_plan_requires_review/, 'incomplete local safety drafts must use beat_plan_requires_review')
assert.match(writerStore, /whetherAllowedToContinue/, 'beat plan diagnostics must record whether the flow may continue')
assert.match(writerStore, /stageSnapshotFields/, 'beat plan diagnostics must record story block snapshot field coverage')
assert.match(writerStore, /buildAiResponseDiagnostics|responseDiagnostics/, 'AI attempts must include backend response diagnostics')
assert.doesNotMatch(
  writerStore,
  /local_safety_empty_response[\s\S]{0,900}requiresReview:\s*true[\s\S]{0,900}BEAT_PLAN_GENERATION_EMPTY/,
  'complete story block empty-response fallback must not be hardwired to review-required generation failure'
)

assert.match(writerView, /beatPlanSourceLabel/, 'writer desk must expose a human-readable beat plan source label')
assert.match(writerView, /故事块派生/, 'writer desk must show the story-block-derived beat plan source')
assert.match(writerView, /buildBeatPlanStoryBlockMetadata[\s\S]*beatPlanSource/, 'beat plan save metadata must include beatPlanSource')
assert.match(writerView, /buildBeatPlanStoryBlockMetadata[\s\S]*derivedFromStoryBlock/, 'beat plan save metadata must include derivedFromStoryBlock')

console.log('beat plan empty response source contract tests passed')
