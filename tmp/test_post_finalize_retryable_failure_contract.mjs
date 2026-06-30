import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const guard = readFileSync('frontend/src/utils/finalizationGuard.js', 'utf8')
const writerView = readFileSync('frontend/src/views/WriterView.vue', 'utf8')
const markerAction = readFileSync('frontend/src/application/writer-flow/finalization-marker-action.js', 'utf8')

assert.match(
  guard,
  /markChapterFinalizationFailure/,
  'finalization guard must be able to persist retryable post-finalize failure state'
)
assert.match(
  guard,
  /retryablePostprocessFailure/,
  'finalization marker must preserve retryable postprocess failure details'
)
assert.match(
  guard,
  /postFinalizePending/,
  'finalization marker must explicitly indicate postFinalizePending'
)

assert.match(
  writerView,
  /markChapterFinalizationFailure\(/,
  'WriterView must write retryable failure state when finalized postprocess fails'
)
assert.match(
  writerView,
  /postFinalizeFailed/,
  'WriterView must expose post-finalize failure state to the UI and live diagnostics'
)
assert.match(
  writerView,
  /finalizationMarkerAction\.buttonText/,
  'WriterView must render the user-visible retry postprocess action from marker action state'
)
assert.match(
  markerAction,
  /重试第 \$\{chapterNum \|\| ''\} 章定稿后提取/,
  'marker action must keep a user-visible retry postprocess label'
)
assert.match(
  writerView,
  /clearChapterFinalizationFailure|clearChapterFinalizationPending/,
  'successful retry must clear the stored failure marker'
)

console.log('post finalize retryable failure contract passed')
