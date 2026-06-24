import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const writerView = readFileSync('frontend/src/views/WriterView.vue', 'utf8')
const liveScript = readFileSync('tmp/run_longform_browser_240w_phase1.mjs', 'utf8')

assert.match(
  writerView,
  /async function reconcileCompletedFinalizationMarker\(marker/,
  'WriterView must reconcile stale finalization markers when durable post-finalize state is already complete'
)
assert.match(
  writerView,
  /clearChapterFinalizationPending\(projectId\.value,\s*num/,
  'WriterView reconciliation must clear the chapter finalization marker'
)
assert.match(
  writerView,
  /findBlockingFinalizationPending\(\)[\s\S]*reconcileCompletedFinalizationMarker/,
  'AI context readiness must attempt marker reconciliation before blocking on stale marker'
)
assert.match(
  writerView,
  /getChapterFinalizationPending\(projectId\.value,\s*chapterNum\.value - 1\)[\s\S]*reconcileCompletedFinalizationMarker/,
  'previous chapter readiness must reconcile stale previous-chapter markers'
)
assert.match(
  writerView,
  /retryFinalizationPostprocess[\s\S]*reconcileCompletedFinalizationMarker/,
  'retry postprocess entry must be able to clear already-complete marker state'
)

assert.match(liveScript, /async function waitForPostFinalizeSettlement\(page,\s*chapterNum/, 'live script must wait for post-finalize settlement')
for (const field of [
  'finalizationMarkerBeforeNextChapter',
  'finalizationMarkerClearedAt',
  'finalizationMaskVisible',
  'postFinalizeWaitReason',
  'postFinalizeWaitPassed',
  'navigatedToSettingsAfterMarkerCleared'
]) {
  assert.match(liveScript, new RegExp(field), `live report must include ${field}`)
}
assert.match(
  liveScript,
  /await waitForPostFinalizeSettlement\(page,\s*chapterNum\)[\s\S]*page\.goto\(`\$\{FRONTEND\}\/project\/\$\{report\.project\.id\}\?tab=settingsLibrary`/,
  'live script must wait for marker-cleared settlement before navigating to settings'
)
assert.match(
  liveScript,
  /readFinalizationMarker\(page,\s*chapterNum\)[\s\S]*window\.localStorage\?\.getItem\(`novel_creator\.chapter_finalization\.\$\{projectId\}\.\$\{Number\(chapterNum\) \|\| 0\}`\)/,
  'live script must read the exact chapter finalization localStorage marker'
)

console.log('finalization marker settlement contract passed')
