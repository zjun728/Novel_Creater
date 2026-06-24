import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

import {
  SETTING_CHANGE_CLASSIFICATIONS,
  SETTING_FIELD_TIERS,
  classifySettingChangeRisk,
  getSettingFieldTier,
  isBatchAcceptableSettingChange,
  isDynamicStateField,
  isHardSettingField
} from '../frontend/src/utils/settingChangeRisk.js'

function classifyOwnerChange({ oldValue, newValue, evidence = '第 3 章定稿后设定提取' }) {
  return classifySettingChangeRisk({
    entityName: '星债总账',
    entityType: 'item',
    changeType: 'update_entity',
    fieldPath: 'profile.owner',
    oldValue,
    newValue,
    evidence,
    confidence: 0.9,
    chapterNum: 3
  }, {
    existingEntity: {
      entityType: 'item',
      name: '星债总账',
      profile: {
        owner: oldValue
      }
    }
  })
}

assert.equal(getSettingFieldTier('profile.owner'), SETTING_FIELD_TIERS.hardSetting)
assert.equal(isHardSettingField('profile.owner'), true)

for (const field of [
  'profile.currentHolder',
  'profile.possessionStatus',
  'profile.custodyState',
  'profile.contactStatus',
  'profile.accessState',
  'holder',
  'currentHolder',
  'possessor',
  'currentPossessor',
  'custody',
  'possessionStatus',
  'contactStatus',
  'accessState'
]) {
  assert.equal(getSettingFieldTier(field), SETTING_FIELD_TIERS.dynamicState, `${field} should be dynamicState`)
  assert.equal(isDynamicStateField(field), true, `${field} should be dynamic`)
  assert.equal(isHardSettingField(field), false, `${field} must not be a hard setting field`)
}

const mixedOldOwnerRisk = classifyOwnerChange({
  oldValue: '未知（陆沉舟已接触但未取出）',
  newValue: '陆沉舟',
  evidence: '陆沉舟已接触星债总账，但章节只证明他接触和取出账册，未证明法理归属转移。'
})
assert.equal(mixedOldOwnerRisk.fieldTier, SETTING_FIELD_TIERS.hardSetting)
assert.equal(mixedOldOwnerRisk.classification, SETTING_CHANGE_CLASSIFICATIONS.revealOrRefinement)
assert.equal(mixedOldOwnerRisk.batchAcceptable, true)
assert.equal(isBatchAcceptableSettingChange(mixedOldOwnerRisk), true)
assert.equal(mixedOldOwnerRisk.rehomeTargetField, 'profile.possessionStatus')
assert.equal(mixedOldOwnerRisk.rehomeTargetTier, SETTING_FIELD_TIERS.dynamicState)
assert.match(mixedOldOwnerRisk.conflictWarnings.join('\n'), /动态持有|接触|不覆盖.*owner/)

const incomingDynamicOwnerRisk = classifyOwnerChange({
  oldValue: '星债会',
  newValue: '陆沉舟已临时持有/已接触未取出',
  evidence: '陆沉舟把星债总账临时藏在身上，只说明当前持有与接触状态。'
})
assert.equal(incomingDynamicOwnerRisk.classification, SETTING_CHANGE_CLASSIFICATIONS.revealOrRefinement)
assert.equal(incomingDynamicOwnerRisk.batchAcceptable, true)
assert.equal(incomingDynamicOwnerRisk.rehomeTargetField, 'profile.possessionStatus')
assert.match(incomingDynamicOwnerRisk.conflictWarnings.join('\n'), /保留.*归属|不覆盖.*owner/)

const stableOwnerConflict = classifyOwnerChange({
  oldValue: '星债会',
  newValue: '陆沉舟',
  evidence: '无转让、夺取、继承或归还等剧情证据。'
})
assert.equal(stableOwnerConflict.classification, SETTING_CHANGE_CLASSIFICATIONS.hardConflict)
assert.equal(stableOwnerConflict.batchAcceptable, false)
assert.match(stableOwnerConflict.whyBlocked, /硬设定字段/)

const stableTransferRisk = classifyOwnerChange({
  oldValue: '星债会',
  newValue: '陆沉舟',
  evidence: '星债会当众将星债总账正式转让给陆沉舟，确认所有权移交。'
})
assert.notEqual(stableTransferRisk.classification, SETTING_CHANGE_CLASSIFICATIONS.hardConflict)
assert.equal(stableTransferRisk.batchAcceptable, true)

const extractionPrompt = readFileSync('frontend/src/prompts/settingExtraction.js', 'utf8')
for (const field of ['profile.currentHolder', 'profile.possessionStatus', 'profile.contactStatus', 'profile.accessState']) {
  assert.match(extractionPrompt, new RegExp(field.replace('.', '\\.')), `setting extraction prompt should expose ${field}`)
}

const backend = readFileSync('backend/routers/settings_library.py', 'utf8')
for (const field of ['profile.currentHolder', 'profile.possessionStatus', 'profile.custodyState', 'profile.contactStatus', 'profile.accessState']) {
  assert.match(backend, new RegExp(field.replace('.', '\\.')), `backend should know ${field}`)
}

console.log('owner possession rehoming frontend contract tests passed')
