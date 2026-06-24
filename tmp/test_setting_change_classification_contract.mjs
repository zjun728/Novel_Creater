import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import {
  classifySettingChangeRisk,
  isHardSettingField,
  isBatchAcceptableSettingChange
} from '../frontend/src/utils/settingChangeRisk.js'

const revealSample = {
  entityName: '陆沉舟之父',
  fieldPath: 'summary',
  oldValue: '陆沉舟之父，三年前死于北境灵脉矿场，但名字出现在星账新账上',
  newValue: '陆沉舟之父，三年前死于北境灵脉矿场（官方结论），但名籍被封存于巡天司旧档室甲字七号柜，可能未死',
  evidence: '星账浮现字迹：陆长庚，名籍封存，巡天司旧档室，甲字七号柜',
  confidence: 0.7,
  status: 'pending_review'
}

const reveal = classifySettingChangeRisk(revealSample)
assert.equal(reveal.classification, 'reveal_or_refinement')
assert.equal(isBatchAcceptableSettingChange(revealSample), true)
assert.ok(reveal.conflictWarnings.length >= 1)
assert.ok(reveal.conflictWarnings.some(item => item.includes('隐藏信息') || item.includes('旧设定细化')))

const hardConflict = classifySettingChangeRisk({
  entityName: '陆沉舟之父',
  fieldPath: 'summary',
  oldValue: '陆沉舟之父三年前死于北境灵脉矿场。',
  newValue: '陆沉舟之父并未死亡，他一直活着并亲自策划追杀陆沉舟。',
  evidence: '父亲现身承认布局。',
  confidence: 0.95
})
assert.equal(hardConflict.classification, 'hard_conflict')
assert.equal(isBatchAcceptableSettingChange(hardConflict), false)

const lowRisk = classifySettingChangeRisk({
  entityName: '陆沉舟',
  fieldPath: 'profile.currentState',
  oldValue: '在雨夜当铺清账。',
  newValue: '在雨夜当铺发现星账异常后，决定查清父亲名籍。',
  evidence: '第1章定稿',
  confidence: 0.8
})
assert.equal(lowRisk.classification, 'low_risk_update')
assert.equal(isBatchAcceptableSettingChange(lowRisk), true)

assert.equal(isHardSettingField('profile.faction'), true)
assert.equal(isHardSettingField('profile.realm'), true)
assert.equal(isHardSettingField('profile.nickname'), false)

const factionConflict = classifySettingChangeRisk({
  entityName: '林逐',
  changeType: 'update_entity',
  fieldPath: 'profile.faction',
  oldValue: '',
  newValue: '赤焰宗',
  evidence: '无明确剧情证据',
  confidence: 0.8
}, {
  existingEntity: {
    entityType: 'character',
    name: '林逐',
    profile: { faction: '青玄宗' }
  }
})
assert.equal(factionConflict.classification, 'hard_conflict')
assert.equal(isBatchAcceptableSettingChange(factionConflict), false)
assert.ok(factionConflict.conflictWarnings.some(item => item.includes('硬设定字段')))

const abilityLevelConflict = classifySettingChangeRisk({
  entityName: '林逐',
  changeType: 'update_entity',
  fieldPath: 'profile.realm',
  oldValue: '',
  newValue: '筑基',
  evidence: '无明确突破剧情',
  confidence: 0.8
}, {
  existingEntity: {
    entityType: 'character',
    name: '林逐',
    profile: { realm: '炼气' }
  }
})
assert.equal(abilityLevelConflict.classification, 'hard_conflict')
assert.equal(isBatchAcceptableSettingChange(abilityLevelConflict), false)

const duplicateEntityHardConflict = classifySettingChangeRisk({
  entityName: '林逐',
  changeType: 'new_entity',
  fieldPath: 'summary',
  newValue: JSON.stringify({
    summary: '青玄宗外门弟子',
    profile: { faction: '赤焰宗' }
  }),
  evidence: '新抽取候选',
  confidence: 0.8
}, {
  existingEntity: {
    entityType: 'character',
    name: '林逐',
    profile: { faction: '青玄宗' }
  }
})
assert.equal(duplicateEntityHardConflict.classification, 'hard_conflict')
assert.equal(isBatchAcceptableSettingChange(duplicateEntityHardConflict), false)

