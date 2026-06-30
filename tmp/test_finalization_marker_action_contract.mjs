import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { getFinalizationMarkerAction } from '../frontend/src/application/writer-flow/finalization-marker-action.js'

const writerView = readFileSync('frontend/src/views/WriterView.vue', 'utf8')
const helper = readFileSync('frontend/src/application/writer-flow/finalization-marker-action.js', 'utf8')

assert.equal(getFinalizationMarkerAction(null).canRetryPostprocess, false)

const retryable = getFinalizationMarkerAction({
  chapterNum: 88,
  retryablePostprocessFailure: {
    message: 'facts: upstream timeout',
    retryable: true
  }
})
assert.equal(retryable.kind, 'retry_postprocess')
assert.equal(retryable.canRetryPostprocess, true)
assert.match(retryable.buttonText, /重试第 88 章定稿后提取/)

const processingOnly = getFinalizationMarkerAction({
  chapterNum: 88,
  status: 'processing',
  postFinalizePending: true,
  postFinalizeFailed: false
})
assert.equal(processingOnly.kind, 'pending_postprocess')
assert.equal(processingOnly.canRetryPostprocess, false)
assert.equal(processingOnly.buttonText, '')
assert.match(processingOnly.tagText, /定稿后处理未完成/)

const pendingOnly = getFinalizationMarkerAction({
  chapterNum: 88,
  postFinalizePending: true
})
assert.equal(pendingOnly.kind, 'pending_postprocess')
assert.equal(pendingOnly.canRetryPostprocess, false)

const storyBlockFailure = getFinalizationMarkerAction({
  chapterNum: 88,
  storyBlockSettlementFailure: {
    message: 'story_block_stage_update_conflict',
    retryable: false
  }
})
assert.equal(storyBlockFailure.kind, 'manual_story_block_settlement')
assert.equal(storyBlockFailure.canRetryPostprocess, false)
assert.match(storyBlockFailure.tagText, /故事块结算/)
assert.match(storyBlockFailure.warning, /不会重跑故事块结算/)

assert.match(
  helper,
  /export function getFinalizationMarkerAction/,
  'marker action helper must expose a pure classifier'
)
assert.doesNotMatch(
  helper,
  /use[A-Z][A-Za-z]+Store|chatCompletion|api\./,
  'marker action helper must stay pure and independent from stores/api/chat'
)
assert.match(
  writerView,
  /getFinalizationMarkerAction/,
  'WriterView must use the marker action helper'
)
assert.match(
  writerView,
  /finalizationMarkerAction\.canRetryPostprocess/,
  'WriterView retry button/function must be guarded by canRetryPostprocess'
)

console.log('finalization marker action contract passed')
