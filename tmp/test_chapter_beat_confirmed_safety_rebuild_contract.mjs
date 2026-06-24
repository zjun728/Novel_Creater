import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const writerView = readFileSync('frontend/src/views/WriterView.vue', 'utf8')
const writerStore = readFileSync('frontend/src/stores/writerStore.js', 'utf8')

assert.match(writerView, /beatPlanConfirmedByUser:\s*true/)
assert.match(writerStore, /context\?\.beatPlanConfirmedByUser/)
assert.match(writerStore, /local_safety_rebuild_acknowledged/)
assert.match(writerStore, /beatPlanSafetyRebuildAcknowledged:\s*true/)
assert.match(writerStore, /已使用确认后的安全小纲继续生成正文/)

const guardIndex = writerStore.indexOf("beatPlanQualityNotice.value?.source === 'local_safety_rebuild'")
const confirmedIndex = writerStore.indexOf('context?.beatPlanConfirmedByUser', guardIndex)
const throwIndex = writerStore.indexOf("error.code = 'BEAT_PLAN_LOCAL_SAFETY_REBUILD'", guardIndex)
assert.ok(guardIndex >= 0, '正文生成入口必须保留 local_safety_rebuild 守卫')
assert.ok(confirmedIndex > guardIndex, '守卫内必须先检查确认小纲路径')
assert.ok(throwIndex > confirmedIndex, '未确认小纲仍需抛回确认流程')

console.log('chapter beat confirmed safety rebuild contract tests passed')
