import assert from 'node:assert/strict'
import {
  classifySettingChangeRisk,
  SETTING_CHANGE_CLASSIFICATIONS
} from '../frontend/src/utils/settingChangeRisk.js'

function classify({ entityName, oldValue, newValue, evidence = '' }) {
  return classifySettingChangeRisk(
    {
      entityName,
      fieldPath: 'summary',
      newValue,
      evidence
    },
    { existingValue: oldValue }
  )
}

const placeholderReveal = classify({
  entityName: '木门后老人',
  oldValue: '在矿城西区木门后出现的老人，知道陆沉舟父亲和庚子账，可能是父亲旧识或关键情报源。',
  newValue: '宋怀安，前矿北账务所账房，与陆怀安共事大半年，陆怀安留信物与他，掌握庚子账线索。',
  evidence: '老人拿出陆怀安留下的信物，承认自己叫宋怀安。'
})
assert.equal(placeholderReveal.classification, SETTING_CHANGE_CLASSIFICATIONS.revealOrRefinement)
assert.equal(placeholderReveal.batchAcceptable, true)

const codenameReveal = classify({
  entityName: '青先生',
  oldValue: '自称青先生的神秘联络人，身份不明，可能掌握巡天司内部线索。',
  newValue: '青先生其实是徐正清，巡天司主簿，曾用青先生身份暗中递送线索。',
  evidence: '青先生留下徐正清私印，信尾写明真实身份。'
})
assert.equal(codenameReveal.classification, SETTING_CHANGE_CLASSIFICATIONS.revealOrRefinement)
assert.equal(codenameReveal.batchAcceptable, true)

const mistakenClaim = classify({
  entityName: '黑衣人',
  oldValue: '夜里出现的黑衣人，身份不明。',
  newValue: '众人以为黑衣人是陆长庚，但尚无证据确认。',
  evidence: '有人说背影像陆长庚。'
})
assert.equal(mistakenClaim.classification, SETTING_CHANGE_CLASSIFICATIONS.revealOrRefinement)
assert.equal(mistakenClaim.identityAction, 'record_identity_claim')
assert.equal(mistakenClaim.rehomeTargetField, 'profile.identityClaims')

const mistakenDisproved = classify({
  entityName: '黑衣人',
  oldValue: '夜里出现的黑衣人，身份不明。',
  newValue: '黑衣人不是陆长庚，脚步与身形证据已排除陆长庚。',
  evidence: '陆长庚同时在巡天司衙门留有记录。'
})
assert.equal(mistakenDisproved.classification, SETTING_CHANGE_CLASSIFICATIONS.revealOrRefinement)
assert.equal(mistakenDisproved.identityAction, 'record_mistaken_identity')
assert.equal(mistakenDisproved.rehomeTargetField, 'profile.mistakenIdentities')

const hardRewrite = classify({
  entityName: '徐正清',
  oldValue: '徐正清是巡天司主簿，负责北城账册归档。',
  newValue: '徐正清是星债会会主，负责追杀陆沉舟。',
  evidence: ''
})
assert.equal(hardRewrite.classification, SETTING_CHANGE_CLASSIFICATIONS.hardConflict)

console.log('identity setting change risk contract passed')
