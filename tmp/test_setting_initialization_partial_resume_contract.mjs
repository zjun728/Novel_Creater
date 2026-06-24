import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const store = readFileSync('frontend/src/stores/settingStore.js', 'utf8')
const bible = readFileSync('frontend/src/components/bible/CreativeBible.vue', 'utf8')

assert.match(store, /async function runBibleInitializationGroup/)
assert.match(store, /saveBibleInitializationProgress/)
assert.match(store, /loadBibleInitializationProgress/)
assert.match(store, /saveChangeEvent\(projectId,\s*\{/)
assert.match(store, /savedSuccessfully:\s*true/)
assert.match(store, /提取空响应/)
assert.match(store, /未解析出可保存候选/)
assert.match(store, /待确认占位候选/)
assert.match(store, /buildFallbackEventsForInitializationGroup/)
assert.match(store, /待确认长期关系/)
assert.match(store, /partial_failed/)
assert.match(store, /failedGroups/)
assert.match(store, /continueOnError/)

assert.match(store, /async function retryFailedBibleInitializationGroups/)
assert.match(bible, /handleRetryFailedSettingGroups/)
assert.match(bible, /继续提取\/重试失败分组/)
assert.match(bible, /失败后可重试/)

console.log('setting initialization partial resume contract tests passed')
