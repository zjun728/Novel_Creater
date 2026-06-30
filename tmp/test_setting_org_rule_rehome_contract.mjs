import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import {
  classifySettingChangeRisk,
  isBatchAcceptableSettingChange,
  SETTING_CHANGE_CLASSIFICATIONS
} from '../frontend/src/utils/settingChangeRisk.js'

const OLD_SUMMARY = '一个与星账、阵眼玉相关的神秘组织，陆沉舟母亲曾与之有关，陆沉舟需替母亲还一笔旧债给北街七号的沈姓债主。'
const RULE_SUMMARY = '神秘组织，记录活人债务，以铜扣和欠条为凭证，不与外人做交易，有严格规矩。'
const RULE_EVIDENCE = '星债会不对外人开放。铜扣是你的通行证，但星账是活人的债本。带着债本进去，等于把外面的债带进门里。会里不认这个。'

const ruleRisk = classifySettingChangeRisk({
  entityName: '星债会',
  entityType: 'faction',
  changeType: 'update_entity',
  fieldPath: 'summary',
  oldValue: '',
  newValue: RULE_SUMMARY,
  evidence: RULE_EVIDENCE,
  confidence: 0.9,
  chapterNum: 68
}, {
  existingEntity: {
    entityType: 'faction',
    name: '星债会',
    summary: OLD_SUMMARY,
    profile: {}
  }
})

assert.equal(ruleRisk.classification, SETTING_CHANGE_CLASSIFICATIONS.revealOrRefinement)
assert.equal(ruleRisk.batchAcceptable, true)
assert.equal(isBatchAcceptableSettingChange(ruleRisk), true)
assert.equal(ruleRisk.rehomeTargetField, 'profile.internalMechanisms')
assert.equal(ruleRisk.rehomeTargetTier, 'dynamicState')
assert.ok(ruleRisk.conflictWarnings.some(item => item.includes('组织规则') || item.includes('准入')))
assert.doesNotMatch(ruleRisk.whyBlocked || '', /硬设定字段/)

const hardNegation = classifySettingChangeRisk({
  entityName: '星债会',
  entityType: 'faction',
  changeType: 'update_entity',
  fieldPath: 'summary',
  oldValue: '',
  newValue: '星债会已与星账、阵眼玉、陆沉舟母亲旧债无关，只是茶楼里临时起名的无关势力。',
  evidence: '无规则揭示，只是否定旧记录。',
  confidence: 0.9,
  chapterNum: 68
}, {
  existingEntity: {
    entityType: 'faction',
    name: '星债会',
    summary: OLD_SUMMARY,
    profile: {}
  }
})

assert.equal(hardNegation.classification, SETTING_CHANGE_CLASSIFICATIONS.hardConflict)
assert.equal(hardNegation.batchAcceptable, false)
assert.ok(hardNegation.conflictWarnings.some(item => item.includes('硬设定字段') || item.includes('硬改')))

const frontendSource = readFileSync('frontend/src/utils/settingChangeRisk.js', 'utf8')
assert.match(frontendSource, /ORG_RULE_SUMMARY_REHOME_FIELD/)
assert.match(frontendSource, /isOrgRuleSummaryRefinement/)

const backendSource = readFileSync('backend/routers/settings_library.py', 'utf8')
assert.match(backendSource, /ORG_RULE_SUMMARY_REHOME_FIELD/)
assert.match(backendSource, /_is_org_rule_summary_refinement/)
assert.match(backendSource, /_rehome_org_rule_summary_update/)

console.log('setting org rule rehome contract passed')
