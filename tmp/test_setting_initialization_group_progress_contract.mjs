import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

import {
  SETTING_INITIALIZATION_GROUPS
} from '../frontend/src/prompts/settingsFromBible.js'

const store = readFileSync('frontend/src/stores/settingStore.js', 'utf8')
const bible = readFileSync('frontend/src/components/bible/CreativeBible.vue', 'utf8')
const liveScript = readFileSync('tmp/run_longform_browser_240w_phase1.mjs', 'utf8')

assert.deepEqual(
  SETTING_INITIALIZATION_GROUPS.map(group => group.label),
  ['人物', '势力/组织', '世界规则/能力体系', '地点/物品', '长期关系']
)

assert.match(store, /bibleInitializationProgress/)
assert.match(store, /bibleInitializationDiagnostics/)
assert.match(store, /currentGroupLabel/)
assert.match(store, /completedGroups/)
assert.match(store, /generatedCandidates/)
assert.match(store, /promptChars/)
assert.match(store, /startedAt/)
assert.match(store, /endedAt/)
assert.match(store, /repairTriggered/)
assert.match(store, /fallbackTriggered/)
assert.match(store, /fallbackReason/)
assert.match(store, /rawHead/)
assert.match(store, /rawTail/)
assert.match(store, /savedSuccessfully/)

assert.match(bible, /正在提取设定库/)
assert.match(bible, /已完成\s*\{\{\s*settingInitializationProgress\.completedGroups/)
assert.match(bible, /已生成\s*\{\{\s*settingInitializationProgress\.generatedCandidates/)
assert.match(bible, /可重试失败分组/)
assert.match(liveScript, /bible settings extraction groups settled/)
assert.match(liveScript, /继续提取\/重试失败分组/)

console.log('setting initialization group progress contract tests passed')
