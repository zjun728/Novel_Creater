import assert from 'node:assert/strict'

import {
  AI_TRACE_ISSUE_TYPES,
  AI_TRACE_RULES,
  formatAiTraceRulesForAudit,
  formatAiTraceRulesForGeneration,
  getAiTraceRuleById
} from '../frontend/src/qualityRules/aiTraceRules.js'

assert.ok(AI_TRACE_RULES.length >= 10, 'AI trace rules should cover the main style fingerprints')
assert.ok(AI_TRACE_ISSUE_TYPES.includes('info_dump'), 'information dumping must be a tracked issue type')
assert.ok(AI_TRACE_ISSUE_TYPES.includes('overfunctional_density'), 'functional-overload must be a tracked issue type')
assert.ok(getAiTraceRuleById('emotion_label'), 'rules should be queryable by id')

const generationText = formatAiTraceRulesForGeneration()
assert.match(generationText, /写作方法/)
assert.match(generationText, /动作后不要翻译情绪/)
assert.match(generationText, /信息尽量被发现/)
assert.doesNotMatch(generationText, /必须报问题/)
assert.doesNotMatch(generationText, /超过\s*2\s*次/)

const auditText = formatAiTraceRulesForAudit()
assert.match(auditText, /AI 痕迹反证/)
assert.match(auditText, /情绪贴标签/)
assert.match(auditText, /功能过满/)
assert.match(auditText, /判断是否真的影响读者代入/)
