import assert from 'node:assert/strict'
import test from 'node:test'

import { contractDocumentSections } from '../../src/application/contracts/contractDocumentSections.js'

const HASH = 'a'.repeat(64)

function payload(overrides = {}) {
  return {
    engineOptionId: 'engine-1',
    engineHash: HASH,
    channelProfileKey: 'xuanhuan',
    genreProfileKey: 'fantasy',
    qualityCharterVersion: 'story-first-quality-v1',
    targetTotalWords: 1_200_000,
    expectedVolumeCount: 6,
    expectedChapterCount: 400,
    chapterWordRangePreference: [2_800, 3_400],
    prohibitedDirections: ['不写无代价升级'],
    authorNotes: '人物选择优先。',
    primaryStyleRef: { id: 'style-1', revision: 1, contentHash: HASH },
    secondaryStyleRef: null,
    likes: ['有代价的成长'],
    dislikes: ['机械反转'],
    experienceCardRefs: [],
    corpusSourceRefs: [],
    ...overrides,
  }
}

function map(state = {}) {
  return contractDocumentSections({
    draftVersion: 7,
    payload: payload(),
    ...state,
  })
}

function section(result, key) {
  const value = result.sections.find(item => item.key === key)
  assert.ok(value, `missing ${key} section`)
  return value
}

test('always returns the six author document sections with a CAS-only version label', () => {
  const result = map()

  assert.deepEqual(result.sections.map(item => item.key), [
    'engine', 'capacity', 'assets', 'style', 'prohibitions', 'preview',
  ])
  assert.ok(result.sections.every(item => item.visible === true))
  assert.equal(result.draftVersion.label, '并发版本')
  assert.equal(result.draftVersion.value, 7)
  assert.doesNotMatch(result.draftVersion.label, /历史版本/)
})

test('saved stages preserve the existing engine, style, and assets max-open progression', () => {
  const cases = [
    ['engine', ['engine', 'style']],
    ['style', ['engine', 'assets', 'style']],
    ['assets', ['engine', 'capacity', 'assets', 'style', 'prohibitions', 'preview']],
  ]

  for (const [draftStage, expectedOpen] of cases) {
    const result = map({ draftStage })
    assert.deepEqual(
      result.sections.filter(item => item.open).map(item => item.key),
      expectedOpen,
      `${draftStage} must preserve its contractStepAccess max-open boundary`,
    )
    assert.deepEqual(
      result.sections.filter(item => item.writeFields.length).map(item => item.key),
      expectedOpen.filter(key => key !== 'preview'),
      `${draftStage} must expose writes only for the existing open steps`,
    )
  }
})

test('an assets draft opens asset fields and the final server preview', () => {
  const result = map({
    draftStage: 'assets',
    serverCanConfirm: true,
    readiness: { ready: true, reasons: [] },
  })

  assert.equal(section(result, 'assets').open, true)
  assert.deepEqual(section(result, 'assets').writeFields, [
    'experienceCardRefs', 'corpusSourceRefs',
  ])
  assert.deepEqual(section(result, 'capacity').writeFields, [
    'targetTotalWords', 'expectedVolumeCount', 'expectedChapterCount',
    'chapterWordRangePreference', 'authorNotes',
  ])
  assert.deepEqual(section(result, 'prohibitions').writeFields, ['prohibitedDirections'])
  assert.equal(section(result, 'preview').open, true)
  assert.equal(section(result, 'preview').canPreview, true)
  assert.equal(section(result, 'preview').canConfirm, true)
})

test('selection drift keeps an assets draft engine-only without preview or confirmation', () => {
  const result = map({
    draftStage: 'assets',
    selectionDrift: true,
    serverCanConfirm: true,
  })

  assert.deepEqual(result.sections.filter(item => item.open).map(item => item.key), ['engine'])
  assert.deepEqual(result.sections.filter(item => item.writeFields.length).map(item => item.key), ['engine'])
  assert.equal(section(result, 'preview').canPreview, false)
  assert.equal(section(result, 'preview').canConfirm, false)
})

test('only server capability, reasons, or validation can block a section', () => {
  const locallyDrifted = map({
    draftStage: 'assets',
    selectionDrift: true,
    readiness: { ready: true, reasons: [] },
  })
  assert.ok(locallyDrifted.sections.every(item => item.status !== 'blocked'))

  const serverBlocked = map({
    draftStage: 'assets',
    capabilities: { edit: false },
    readiness: { ready: false, reasons: ['seed_drift'] },
    validation: { reasons: ['contract_invalid'] },
  })
  for (const item of serverBlocked.sections) {
    assert.equal(item.status, 'blocked')
    assert.deepEqual(item.blockedReasons, ['seed_drift', 'contract_invalid'])
  }
})

