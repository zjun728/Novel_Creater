import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const liveScript = readFileSync('tmp/run_longform_browser_240w_phase1.mjs', 'utf8')
const writerView = readFileSync('frontend/src/views/WriterView.vue', 'utf8')

assert.match(
  liveScript,
  /promoteFinalizeFailureFromFlowEvents/,
  'live report must promote chapter flowEvents.finalize_failed into the top-level blocker'
)
assert.match(
  liveScript,
  /flowEvents\?\.finalize_failed[\s\S]*finalize_timed_out[\s\S]*report\.blocker/,
  'finalize_failed flow events should become a finalize_timed_out blocker'
)
assert.match(
  liveScript,
  /第 \$\{chapter\.chapterNum\} 章定稿超时/,
  'acceptance.reason should identify the timed-out chapter'
)
assert.match(
  liveScript,
  /report\.acceptance\.reason\s*=\s*report\.blocker\.message/,
  'promoted finalize blocker must populate acceptance.reason'
)

assert.match(
  liveScript,
  /finalizeDiagnostics/,
  'live report should include finalizeDiagnostics on chapter reports and blockers'
)
for (const field of [
  'chapterStatus',
  'finalVersionId',
  'finalVersionType',
  'versionCount',
  'pendingSettingsCount',
  'pendingFactsCount',
  'storyBlockReviewCount',
  'markerPresent',
  'postFinalizeFailed',
  'activeAction',
  'recentAiProxy'
]) {
  assert.match(liveScript, new RegExp(field), `finalizeDiagnostics should include ${field}`)
}

assert.match(
  liveScript,
  /await dismissAppDialogs\(page\)[\s\S]*markChapterFlowEvent\(chapterNum, 'finalize_click_started'\)/,
  'audit modal should be reliably dismissed before clicking finalize'
)

assert.match(
  writerView,
  /reconcileCompletedFinalizationMarker[\s\S]*clearChapterFinalizationPending/,
  'completed backend finalization with a stale marker should be self-healed by clearing the marker'
)
assert.match(
  writerView,
  /markChapterFinalizationFailure[\s\S]*retryablePostprocessFailure/,
  'post-finalize failures should write retryablePostprocessFailure state'
)

console.log('live finalize timeout contract passed')
