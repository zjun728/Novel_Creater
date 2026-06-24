import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import {
  collectStructuredBeatPlanIssues,
  parseStructuredBeatPlan
} from '../frontend/src/prompts/chapter.js'

const placeholderBeatPlan = `
### 本章事件
未填写

### 人物目标
待补充

### 核心冲突
TODO

### 外部压力
略

### 代价或损失
陆沉舟为使用星账消耗十年寿命。

### 不可逆变化
空

### 结尾交接
未填写
`

const issues = collectStructuredBeatPlanIssues(parseStructuredBeatPlan(placeholderBeatPlan))
assert.ok(
  issues.placeholderFields?.includes('chapterEvent'),
  'placeholder chapterEvent must be reported'
)
assert.ok(
  issues.placeholderFields?.includes('characterGoal'),
  'placeholder characterGoal must be reported'
)
assert.ok(
  issues.placeholderFields?.includes('coreConflict'),
  'placeholder coreConflict must be reported'
)
assert.ok(
  issues.issues.some(issue => issue.type === 'structured_beat_plan_placeholder_fields'),
  'placeholder fields must produce a quality issue'
)

const writerStore = readFileSync('frontend/src/stores/writerStore.js', 'utf8')
assert.match(
  writerStore,
  /beatPlanQualityDiagnostics/,
  'writer store must expose beatPlanQualityDiagnostics for live reports'
)
assert.match(
  writerStore,
  /BEAT_PLAN_QUALITY_FAILED|beat_plan_quality_failed/,
  'placeholder beat plan failures must use a distinct quality failure code'
)
assert.match(
  writerStore,
  /placeholderFields/,
  'writer store quality diagnostics must include placeholderFields'
)

const liveScript = readFileSync('tmp/run_longform_browser_240w_phase1.mjs', 'utf8')
for (const marker of [
  'title_generation_started',
  'title_generation_done',
  'title_generation_failed',
  'audit_click_started',
  'audit_started',
  'audit_done',
  'audit_failed',
  'audit_modal_visible',
  'finalize_click_started',
  'finalize_dialog_visible',
  'finalize_confirm_clicked',
  'finalize_started',
  'finalize_done',
  'finalize_failed',
  'postprocess_started',
  'postprocess_done',
  'postprocess_failed',
  'story_block_review_started',
  'story_block_review_done',
  'story_block_review_failed'
]) {
  assert.match(liveScript, new RegExp(marker), `live script must record ${marker}`)
}
for (const field of [
  'audit_issue_count',
  'hard_issue_count',
  'soft_issue_count',
  'visibleButtonStates',
  'auditRunning',
  'finalizeSubmitting',
  'memoryProcessing',
  'finalizationActionBusy',
  'cjkCharCount',
  'rawContentLength',
  'targetRange',
  'wordCountPolicyStatus'
]) {
  assert.match(liveScript, new RegExp(field), `live diagnostics/report must include ${field}`)
}
for (const blocker of [
  'audit_not_started',
  'audit_timed_out',
  'audit_modal_blocked',
  'finalize_not_started',
  'finalize_timed_out',
  'finalize_postprocess_timed_out'
]) {
  assert.match(liveScript, new RegExp(blocker), `live script must classify ${blocker}`)
}
assert.doesNotMatch(
  liveScript,
  /phase_target_3_process_timeout_after_draft_candidate/,
  'live script must not use a generic process timeout blocker after draft candidate'
)

console.log('beat plan quality and finalize diagnostics contract tests passed')
