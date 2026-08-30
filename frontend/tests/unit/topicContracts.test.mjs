import assert from 'node:assert/strict'
import test from 'node:test'

import {
  candidatePresentation,
  parseAssistantResult,
  parseHandoff,
  parseSavedCandidate,
} from '../../src/application/topics/topicContracts.js'

const candidate = {
  title: '典镇山河', genre: '东方奇幻', logline: '典吏以文契镇守山河。',
  targetAudience: '男频长篇读者', protagonist: '县衙典吏', desire: '守住故乡',
  coreConflict: '豪强争权', worldPressure: '妖灾逼近', openingHook: '山神索命',
  differentiation: '治理推动成长', storyPromise: '重定山河',
  longFormPotential: '五级递进', marketBasis: '公开榜单仅作兴趣依据',
}

test('assistant and candidate contracts reject missing and extra provider fields', () => {
  const valid = { reply: '继续收束。', directionSuggestions: [], candidateSuggestions: [candidate] }
  assert.equal(parseAssistantResult(valid).candidateSuggestions[0].title, '典镇山河')
  assert.throws(() => parseAssistantResult({ ...valid, provider: 'private' }), /Invalid/)
  assert.throws(() => parseAssistantResult({ reply: '缺字段' }), /Invalid/)
  assert.throws(() => parseSavedCandidate({
    candidateId: 'c1', versionId: 'v1', version: 1, contentHash: 'x'.repeat(64),
    payload: candidate, basis: {},
  }), /Invalid/)
})

test('handoff can only return an unselected revision-zero seed', () => {
  const value = {
    project: { id: 'p1', title: '典镇山河' },
    seed: { id: 's1', revision: 1, isSelected: false, selectionRevision: 0 },
    handoff: { candidateId: 'c1', version: 2 },
  }
  assert.equal(parseHandoff(value).project.title, '典镇山河')
  assert.throws(() => parseHandoff({
    ...value, seed: { ...value.seed, isSelected: true },
  }), /Invalid/)
})

test('presentation keeps Chinese author text but omits hashes and basis', () => {
  const view = candidatePresentation({
    candidateId: 'c1', versionId: 'v1', version: 1,
    contentHash: 'a'.repeat(64), payload: candidate, basis: { private: 'hidden' },
  })
  assert.deepEqual(view, {
    id: 'c1', version: 1, title: '典镇山河', genre: '东方奇幻',
    logline: '典吏以文契镇守山河。',
  })
  assert.equal(JSON.stringify(view).includes('contentHash'), false)
})
