import assert from 'node:assert/strict'
import test from 'node:test'

import {
  BIBLE_PROPOSAL_SCOPES,
  adoptBibleProposal,
  bibleProposalScope,
} from '../../src/application/bible/bibleProposalScopes.js'

const bible = prefix => ({
  premiseAndPromise: `${prefix} promise`,
  worldRules: [{ id: `${prefix}-world`, text: `${prefix} world` }],
  powerOrProgressionSystem: `${prefix} progression`,
  protagonist: `${prefix} protagonist`,
  coreCast: [{ id: `${prefix}-cast`, text: `${prefix} cast` }],
  factions: [{ id: `${prefix}-faction`, text: `${prefix} faction` }],
  longTermConflicts: [{ id: `${prefix}-conflict`, text: `${prefix} conflict` }],
  relationshipDynamics: [{ id: `${prefix}-relationship`, text: `${prefix} relationship` }],
  toneAndNarrativeBoundaries: `${prefix} tone`,
  continuityGuardrails: [{ id: `${prefix}-guardrail`, text: `${prefix} guardrail` }],
  openDesignQuestions: [{ id: `${prefix}-question`, text: `${prefix} question` }],
})

test('proposal scopes are frozen stable keys with Chinese labels and exact field mappings', () => {
  assert.deepEqual(BIBLE_PROPOSAL_SCOPES.map(scope => [scope.key, scope.label, scope.fields]), [
    ['whole', '完整创作圣经', null],
    ['premise', '作品承诺', ['premiseAndPromise']],
    ['world_rules', '世界规则', ['worldRules']],
    ['progression', '力量／成长体系', ['powerOrProgressionSystem']],
    ['core_characters', '主角与核心人物', ['protagonist', 'coreCast']],
    ['factions', '势力', ['factions']],
    ['long_term_conflicts', '长期冲突', ['longTermConflicts']],
    ['relationships', '关系动力', ['relationshipDynamics']],
    ['tone_boundaries', '基调与叙事边界', ['toneAndNarrativeBoundaries']],
    ['continuity_guardrails', '连贯性护栏', ['continuityGuardrails']],
    ['open_questions', '开放设计问题', ['openDesignQuestions']],
  ])
  assert.equal(Object.isFrozen(BIBLE_PROPOSAL_SCOPES), true)
  assert.equal(Object.isFrozen(BIBLE_PROPOSAL_SCOPES[1]), true)
  assert.equal(Object.isFrozen(BIBLE_PROPOSAL_SCOPES[1].fields), true)
  assert.equal(bibleProposalScope('world_rules'), BIBLE_PROPOSAL_SCOPES[2])
  assert.equal(bibleProposalScope('unknown'), null)
})

test('whole adoption returns a deep copy without mutating either input', () => {
  const current = bible('current'); const proposal = bible('proposal')
  const currentBefore = structuredClone(current); const proposalBefore = structuredClone(proposal)
  const adopted = adoptBibleProposal(current, proposal, 'whole')
  assert.deepEqual(adopted, proposal)
  assert.notEqual(adopted, proposal)
  assert.notEqual(adopted.worldRules, proposal.worldRules)
  adopted.worldRules[0].text = 'changed adopted copy'
  assert.deepEqual(current, currentBefore)
  assert.deepEqual(proposal, proposalBefore)
})

test('section adoption copies only mapped fields and rejects unknown scopes', () => {
  const current = bible('current'); const proposal = bible('proposal')
  const adopted = adoptBibleProposal(current, proposal, 'core_characters')
  assert.equal(adopted.protagonist, proposal.protagonist)
  assert.deepEqual(adopted.coreCast, proposal.coreCast)
  assert.equal(adopted.premiseAndPromise, current.premiseAndPromise)
  assert.deepEqual(adopted.worldRules, current.worldRules)
  assert.notEqual(adopted.coreCast, proposal.coreCast)
  assert.notEqual(adopted.worldRules, current.worldRules)
  assert.throws(() => adoptBibleProposal(current, proposal, 'unknown'), TypeError)
})