const duplicateEntityCategoryConflict = classifySettingChangeRisk({
  entityName: '废弃灵脉矿井',
  changeType: 'new_entity',
  fieldPath: 'summary',
  newValue: JSON.stringify({
    summary: '父亲坐标指向的最终地点，埋藏灵脉枯竭真相和星账线索',
    category: '矿井/秘境',
    profile: { category: '矿井/秘境' }
  }),
  evidence: '洞壁上镶嵌夜明珠，井下有三百丈线索',
  confidence: 1
}, {
  existingEntity: {
    entityType: 'location',
    name: '废弃灵脉矿井',
    category: '地点',
    summary: '北境废弃矿井',
    profile: {}
  }
})
assert.equal(duplicateEntityCategoryConflict.classification, 'hard_conflict')
assert.equal(isBatchAcceptableSettingChange(duplicateEntityCategoryConflict), false)
assert.ok(duplicateEntityCategoryConflict.conflictWarnings.some(item => item.includes('分类')))

const layeredHardFieldReveal = classifySettingChangeRisk({
  entityName: '陆沉舟之父',
  changeType: 'update_entity',
  fieldPath: 'summary',
  oldValue: '',
  newValue: '三年前死于北境灵脉矿场（官方结论），但名籍封存于巡天司旧档，可能未死',
  evidence: '星账浮现字迹：陆长庚，名籍封存',
  confidence: 0.7
}, {
  existingEntity: {
    entityType: 'character',
    name: '陆沉舟之父',
    summary: '三年前死于北境灵脉矿场',
    profile: {}
  }
})
assert.equal(layeredHardFieldReveal.classification, 'reveal_or_refinement')
assert.equal(isBatchAcceptableSettingChange(layeredHardFieldReveal), true)

const settingLibrary = readFileSync('frontend/src/components/settings-library/SettingLibrary.vue', 'utf8')
assert.match(settingLibrary, /隐藏信息揭示\/旧设定细化/)
assert.match(settingLibrary, /仍有硬冲突设定需要逐条确认，处理后才能进入下一章。/)
assert.match(settingLibrary, /isBatchAcceptableSettingChange/)
assert.match(settingLibrary, /async function ensureChangeRiskContext/)
assert.match(
  settingLibrary,
  /await ensureChangeRiskContext\(\)[\s\S]*const events = \[\.\.\.settingStore\.pendingChangeEvents\]/,
  'batch accept must refresh entities before computing pending risk'
)
assert.match(
  settingLibrary,
  /async function markChangeEvent[\s\S]*await ensureChangeRiskContext\(\)[\s\S]*getChangeRisk/,
  'single accept must refresh entities before computing hard-field risk'
)

const riskUtils = readFileSync('frontend/src/utils/settingChangeRisk.js', 'utf8')
assert.ok(
  (riskUtils.match(/isHardSettingField\(/g) || []).length >= 2,
  'isHardSettingField must be used by structural hard-field classification, not only defined'
)

const liveScript = readFileSync('tmp/run_longform_browser_240w_phase1.mjs', 'utf8')
for (const marker of [
  'manual_setting_review_required',
  'hard_conflict_setting_review_required',
  'pendingSettingIds',
  'classification',
  'conflictWarnings',
  'AUTO_RESOLVE_HARD_CONFLICT_SETTINGS',
  '现死去三年',
  '第 ? 章自动识别的设定'
]) {
  assert.match(liveScript, new RegExp(marker.replace(/[?]/g, '\\?')), `live script must include ${marker}`)
}
assert.doesNotMatch(liveScript, /settings_confirmation_timed_out['"]/)
assert.match(
  liveScript,
  /const split = splitSettingEventsByRisk\(pending, settingEntities\)[\s\S]*if \(split\.hardConflicts\.length && split\.batchAcceptable\.length\)/,
  'live script must classify pending settings before clicking batch confirmation'
)

const dbClient = readFileSync('frontend/src/api/db/client.js', 'utf8')
assert.match(dbClient, /accept: \(projectId, eventId, data\) => post\(`\/projects\/\$\{projectId\}\/settings\/change-events\/\$\{eventId\}\/accept`, data\)/)

const settingStore = readFileSync('frontend/src/stores/settingStore.js', 'utf8')
assert.match(settingStore, /async function acceptChangeEvent\(projectId, eventId, options = undefined\)/)
assert.match(settingStore, /api\.settings\.changeEvents\.accept\(projectId, eventId, options\)/)

const settingsBackend = readFileSync('backend/routers/settings_library.py', 'utf8')
assert.match(settingsBackend, /forceHardConflict/)
assert.match(settingsBackend, /hard_conflict_setting_review_required/)
assert.match(settingsBackend, /status_code=409/)
assert.match(settingsBackend, /_collect_hard_setting_conflicts/)

console.log('setting change classification contract tests passed')
