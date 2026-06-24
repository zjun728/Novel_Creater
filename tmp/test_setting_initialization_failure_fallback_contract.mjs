import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

import {
  SETTING_INITIALIZATION_GROUPS,
  buildFallbackSettingsFromBibleEvents,
  filterEventsForInitializationGroup
} from '../frontend/src/prompts/settingsFromBible.js'

const store = readFileSync('frontend/src/stores/settingStore.js', 'utf8')

const seed = {
  openingHook: '陆沉舟在雨夜当铺清账时，发现死去三年的父亲名字出现在当天新账上。',
  differentiation: '用账本、债务和灵脉账目推动长线剧情，不靠规则表解释世界。',
  coreConflict: '巡天司、商盟和隐秘星债会都想控制星账。'
}
const bible = {
  premise: '被逐出巡天司的少年用会记债的星账追查灵脉衰竭真相。',
  worldRules: '星账只记录活人的灵脉债务，每次使用星账都要付出现实代价。'
}

const locationGroup = SETTING_INITIALIZATION_GROUPS.find(group => group.key === 'locationsItems')
const fallbackEvents = filterEventsForInitializationGroup(
  buildFallbackSettingsFromBibleEvents({ bible, seed }),
  locationGroup
)

assert.ok(fallbackEvents.length >= 1, '地点/物品分组必须有保守 fallback 候选')
assert.ok(
  fallbackEvents.some(event => ['location', 'item'].includes(event.entityType)),
  '地点/物品 fallback 只能生成 location/item 候选'
)
assert.ok(
  fallbackEvents.some(event => /星账|当铺/.test(event.entityName)),
  '地点/物品 fallback 应从开局地点或核心物件生成待确认候选'
)

assert.match(store, /模型调用失败/)
assert.match(store, /diagnostics\.fallbackTriggered\s*=\s*true/)
assert.match(store, /diagnostics\.fallbackReason\s*=/)
assert.match(store, /savedSuccessfully:\s*true/)
assert.match(store, /return\s+\{\s*created,\s*events,\s*lastText:\s*''\s*\}/)

console.log('setting initialization failure fallback contract tests passed')
