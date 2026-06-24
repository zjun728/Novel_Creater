import assert from 'node:assert/strict'

import {
  SETTING_CHANGE_CLASSIFICATIONS,
  SETTING_FIELD_TIERS,
  classifySettingChangeRisk,
  isSummaryChapterFactSupplement
} from '../frontend/src/utils/settingChangeRisk.js'

const oldSummary = '掌控九州灵脉贸易与资源流通的商业联盟，与巡天司、星债会争夺星账控制权。'
const actionSummary = '掌控九州灵脉贸易与资源流通的商业联盟，与巡天司、星债会争夺星账控制权；已派人追踪陆沉舟，试图用父亲下落交换星账。'

assert.equal(
  isSummaryChapterFactSupplement(oldSummary, actionSummary, '第 1 章定稿后抽取：商盟已派人追踪陆沉舟，试图交换星账。'),
  true,
  'organization summary plus chapter action facts should be treated as rehomeable supplement'
)

const risk = classifySettingChangeRisk({
  entityName: '商盟',
  entityType: 'faction',
  changeType: 'update_entity',
  fieldPath: 'summary',
  oldValue: oldSummary,
  newValue: actionSummary,
  evidence: '商盟已派人追踪陆沉舟，试图用父亲下落交换星账。',
  confidence: 0.9,
  chapterNum: 1
}, {
  existingEntity: {
    entityType: 'faction',
    name: '商盟',
    summary: oldSummary,
    profile: {}
  }
})

assert.equal(risk.classification, SETTING_CHANGE_CLASSIFICATIONS.revealOrRefinement)
assert.equal(risk.batchAcceptable, true)
assert.equal(risk.fieldTier, SETTING_FIELD_TIERS.hardSetting)
assert.equal(risk.rehomeTargetField, 'profile.currentActions')
assert.equal(risk.rehomeTargetTier, SETTING_FIELD_TIERS.dynamicState)
assert.match(risk.conflictWarnings.join('\n'), /不覆盖 summary|归位/)

const commaAnchorSummary = '掌控九州灵脉贸易与资源流通的商业联盟，可能通过灵脉账目操纵粮价与修士寿元。'
const commaAnchorIncoming = '掌控九州灵脉贸易与资源流通的商业联盟；已派人追踪陆沉舟，试图用父亲下落交换星账。'
assert.equal(
  isSummaryChapterFactSupplement(commaAnchorSummary, commaAnchorIncoming, '已派人追踪陆沉舟'),
  true,
  'old summary anchor should be preserved when only comma-level stable definition fragment remains'
)

const hardRewrite = classifySettingChangeRisk({
  entityName: '商盟',
  entityType: 'faction',
  changeType: 'update_entity',
  fieldPath: 'summary',
  oldValue: oldSummary,
  newValue: '商盟其实不是商业联盟，而是星债会伪装分部。',
  evidence: '无足够铺垫',
  confidence: 0.9,
  chapterNum: 1
}, {
  existingEntity: {
    entityType: 'faction',
    name: '商盟',
    summary: oldSummary,
    profile: {}
  }
})
assert.equal(hardRewrite.classification, SETTING_CHANGE_CLASSIFICATIONS.hardConflict)
assert.equal(hardRewrite.batchAcceptable, false)

console.log('organization summary action rehome frontend contract tests passed')
