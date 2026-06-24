import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const guard = readFileSync('frontend/src/utils/finalizationGuard.js', 'utf8')
const writerView = readFileSync('frontend/src/views/WriterView.vue', 'utf8')

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
  /重试第 \{\{ blockingFinalizationPending\.chapterNum \}\} 章定稿后/,
  'WriterView must keep a user-visible retry postprocess entry'
)
assert.match(
  writerView,
  /clearChapterFinalizationFailure|clearChapterFinalizationPending/,
  'successful retry must clear the stored failure marker'
)

console.log('post finalize retryable failure contract passed')
