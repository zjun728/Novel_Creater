import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

import {
  classifySettingChangeRisk,
  getSettingFieldTier,
  isBatchAcceptableSettingChange,
  isHardSettingField
} from '../frontend/src/utils/settingChangeRisk.js'

const oldSummary = '星账只记录活人的代价，每次使用必须付出现实代价，代价不可逆且随次数递增，星账不可复制，只能由持有者主动使用或转让。这是推动剧情和主角选择的核心硬规则。'
const instanceSummary = '星账只记录活人的代价，每次使用必须付出现实代价，代价不可逆且随次数递增（第一次左眼视力三成，第二次右眼视力七成），星账不可复制，只能由持有者主动使用或转让。这是推动剧情和主角选择的核心硬规则。'

const instanceRisk = classifySettingChangeRisk({
  entityName: '星账代价规则',
  entityType: 'power_system',
  changeType: 'update_entity',
  fieldPath: 'summary',
  oldValue: oldSummary,
  newValue: instanceSummary,
  evidence: '陆沉舟欠债一次，代价：左眼视力三成。第二次使用，代价：右眼视力七成',
  confidence: 1,
  chapterNum: 3
}, {
  existingEntity: {
    entityType: 'power_system',
    name: '星账代价规则',
    summary: oldSummary,
    profile: {
      costRule: '代价不可逆且随次数递增；首次使用代价为左眼视力三成，后续代价更严重'
    }
  }
})

assert.equal(instanceRisk.classification, 'reveal_or_refinement')
assert.equal(instanceRisk.batchAcceptable, true)
assert.equal(isBatchAcceptableSettingChange({ ...instanceRisk }), true)
assert.equal(instanceRisk.rehomeTargetField, 'profile.observedCosts')
assert.equal(instanceRisk.rehomeTargetTier, 'dynamicState')
assert.match(instanceRisk.conflictWarnings.join('\n'), /规则实例|已发生代价|不改写 summary/)

for (const field of ['profile.observedCosts', 'profile.costHistory', 'profile.ruleExamples']) {
  assert.notEqual(getSettingFieldTier(field), 'hardSetting', `${field} must not be hardSetting`)
  assert.equal(isHardSettingField(field), false, `${field} must not be a hard setting field`)
}
assert.equal(getSettingFieldTier('profile.observedCosts'), 'dynamicState')

const trueRewriteRisk = classifySettingChangeRisk({
  entityName: '星账代价规则',
  entityType: 'power_system',
  changeType: 'update_entity',
  fieldPath: 'summary',
  oldValue: oldSummary,
  newValue: '星账不再需要付出现实代价，代价可以逆转，也可以复制星账并记录死者代价。',
  evidence: '无明确剧情铺垫',
  confidence: 0.9,
  chapterNum: 3
}, {
  existingEntity: {
    entityType: 'power_system',
    name: '星账代价规则',
    summary: oldSummary,
    profile: {}
  }
})

assert.equal(trueRewriteRisk.classification, 'hard_conflict')
assert.equal(trueRewriteRisk.batchAcceptable, false)
assert.equal(isBatchAcceptableSettingChange(trueRewriteRisk), false)

const frontendRiskSource = readFileSync('frontend/src/utils/settingChangeRisk.js', 'utf8')
const backendSettingsSource = readFileSync('backend/routers/settings_library.py', 'utf8')
assert.match(frontendRiskSource, /RULE_INSTANCE_REHOME_FIELD[\s\S]*profile\.observedCosts/)
assert.match(backendSettingsSource, /RULE_INSTANCE_REHOME_FIELD[\s\S]*profile\.observedCosts/)

console.log('rule instance rehoming frontend contract tests passed')
