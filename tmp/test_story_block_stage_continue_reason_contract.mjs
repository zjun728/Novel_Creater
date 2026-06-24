import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

import {
  buildStoryBlockReviewPrompt,
  buildStoryBlockReviewSystemPrompt,
  normalizeStoryBlockReviewResult
} from '../frontend/src/prompts/storyBlockPrompt.js'

const systemPrompt = buildStoryBlockReviewSystemPrompt()
const reviewPrompt = buildStoryBlockReviewPrompt({
  chapterNum: 4,
  finalizedSummary: '主角进入旧账房地窖，但账册线索尚未取完整。',
  blockStageSnapshot: {
    stageId: 'stage-3_new',
    stagePurpose: '获取老账房地窖下父亲藏匿的账册存根',
    stageAction: '进入地窖并避开追兵',
    stageChoice: '先确认宋知远意图还是直接取账册'
  }
})

assert.match(systemPrompt, /stageContinues=true[\s\S]*stageContinueReason/)
assert.match(systemPrompt, /本阶段为什么没有完成/)
assert.match(systemPrompt, /下一章继续完成哪个具体动作|下一章继续完成的具体动作/)
assert.match(systemPrompt, /本章已经完成了什么/)
assert.match(reviewPrompt, /"stageContinueReason"/)
assert.match(reviewPrompt, /stageContinues[\s\S]*stageContinueReason/)

const normalized = normalizeStoryBlockReviewResult({
  decision: 'continue_current_block',
  stageContinues: true,
  stageContinueReason: '本章只完成潜入旧账房和触发追兵压力，尚未取到账册存根；下一章继续在地窖内做取账册或先辨别宋知远立场的选择。'
})
assert.equal(normalized.stageContinues, true)
assert.match(normalized.stageContinueReason, /尚未取到账册存根/)

const storyBlockStore = readFileSync('frontend/src/stores/storyBlockStore.js', 'utf8')
assert.match(storyBlockStore, /ensureValidStoryBlockReview/)
assert.match(storyBlockStore, /repairStoryBlockReviewSemantics/)
assert.match(storyBlockStore, /stage_continue_reason_missing/)
assert.match(storyBlockStore, /semanticRepairTriggered/)

const writerView = readFileSync('frontend/src/views/WriterView.vue', 'utf8')
assert.doesNotMatch(
  writerView,
  /当前阶段需要跨章继续，下一章继续承接同一阶段。/,
  'WriterView must not silently invent a generic same-stage continuation reason'
)
assert.match(writerView, /stageContinueReason/)

console.log('story block stage continue reason contract tests passed')
