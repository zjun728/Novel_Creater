import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const store = readFileSync('frontend/src/stores/volumeStore.js', 'utf8')
const prompt = readFileSync('frontend/src/prompts/volumePlan.js', 'utf8')
const adapter = readFileSync('frontend/src/api/ai/openaiCompatibleAdapter.js', 'utf8')
const liveScript = readFileSync('tmp/run_longform_browser_240w_phase1.mjs', 'utf8')

assert.match(prompt, /字段必须短/)
assert.match(prompt, /如果内容过多，优先缩短字段，不要破坏 JSON/)
assert.match(prompt, /buildCompactVolumePlanRetryPrompt/)

assert.match(adapter, /options\.returnRaw/)

assert.match(store, /lastPlanningDiagnostics/)
assert.match(store, /createVolumePlanningDiagnostics/)
assert.match(store, /saveVolumePlanningDiagnostics/)
assert.match(store, /repairTriggered/)
assert.match(store, /repairSucceeded/)
assert.match(store, /compactRetryTriggered/)
assert.match(store, /compactRetrySucceeded/)
assert.match(store, /finishReason/)
assert.match(store, /usage/)
assert.match(store, /rawHead/)
assert.match(store, /rawTail/)
assert.match(store, /returnRaw:\s*true/)
assert.match(store, /maxTokens:\s*(?:1[0-9]{4}|[89][0-9]{3})/)
assert.match(store, /buildCompactVolumePlanRetryPrompt/)

assert.match(liveScript, /readVolumePlanningDiagnostics/)
assert.match(liveScript, /volume plan failure dialog/)
assert.match(liveScript, /volumePlanning\.diagnostics/)

console.log('volume plan JSON resilience contract tests passed')
