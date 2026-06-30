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
const minerCreditorOldSummary = '自称替陆沉舟父亲收债的神秘矿工，可能掌握父亲债务的细节或与玉虚峰矿山的交易内幕，后续可能引导调查或成为敌对。'
const minerCreditorNewSummary = '自称替私人债主收债的玉虚峰丙七矿区矿工，曾是陆沉舟父亲的跟班矿工，认识巡天司北城执事赵鹤，知道星账在陆沉舟手中，并提供了逃跑路线和欠条。'
const minerCreditorEvidence = '“我给他当了两年跟班矿工。”“我不是债主——我是来替他收债的。”“你认识赵鹤？”“你爹生前跟我说过那本账。”'

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

const backgroundRevealRisk = classifySettingChangeRisk({
  entityName: '矿山债主',
  entityType: 'character',
  changeType: 'update_entity',
  fieldPath: 'summary',
  oldValue: minerCreditorOldSummary,
  newValue: minerCreditorNewSummary,
  evidence: minerCreditorEvidence,
  confidence: 0.9,
  chapterNum: 2
}, {
  existingEntity: {
    entityType: 'character',
    name: '矿山债主',
    summary: minerCreditorOldSummary,
    aliases: [],
    profile: {}
  }
})
assert.equal(backgroundRevealRisk.classification, SETTING_CHANGE_CLASSIFICATIONS.revealOrRefinement)
assert.equal(backgroundRevealRisk.batchAcceptable, true)
assert.equal(backgroundRevealRisk.fieldTier, SETTING_FIELD_TIERS.hardSetting)
assert.doesNotMatch(backgroundRevealRisk.whyBlocked || '', /硬设定字段/)
assert.match(backgroundRevealRisk.conflictWarnings.join('\n'), /身份|背景|线索|揭示|旧设定细化/)

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

const affiliationRevealRisk = classifySettingChangeRisk({
  entityName: '剔牙男人',
  entityType: 'character',
  changeType: 'update_entity',
  fieldPath: 'profile.faction',
  oldValue: '与缺指男人同一势力',
  newValue: '巡天司（暗哨）',
  evidence: '剔牙男人拿出巡天司暗哨令牌。',
  confidence: 0.86,
  chapterNum: 43
}, {
  existingEntity: {
    entityType: 'character',
    name: '剔牙男人',
    profile: { faction: '与缺指男人同一势力' }
  }
})
assert.equal(affiliationRevealRisk.classification, SETTING_CHANGE_CLASSIFICATIONS.revealOrRefinement)
assert.equal(affiliationRevealRisk.batchAcceptable, true)
assert.equal(affiliationRevealRisk.fieldTier, SETTING_FIELD_TIERS.hardSetting)
assert.equal(affiliationRevealRisk.rehomeTargetField, 'profile.hiddenAffiliation')
assert.equal(affiliationRevealRisk.rehomeTargetTier, SETTING_FIELD_TIERS.dynamicState)
assert.doesNotMatch(affiliationRevealRisk.whyBlocked || '', /硬设定字段/)

const unknownFactionRevealRisk = classifySettingChangeRisk({
  entityName: '缺指男人',
  entityType: 'character',
  changeType: 'update_entity',
  fieldPath: 'profile.faction',
  oldValue: '未知势力，可能与巡天司或商盟有关',
  newValue: '巡天司',
  evidence: '缺指男人指挥巡天司暗哨设伏，瘦高个巡天司领队听从其命令。',
  confidence: 0.8,
  chapterNum: 44
}, {
  existingEntity: {
    entityType: 'character',
    name: '缺指男人',
    profile: { faction: '未知势力，可能与巡天司或商盟有关' }
  }
})
assert.equal(unknownFactionRevealRisk.classification, SETTING_CHANGE_CLASSIFICATIONS.revealOrRefinement)
assert.equal(unknownFactionRevealRisk.batchAcceptable, true)
assert.equal(unknownFactionRevealRisk.rehomeTargetField, 'profile.hiddenAffiliation')

for (const fieldPath of [
  'profile.observedFacts',
  'profile.revealedClues',
  'profile.currentActions',
  'profile.internalMechanisms',
  'profile.chapterEvidence',
  'profile.hiddenStance',
  'profile.currentAction',
  'profile.affiliationClaims',
  'profile.hiddenAffiliation',
  'profile.currentRole',
  'profile.identityReveal',
  'profile.identityReveals'
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

const stableFactionRewriteRisk = classifySettingChangeRisk({
  entityName: '方鹤',
  entityType: 'character',
  changeType: 'update_entity',
  fieldPath: 'profile.faction',
  oldValue: '巡天司',
  newValue: '星债会核心成员',
  evidence: '无卧底、伪装、暗线或身份揭示证据。',
  confidence: 0.9,
  chapterNum: 43
}, {
  existingEntity: {
    entityType: 'character',
    name: '方鹤',
    profile: { faction: '巡天司' }
  }
})
assert.equal(stableFactionRewriteRisk.classification, SETTING_CHANGE_CLASSIFICATIONS.hardConflict)
assert.equal(stableFactionRewriteRisk.batchAcceptable, false)

const frontendRiskSource = readFileSync('frontend/src/utils/settingChangeRisk.js', 'utf8')
const backendSettingsSource = readFileSync('backend/routers/settings_library.py', 'utf8')
assert.match(frontendRiskSource, /SUMMARY_CHAPTER_FACT_REHOME_FIELD[\s\S]*profile\.observedFacts/)
assert.match(frontendRiskSource, /HARD_FIELD_BEHAVIOR_REHOME_FIELD[\s\S]*profile\.hiddenStance/)
assert.match(frontendRiskSource, /FACTION_AFFILIATION_REVEAL_REHOME_FIELD[\s\S]*profile\.hiddenAffiliation/)
assert.match(frontendRiskSource, /isDescriptivePlaceholderIdentityReveal/)
assert.match(backendSettingsSource, /SUMMARY_CHAPTER_FACT_REHOME_FIELD[\s\S]*profile\.observedFacts/)
assert.match(backendSettingsSource, /HARD_FIELD_BEHAVIOR_REHOME_FIELD[\s\S]*profile\.hiddenStance/)
assert.match(backendSettingsSource, /FACTION_AFFILIATION_REVEAL_REHOME_FIELD[\s\S]*profile\.hiddenAffiliation/)
assert.match(backendSettingsSource, /_is_descriptive_placeholder_identity_reveal/)

console.log('setting summary write policy frontend contract tests passed')
