import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

import {
  classifySettingChangeRisk,
  getSettingFieldTier,
  isBatchAcceptableSettingChange,
  isDynamicStateField,
  isHardSettingField,
  isObservedCapabilityField
} from '../frontend/src/utils/settingChangeRisk.js'

function classify(event, profile = {}) {
  return classifySettingChangeRisk(event, {
    existingEntity: {
      entityType: event.entityType || 'character',
      name: event.entityName || '测试实体',
      profile
    }
  })
}

const dynamicSamples = [
  ['profile.location', '青石岭附近荒地', '青石岭废弃矿洞'],
  ['profile.currentGoal', '七日内赶到灵脉矿区丙七号井', '前往丙七号井核实账目被烧真相，同时保护陈三'],
  ['profile.physicalStatus', '左臂星纹灼伤', '左臂星纹灼伤加重，左腿膝盖磕伤肿胀'],
  ['profile.itemStatus', '残页完整', '残页被雨水浸湿，边角烧焦'],
  ['profile.behaviorState', '巡天司尚未公开追捕', '巡天司已对陆沉舟发布悬赏令'],
  ['profile.mentalState', '追查父亲旧案', '追查父亲旧案但开始怀疑纪九']
]

for (const [fieldPath, oldValue, newValue] of dynamicSamples) {
  const risk = classify({
    entityName: '陆沉舟',
    changeType: 'update_entity',
    fieldPath,
    oldValue,
    newValue,
    evidence: '第 2 章定稿后状态提取',
    confidence: 0.9,
    chapterNum: 2
  }, {
    [fieldPath.replace('profile.', '')]: oldValue
  })
  assert.notEqual(risk.classification, 'hard_conflict', `${fieldPath} must not be a hard conflict`)
  assert.equal(risk.fieldTier, 'dynamicState', `${fieldPath} should be dynamicState`)
  assert.equal(isBatchAcceptableSettingChange({ ...risk }), true, `${fieldPath} should be batch acceptable`)
  assert.equal(isDynamicStateField(fieldPath), true, `${fieldPath} should be detected as dynamic state`)
  assert.equal(isHardSettingField(fieldPath), false, `${fieldPath} should not be a hard setting field`)
}

const observedAbility = classifySettingChangeRisk({
  entityName: '星账',
  entityType: 'item',
  changeType: 'update_entity',
  fieldPath: 'profile.ability',
  oldValue: '会记债的账本，只记录活人的代价，每次使用必须付出现实代价，代价随机且不可逆；已展现能力星移，使用后显示下一线索及有效期',
  newValue: '会记债的账本，只记录活人的代价，每次使用必须付出现实代价，代价随机且不可逆；已展现能力星移，使用后显示下一线索及有效期；能主动显示指引文字，且文字浮现时墨迹未干透',
  evidence: '星账浮现“往山谷走。三里有座废弃矿洞，可暂避。”',
  confidence: 0.9,
  chapterNum: 2
}, {
  existingEntity: {
    entityType: 'item',
    name: '星账',
    profile: {
      ability: '会记债的账本，只记录活人的代价，每次使用必须付出现实代价，代价随机且不可逆；已展现能力星移，使用后显示下一线索及有效期'
    }
  }
})
assert.equal(observedAbility.fieldTier, 'observedCapability')
assert.equal(observedAbility.classification, 'reveal_or_refinement')
assert.equal(observedAbility.batchAcceptable, true)
assert.equal(isObservedCapabilityField('profile.ability'), true)
assert.equal(isHardSettingField('profile.ability'), false)

const abilityRuleConflict = classifySettingChangeRisk({
  entityName: '星账',
  entityType: 'item',
  changeType: 'update_entity',
  fieldPath: 'profile.ability',
  oldValue: '只能转移债务，不能伪造或销毁，每次使用必须付出现实代价，代价随机且不可逆，只记录活人的代价',
  newValue: '星账不再需要付出代价，可以伪造和销毁，也可以记录死者债务',
  evidence: '无剧情代价铺垫',
  confidence: 0.9,
  chapterNum: 2
}, {
  existingEntity: {
    entityType: 'item',
    name: '星账',
    profile: {
      ability: '只能转移债务，不能伪造或销毁，每次使用必须付出现实代价，代价随机且不可逆，只记录活人的代价'
    }
  }
})
assert.equal(abilityRuleConflict.fieldTier, 'observedCapability')
assert.equal(abilityRuleConflict.classification, 'hard_conflict')
assert.equal(abilityRuleConflict.batchAcceptable, false)
assert.ok(abilityRuleConflict.whyBlocked)

const hardSamples = [
  ['profile.faction', '青玄宗', '赤焰宗'],
  ['profile.realm', '炼气', '筑基'],
  ['profile.fixedRelationship', '师徒', '仇敌']
]
for (const [fieldPath, oldValue, newValue] of hardSamples) {
  const risk = classify({
    entityName: '林逐',
    changeType: 'update_entity',
    fieldPath,
    oldValue,
    newValue,
    evidence: '无明确剧情证据',
    confidence: 0.8,
    chapterNum: 2
  }, {
    [fieldPath.replace('profile.', '')]: oldValue
  })
  assert.equal(risk.fieldTier, 'hardSetting')
  assert.equal(risk.classification, 'hard_conflict')
  assert.equal(risk.batchAcceptable, false)
  assert.ok(risk.whyBlocked)
}

assert.equal(getSettingFieldTier('profile.location'), 'dynamicState')
assert.equal(getSettingFieldTier('profile.currentGoal'), 'dynamicState')
assert.equal(getSettingFieldTier('profile.physicalStatus'), 'dynamicState')
assert.equal(getSettingFieldTier('profile.itemStatus'), 'dynamicState')
assert.equal(getSettingFieldTier('profile.behaviorState'), 'dynamicState')
assert.equal(getSettingFieldTier('profile.ability'), 'observedCapability')
assert.equal(getSettingFieldTier('profile.faction'), 'hardSetting')
assert.equal(getSettingFieldTier('profile.realm'), 'hardSetting')
assert.equal(getSettingFieldTier('profile.fixedRelationship'), 'hardSetting')

const backend = readFileSync('backend/routers/settings_library.py', 'utf8')
assert.match(backend, /DYNAMIC_STATE_FIELDS/)
assert.match(backend, /OBSERVED_CAPABILITY_FIELDS/)
assert.match(backend, /_field_tier/)
assert.match(backend, /_is_ability_core_conflict/)
assert.match(backend, /_dynamicStateMeta/)
const backendHardFields = backend.match(/HARD_SETTING_FIELDS = \{[\s\S]*?\n\}/)?.[0] || ''
for (const dynamicOrObservedField of [
  'profile.location',
  'profile.currentGoal',
  'profile.physicalStatus',
  'profile.itemStatus',
  'profile.behaviorState',
  'profile.mentalState',
  'profile.ability'
]) {
  assert.ok(
    !backendHardFields.includes(`"${dynamicOrObservedField}"`) && !backendHardFields.includes(`'${dynamicOrObservedField}'`),
    `${dynamicOrObservedField} must not remain in backend HARD_SETTING_FIELDS`
  )
}

const liveScript = readFileSync('tmp/run_longform_browser_240w_phase1.mjs', 'utf8')
assert.match(liveScript, /fieldTier/)
assert.match(liveScript, /whyBlocked/)

console.log('setting field tiers contract tests passed')
