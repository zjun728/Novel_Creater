import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

import {
  SETTING_CHANGE_CLASSIFICATIONS,
  SETTING_FIELD_TIERS,
  classifySettingChangeRisk,
  getSettingFieldTier,
  isBatchAcceptableSettingChange,
  isHardSettingField,
  isPlaceholderSummary
} from '../frontend/src/utils/settingChangeRisk.js'

const officialOrgSummary = '巡天司是大靖朝廷设立的官方机构，负责巡查九州异象、缉拿违规修士，并掌握部分旧档案。'
const officialOrgWithChapterFacts = '巡天司是大靖朝廷设立的官方机构，负责巡查九州异象、缉拿违规修士，并掌握部分旧档案。第 2 章揭示其存在内部处决机制，司主正在追捕陆沉舟，方鹤暗中帮助陆沉舟。'
const secretOrgSummary = '星债会是围绕星账债务运转的秘密组织，暗中收集债务线索并操纵欠债者。'
const secretOrgWithClues = '星债会是围绕星账债务运转的秘密组织，暗中收集债务线索并操纵欠债者。第 2 章新增线索：陆父曾调查星债会，铜牌与暗号可接触其外围。'
const descriptivePlaceholderSummary = '在矿城西区木门后出现的老人，知道陆沉舟父亲和庚子账，主动引陆沉舟进入，可能是父亲旧识或关键情报源。'
const formalIdentitySummary = '宋怀安，前矿北账务所账房，与陆怀安共事大半年，陆怀安留信物与他，掌握庚子账线索。'

assert.equal(isPlaceholderSummary('第 1 章自动识别的设定'), true)
assert.equal(isPlaceholderSummary('第 ? 章自动识别的设定'), true)
assert.equal(isPlaceholderSummary(''), true)

const placeholderCompletionRisk = classifySettingChangeRisk({
  entityName: '陆远之',
  entityType: 'character',
  changeType: 'update_entity',
  fieldPath: 'summary',
  oldValue: '第 1 章自动识别的设定',
  newValue: '陆远之是陆沉舟的父亲，三年前在北境灵脉矿场案中失踪，名籍被巡天司封存，疑似与星账旧债有关。',
  evidence: '第 2 章定稿后设定补全',
  confidence: 0.9,
  chapterNum: 2
}, {
  existingEntity: {
    entityType: 'character',
    name: '陆远之',
    summary: '第 1 章自动识别的设定',
    firstChapter: 1,
    tags: ['AI识别'],
    profile: {}
  }
})
assert.equal(placeholderCompletionRisk.fieldTier, SETTING_FIELD_TIERS.hardSetting)
assert.equal(placeholderCompletionRisk.classification, SETTING_CHANGE_CLASSIFICATIONS.revealOrRefinement)
assert.equal(placeholderCompletionRisk.batchAcceptable, true)
assert.equal(isBatchAcceptableSettingChange(placeholderCompletionRisk), true)

const identityRevealRisk = classifySettingChangeRisk({
  entityName: '木门后老人',
  entityType: 'character',
  changeType: 'update_entity',
  fieldPath: 'summary',
  oldValue: descriptivePlaceholderSummary,
  newValue: formalIdentitySummary,
  evidence: '老人承认自己叫宋怀安，曾任矿北账务所账房，并拿出陆怀安留下的信物。',
  confidence: 0.9,
  chapterNum: 8
}, {
  existingEntity: {
    entityType: 'character',
    name: '木门后老人',
    summary: descriptivePlaceholderSummary,
    aliases: [],
    profile: {}
  }
})
assert.equal(identityRevealRisk.classification, SETTING_CHANGE_CLASSIFICATIONS.revealOrRefinement)
assert.equal(identityRevealRisk.batchAcceptable, true)
assert.equal(identityRevealRisk.fieldTier, SETTING_FIELD_TIERS.hardSetting)
assert.match(identityRevealRisk.conflictWarnings.join('\n'), /身份揭示|正式姓名|aliases/)

const stableNameRewriteRisk = classifySettingChangeRisk({
  entityName: '陆远之',
  entityType: 'character',
  changeType: 'update_entity',
  fieldPath: 'summary',
  oldValue: '陆远之，陆沉舟的父亲，曾任巡天司星吏，三年前在北境矿案后失踪。',
  newValue: '宋怀安，前矿北账务所账房，与陆怀安共事大半年，掌握庚子账线索。',
  evidence: '无伪装、化名或误认证据。',
  confidence: 0.9,
  chapterNum: 8
}, {
  existingEntity: {
    entityType: 'character',
    name: '陆远之',
    summary: '陆远之，陆沉舟的父亲，曾任巡天司星吏，三年前在北境矿案后失踪。',
    aliases: [],
    profile: {}
  }
})
assert.equal(stableNameRewriteRisk.classification, SETTING_CHANGE_CLASSIFICATIONS.hardConflict)
assert.equal(stableNameRewriteRisk.batchAcceptable, false)

