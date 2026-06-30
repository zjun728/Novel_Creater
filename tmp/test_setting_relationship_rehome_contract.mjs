import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import {
  classifySettingChangeRisk,
  isBatchAcceptableSettingChange
} from '../frontend/src/utils/settingChangeRisk.js'
import { buildRelationshipRehomeAudit } from './audit_setting_relationship_rehome_generalized.mjs'

const relationshipPending = {
  id: 'event-lcz-star-debt',
  entityName: '陆沉舟_星债会',
  entityType: 'character',
  changeType: 'relationship',
  fieldPath: 'relationship',
  classification: 'low_risk_update',
  pendingHardConflicts: [],
  newValue: JSON.stringify({
    targetEntityName: '星债会',
    targetEntityType: 'faction',
    relationType: '债务',
    stance: '中立',
    summary: '陆沉舟通过铜扣继承了父亲陆长庚欠星债会的一次问询权，本章已使用该权利，下次仍需偿还。'
  }),
  evidence: '铜扣和口令只能换来试账资格，不是直接取物。',
  confidence: 0.8
}

const risk = classifySettingChangeRisk(relationshipPending, {
  existingEntity: {
    entityType: 'character',
    name: '陆沉舟_星债会',
    summary: '第 68 章自动识别的设定',
    tags: ['AI识别'],
    profile: {}
  }
})
assert.equal(risk.classification, 'low_risk_update')
assert.equal(isBatchAcceptableSettingChange(relationshipPending), true)
assert.equal(risk.conflictWarnings.some(item => item.includes('硬冲突')), false)

const liveScript = readFileSync('tmp/run_longform_browser_240w_phase1.mjs', 'utf8')
const contextBuilder = readFileSync('frontend/src/utils/contextBuilder.js', 'utf8')
const fixScript = readFileSync('tmp/fix_setting_relationship_rehome_generalized.mjs', 'utf8')

const threeSegmentAudit = buildRelationshipRehomeAudit({
  entities: [
    { id: 'e-bad', name: '缺指男人_陆沉舟_新威胁', entityType: 'character', status: 'active' },
    { id: 'e-lcz', name: '陆沉舟', entityType: 'character', status: 'active' }
  ],
  relations: [
    {
      id: 'r-threat',
      sourceEntityId: 'e-bad',
      targetEntityId: 'e-lcz',
      relationType: '威胁',
      status: 'active',
      summary: '缺指男人对陆沉舟发出新的威胁。'
    }
  ]
})
assert.equal(threeSegmentAudit.activeSyntheticRelationCount, 1, 'three-segment A_B_event relation names must be audited as synthetic')
assert.match(
  liveScript,
  /relationship_auto_confirm_failed/,
  'low-risk relationship pending should report auto-confirm failure instead of generic manual review'
)
assert.match(
  liveScript,
  /detectUnconfirmedAutoAcceptableRelationshipSettings/,
  'live runner should distinguish stuck low-risk relationship pending from true manual review'
)
assert.doesNotMatch(
  liveScript,
  /仍有硬冲突设定[\s\S]{0,160}pendingHardConflicts:\s*\[\]/,
  'reports must not say hard conflict remains when pendingHardConflicts is empty'
)
assert.match(
  contextBuilder,
  /isSyntheticRelationPlaceholderEntity/,
  'context builder should filter synthetic relationship placeholders from entity summaries'
)
assert.match(
  contextBuilder,
  /sourceEntityId && r\.sourceEntityId === r\.targetEntityId/,
  'context builder should not output active self relations into prompt context'
)
assert.match(
  fixScript,
  /eventQualifier|syntheticQualifier|qualifier/,
  'fix script should preserve the third segment as event qualifier, not as a person name'
)

console.log('setting relationship rehome frontend/live contract passed')
