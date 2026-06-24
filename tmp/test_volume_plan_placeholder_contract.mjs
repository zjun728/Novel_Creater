import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const store = readFileSync('frontend/src/stores/volumeStore.js', 'utf8')
const planner = readFileSync('frontend/src/components/chapter/VolumePlanner.vue', 'utf8')

assert.match(store, /detectVolumePlanPlaceholders/)
assert.match(store, /volumePlanQualityWarnings/)
assert.match(store, /摘要不完整/)
assert.match(store, /TODO/)
assert.match(store, /待补充/)
assert.match(store, /略/)

assert.match(planner, /volumePlanQualityWarnings/)
assert.match(planner, /规划质量问题/)
assert.match(planner, /修复分卷规划/)
assert.match(planner, /重新生成分卷规划/)

console.log('volume plan placeholder contract tests passed')