for (const [oldValue, newValue, entityName] of [
  [officialOrgSummary, officialOrgWithChapterFacts, '巡天司'],
  [secretOrgSummary, secretOrgWithClues, '星债会']
]) {
  const risk = classifySettingChangeRisk({
    entityName,
    entityType: 'faction',
    changeType: 'update_entity',
    fieldPath: 'summary',
    oldValue,
    newValue,
    evidence: '第 2 章定稿后设定抽取：章节揭示、行动、线索、内部机制',
    confidence: 0.9,
    chapterNum: 2
  }, {
    existingEntity: {
      entityType: 'faction',
      name: entityName,
      summary: oldValue,
      profile: {}
    }
  })
  assert.equal(risk.classification, SETTING_CHANGE_CLASSIFICATIONS.revealOrRefinement)
  assert.equal(risk.batchAcceptable, true)
  assert.equal(risk.fieldTier, SETTING_FIELD_TIERS.hardSetting)
  assert.equal(risk.rehomeTargetField, 'profile.observedFacts')
  assert.equal(risk.rehomeTargetTier, SETTING_FIELD_TIERS.dynamicState)
  assert.match(risk.conflictWarnings.join('\n'), /不覆盖 summary|归位/)
}

const factionBehaviorRisk = classifySettingChangeRisk({
  entityName: '方鹤',
  entityType: 'character',
  changeType: 'update_entity',
  fieldPath: 'profile.faction',
  oldValue: '巡天司',
  newValue: '巡天司（见习吏，但暗中帮助陆沉舟）',
  evidence: '方鹤表面隶属巡天司，暗中帮助陆沉舟离开追捕现场。',
  confidence: 0.9,
  chapterNum: 2
}, {
  existingEntity: {
    entityType: 'character',
    name: '方鹤',
    profile: { faction: '巡天司' }
  }
})
assert.equal(factionBehaviorRisk.classification, SETTING_CHANGE_CLASSIFICATIONS.revealOrRefinement)
assert.equal(factionBehaviorRisk.batchAcceptable, true)
assert.equal(factionBehaviorRisk.fieldTier, SETTING_FIELD_TIERS.hardSetting)
assert.equal(factionBehaviorRisk.rehomeTargetField, 'profile.hiddenStance')
assert.equal(factionBehaviorRisk.rehomeTargetTier, SETTING_FIELD_TIERS.dynamicState)

for (const fieldPath of [
  'profile.observedFacts',
  'profile.revealedClues',
  'profile.currentActions',
  'profile.internalMechanisms',
  'profile.chapterEvidence',
  'profile.hiddenStance',
  'profile.currentAction'
]) {
  assert.equal(getSettingFieldTier(fieldPath), SETTING_FIELD_TIERS.dynamicState, `${fieldPath} should be dynamicState`)
  assert.equal(isHardSettingField(fieldPath), false, `${fieldPath} should not be hardSetting`)
}

const orgRewriteRisk = classifySettingChangeRisk({
  entityName: '巡天司',
  entityType: 'faction',
  changeType: 'update_entity',
  fieldPath: 'summary',
  oldValue: officialOrgSummary,
  newValue: '巡天司其实不是官方机构，而是商盟在朝廷外伪造的分部，根本目标是掩盖星账交易。',
  evidence: '无足够铺垫',
  confidence: 0.9,
  chapterNum: 2
}, {
  existingEntity: {
    entityType: 'faction',
    name: '巡天司',
    summary: officialOrgSummary,
    profile: {}
  }
})
assert.equal(orgRewriteRisk.classification, SETTING_CHANGE_CLASSIFICATIONS.hardConflict)
assert.equal(orgRewriteRisk.batchAcceptable, false)

const secretOrgRewriteRisk = classifySettingChangeRisk({
  entityName: '星债会',
  entityType: 'faction',
  changeType: 'update_entity',
  fieldPath: 'summary',
  oldValue: secretOrgSummary,
  newValue: '星债会不再是秘密组织，而是公开官署，负责正式登记所有星账债务。',
  evidence: '无足够铺垫',
  confidence: 0.9,
  chapterNum: 2
}, {
  existingEntity: {
    entityType: 'faction',
    name: '星债会',
    summary: secretOrgSummary,
    profile: {}
  }
})
assert.equal(secretOrgRewriteRisk.classification, SETTING_CHANGE_CLASSIFICATIONS.hardConflict)

const factionRewriteRisk = classifySettingChangeRisk({
  entityName: '方鹤',
  entityType: 'character',
  changeType: 'update_entity',
  fieldPath: 'profile.faction',
  oldValue: '巡天司',
  newValue: '商盟',
  evidence: '无隐藏/伪装语义',
  confidence: 0.9,
  chapterNum: 2
}, {
  existingEntity: {
    entityType: 'character',
    name: '方鹤',
    profile: { faction: '巡天司' }
  }
})
assert.equal(factionRewriteRisk.classification, SETTING_CHANGE_CLASSIFICATIONS.hardConflict)
assert.equal(factionRewriteRisk.batchAcceptable, false)

const frontendRiskSource = readFileSync('frontend/src/utils/settingChangeRisk.js', 'utf8')
const backendSettingsSource = readFileSync('backend/routers/settings_library.py', 'utf8')
assert.match(frontendRiskSource, /SUMMARY_CHAPTER_FACT_REHOME_FIELD[\s\S]*profile\.observedFacts/)
assert.match(frontendRiskSource, /HARD_FIELD_BEHAVIOR_REHOME_FIELD[\s\S]*profile\.hiddenStance/)
assert.match(frontendRiskSource, /isDescriptivePlaceholderIdentityReveal/)
assert.match(backendSettingsSource, /SUMMARY_CHAPTER_FACT_REHOME_FIELD[\s\S]*profile\.observedFacts/)
assert.match(backendSettingsSource, /HARD_FIELD_BEHAVIOR_REHOME_FIELD[\s\S]*profile\.hiddenStance/)
assert.match(backendSettingsSource, /_is_descriptive_placeholder_identity_reveal/)

console.log('setting summary write policy frontend contract tests passed')
