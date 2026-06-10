import assert from 'node:assert/strict'

import {
  AI_TRACE_REVIEW_DECISIONS,
  buildAiTraceReviewPrompt,
  buildAiTraceReviewSystemPrompt
} from '../frontend/src/prompts/aiTraceReview.js'
import { buildAuditPrompt } from '../frontend/src/prompts/audit.js'

assert.ok(AI_TRACE_REVIEW_DECISIONS.includes('ignore'), 'review can dismiss false positives')
assert.ok(AI_TRACE_REVIEW_DECISIONS.includes('local_window_revision'), 'review can route to sliding-window repair')
assert.ok(AI_TRACE_REVIEW_DECISIONS.includes('outline_replan'), 'review can identify outline-source problems')

const systemPrompt = buildAiTraceReviewSystemPrompt()
assert.match(systemPrompt, /AI 痕迹二审/)
assert.match(systemPrompt, /反证/)
assert.match(systemPrompt, /不要直接改正文/)
assert.match(systemPrompt, /JSON/)
assert.doesNotMatch(systemPrompt, /重新审完整章/)

const prompt = buildAiTraceReviewPrompt({
  chapterNum: 3,
  chapterContent: '林逐握住铜钱。雨声停了一瞬。他没有立刻抬头。',
  issues: [
    {
      type: 'ai_tone',
      severity: 'minor',
      location: '雨声停了一瞬。',
      description: '疑似模板化停顿',
      suggestion: '判断是否需要替换'
    }
  ],
  context: {
    writingFingerprint: '冷静考据视角，允许少量留白。',
    beatPlan: '雨夜开场，铜钱产生反应。'
  }
})

assert.match(prompt, /第 3 章/)
assert.match(prompt, /待二审问题/)
assert.match(prompt, /处理决策/)
assert.match(prompt, /local_window_revision/)
assert.match(prompt, /写作指纹/)
assert.match(prompt, /雨声停了一瞬/)

const auditPrompt = buildAuditPrompt('他感到愤怒。雨声停了一瞬。', { chapterNum: 3 })
assert.match(auditPrompt, /AI 痕迹反证/)
assert.match(auditPrompt, /情绪贴标签/)
assert.match(auditPrompt, /功能过满/)