test('filled and suggested sections remain display-only and cannot grant confirmation', () => {
  const result = map({
    draftStage: 'engine',
    payload: payload({
      primaryStyleRef: null,
      likes: null,
      dislikes: null,
      experienceCardRefs: null,
      corpusSourceRefs: null,
    }),
  })

  assert.equal(section(result, 'engine').status, 'filled')
  assert.equal(section(result, 'assets').status, 'suggested')
  assert.ok(result.sections.every(item => item.canConfirm === false))
})

test('section values are recursively detached from the mutable Contract payload', () => {
  const source = payload({
    primaryStyleRef: { id: 'style-1', revision: 1, contentHash: HASH },
    experienceCardRefs: [{ id: 'card-1', revision: 1, contentHash: HASH }],
    likes: ['有代价的成长'],
  })
  const result = map({ payload: source })

  section(result, 'style').values.primaryStyleRef.id = 'mutated-style'
  section(result, 'assets').values.experienceCardRefs[0].id = 'mutated-card'
  section(result, 'style').values.likes.push('mutated-like')

  assert.equal(source.primaryStyleRef.id, 'style-1')
  assert.equal(source.experienceCardRefs[0].id, 'card-1')
  assert.deepEqual(source.likes, ['有代价的成长'])
})

test('explicit server confirmation capability is fail-closed over conflicting fallbacks', () => {
  const result = map({
    draftStage: 'assets',
    serverCanConfirm: false,
    capabilities: { confirm: true },
    readiness: { canConfirm: true, reasons: [] },
  })
  const capabilityFalse = map({
    draftStage: 'assets',
    capabilities: { confirm: false },
    readiness: { canConfirm: true, reasons: [] },
  })

  assert.equal(section(result, 'preview').canConfirm, false)
  assert.equal(section(capabilityFalse, 'preview').canConfirm, false)
})

test('malformed own confirmation properties deny instead of falling through', () => {
  const cases = [
    {
      name: 'null server capability',
      state: { serverCanConfirm: null, capabilities: { confirm: true }, readiness: { canConfirm: true } },
    },
    {
      name: 'undefined server capability',
      state: { serverCanConfirm: undefined, capabilities: { confirm: true }, readiness: { canConfirm: true } },
    },
    {
      name: 'string server capability',
      state: { serverCanConfirm: 'true', capabilities: { confirm: true }, readiness: { canConfirm: true } },
    },
    {
      name: 'null nested capability',
      state: { capabilities: { confirm: null }, readiness: { canConfirm: true } },
    },
    {
      name: 'string nested capability',
      state: { capabilities: { confirm: 'true' }, readiness: { canConfirm: true } },
    },
    {
      name: 'undefined readiness capability',
      state: { readiness: { canConfirm: undefined } },
    },
  ]

  for (const { name, state } of cases) {
    assert.equal(section(map({ draftStage: 'assets', ...state }), 'preview').canConfirm, false, name)
  }
})

test('confirmation falls back only when the higher-priority property is absent', () => {
  assert.equal(section(map({
    draftStage: 'assets',
    capabilities: { confirm: true },
  }), 'preview').canConfirm, true)
  assert.equal(section(map({
    draftStage: 'assets',
    readiness: { canConfirm: true },
  }), 'preview').canConfirm, true)
})

test('non-object states produce a safe document shell without confirmation', () => {
  for (const state of [null, undefined, 'invalid', 7]) {
    const result = contractDocumentSections(state)
    assert.equal(result.sections.length, 6)
    assert.equal(result.draftVersion.value, null)
    assert.ok(result.sections.every(item => item.visible && !item.canConfirm))
  }
})

test('draft version accepts only backend-issued positive integers', () => {
  for (const value of [null, '', '7', -1, 0]) {
    assert.equal(map({ draftVersion: value }).draftVersion.value, null, String(value))
  }
  assert.equal(map({ draftVersion: 7 }).draftVersion.value, 7)
  assert.equal(contractDocumentSections({
    draftVersion: 0,
    draft: { draftVersion: 7, draft: payload() },
  }).draftVersion.value, null)
})
