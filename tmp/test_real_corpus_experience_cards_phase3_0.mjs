import assert from 'node:assert/strict'

import {
  buildExpressionHelperFromRealCorpusCards,
  retrieveRealCorpusExperienceCards,
  validateRealCorpusExperienceCardsV3
} from '../frontend/src/data/realCorpusExperienceCardsV3.js'
import realCorpusCards from '../frontend/src/data/realCorpusExperienceCards.v3.json' with { type: 'json' }
import {
  assertRealCorpusExperienceCardsReportMatchesJson,
  validateRealCorpusExperienceCardsPayload,
  runRealCorpusExperienceCardsPhase30,
  SYNTHETIC_SCENES
} from './run_real_corpus_experience_cards_phase3_0.mjs'

const payload = await runRealCorpusExperienceCardsPhase30({ writeArtifacts: false })

assert.equal(payload.schemaVersion, 'real-corpus-experience-cards-phase3-0-v1')
assert.equal(payload.boundary.serviceStarted, false)
assert.equal(payload.boundary.realDbConnection, false)
assert.equal(payload.boundary.liveGenerationRun, false)
assert.equal(payload.boundary.projectStateWritten, false)
assert.equal(payload.branch.baseCommit, 'd45a64c')
assert.match(payload.branch.currentBranch, /^codex\/novel-creater-sample-library-v3/)

assert.equal(payload.corpusAudit.localTxt.totalReadable, payload.corpusAudit.localTxt.totalFiles)
assert.ok(payload.corpusAudit.localTxt.totalFiles >= 46, 'should enumerate all local novel txt files')
assert.equal(payload.corpusAudit.localReport.cardCount, 46)
assert.equal(payload.corpusAudit.alignment.reportCoveredSources, 46)
assert.equal(payload.corpusAudit.alignment.reportSourcesWithoutTxt.length, 0)
assert.equal(payload.corpusAudit.alignment.duplicateReportNames.length, 0)
assert.equal(payload.corpusAudit.alignment.duplicateSourceTitles.length, 0)
assert.ok(payload.corpusAudit.alignment.txtFilesWithoutReport.length >= 1, 'extra local txt files should be reported, not ignored')

assert.equal(payload.currentSampleLayer.localReportCards, 46)
assert.equal(payload.currentSampleLayer.builtInMicroDemoCards.total, 28)
assert.equal(payload.currentSampleLayer.directDraftInjectionEnabled, false)
assert.equal(payload.currentSampleLayer.v23ArtifactsPresent, false)

assert.equal(realCorpusCards.schemaVersion, 'real-corpus-experience-cards-v3')
assert.equal(realCorpusCards.cards.length, payload.v3Cards.total)
assert.equal(payload.v3Cards.total, 46)
assert.equal(payload.v3Cards.sourceCoverage.sourcesWithCandidateCards, 46)
assert.deepEqual(payload.v3Cards.sourceCoverage.skippedSources, [])
assert.doesNotThrow(() => validateRealCorpusExperienceCardsV3(realCorpusCards))
assert.ok(realCorpusCards.cards.every(card => /^real-corpus-v3-\d{3}$/.test(card.cardId)), 'card ids must be neutral and source-name free')

const sourceFragmentLeakCard = {
  ...realCorpusCards.cards[0],
  cardId: 'real-corpus-v3-leak-check',
  promptInjectionSafeVersion: `${realCorpusCards.cards[0].promptInjectionSafeVersion} 赛珍珠`
}
assert.throws(
  () => validateRealCorpusExperienceCardsV3({ ...realCorpusCards, cards: [sourceFragmentLeakCard] }),
  /source/i,
  'source title fragments or author/source names must be rejected from prompt-facing fields'
)

for (const tag of [
  'dialogue_conflict',
  'emotion_variation',
  'character_humanity',
  'scene_dwell',
  'setting_naturalization',
  'aftermath',
  'longform_rhythm',
  'action_burst'
]) {
  assert.ok(payload.v3Cards.sceneFunctionTagDistribution[tag] >= 3, `${tag} should have several cards`)
}

const forbiddenPromptKeys = ['rawExcerpt', 'sourceText', 'sourceCardIds']
for (const card of realCorpusCards.cards) {
  assert.equal(card.sourceAuditOnly, true)
  assert.equal(card.schemaVersion, 'real-corpus-experience-card-v3')
  assert.match(card.sourceFileHash, /^[a-f0-9]{64}$/)
  assert.ok(Array.isArray(card.sourceWindowHashes) && card.sourceWindowHashes.length >= 2)
  assert.equal(card.safetyFlags.no_raw_excerpt, true)
  assert.equal(card.safetyFlags.no_source_text, true)
  assert.equal(card.safetyFlags.no_source_names, true)
  assert.equal(card.safetyFlags.no_direct_imitation, true)
  assert.equal(card.safetyFlags.no_long_quote, true)
  assert.equal(card.safetyFlags.expression_only, true)
  assert.ok(['prompt-ready-low-dose', 'backend-reference-only', 'needs-human-review', 'rejected'].includes(card.promptReadiness))
  for (const key of forbiddenPromptKeys) {
    assert.equal(Object.hasOwn(card, key), false, `${card.cardId} must not contain forbidden key ${key}`)
  }
  const promptFacing = [
    card.applicableScenes,
    card.writingMethod,
    card.promptInjectionSafeVersion,
    card.originalMicroDemo,
    card.antiAiReminder,
    card.notApplicableScenes,
    card.riskNotes
  ].flat().join('\n')
  assert.doesNotMatch(promptFacing, new RegExp(card.sourceTitle.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')), `${card.cardId} prompt-facing fields must not contain source title`)
}

for (const scene of SYNTHETIC_SCENES) {
  const selected = retrieveRealCorpusExperienceCards(scene.sceneExecutionCard, realCorpusCards.cards, { limit: 2 })
  assert.ok(selected.length >= 1 && selected.length <= 2, `${scene.id} should retrieve 1-2 cards`)
  assert.ok(selected.some(card => card.sceneFunctionTags.some(tag => scene.expectedTags.includes(tag))), `${scene.id} should match by scene function`)
  assert.ok(selected.every(card => card.sceneFunctionTags.some(tag => scene.expectedTags.includes(tag)) || /applicableScene|expression/.test(card.retrievalReason)), `${scene.id} should not admit prompt-ready cards with no scene-function or expression match`)
  const helper = buildExpressionHelperFromRealCorpusCards(selected, scene.sceneExecutionCard)
  assert.match(helper, /Expression Helper/)
  assert.doesNotMatch(helper, /sourceTitle|sourceFileHash|sourceWindowHashes|rawExcerpt|sourceText|stateAuthority|guardSnapshot|futureRoadmap/)
  for (const card of selected) {
    assert.doesNotMatch(helper, new RegExp(card.sourceTitle.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')))
  }
}

const noMatchScene = {
  schemaVersion: 'scene-execution-card-v1',
  sceneObjective: '只测试检索资格，不提供任何匹配标签。',
  conflictPair: '甲 vs 乙',
  emotionalTurn: '保持原状',
  sceneFunctionTags: ['dialogue_conflict']
}
const noMatchCards = [
  {
    ...realCorpusCards.cards[0],
    cardId: 'real-corpus-v3-no-match',
    sceneFunctionTags: ['scene_dwell'],
    applicableScenes: ['完全无关的空间静观']
  }
]
assert.deepEqual(
  retrieveRealCorpusExperienceCards(noMatchScene, noMatchCards, { limit: 2 }),
  [],
  'prompt readiness alone must not make a card eligible for retrieval'
)
assert.deepEqual(
  retrieveRealCorpusExperienceCards({}, realCorpusCards.cards, { limit: 2 }),
  [],
  'empty or low-signal SceneExecutionCard must not retrieve generic fallback cards'
)

assert.equal(payload.retrieval.scenes.length, 6)
assert.equal(payload.retrieval.maxSelectedCards, 2)
assert.equal(payload.retrieval.leakageDetected, false)

assert.equal(payload.safety.blockingIssues.length, 0)
assert.equal(payload.safety.promptFacingSourceNameLeaks.length, 0)
assert.equal(payload.safety.rawFieldViolations.length, 0)
assert.equal(payload.safety.longQuoteViolations.length, 0)
assert.equal(payload.safety.microDemoSimilarityViolations.length, 0)
assert.equal(payload.safety.factBoundaryViolations.length, 0)

assert.equal(payload.abQuality.syntheticScenes.length, 6)
assert.equal(payload.abQuality.summary.sampleV3Regressions, 0)
assert.equal(payload.abQuality.summary.futureLeaks, 0)
assert.ok(payload.abQuality.summary.averageSampleScore >= payload.abQuality.summary.averageBaselineScore)
assert.ok(payload.abQuality.summary.averageSignalLift > 0)

assert.equal(payload.modelAssistedValidation.used, false)
assert.match(payload.modelAssistedValidation.reason, /not available|not exposed|not used/i)

assert.equal(payload.review.threadId, '019f300d-e340-78e2-bb59-fd23ccd0ae69')
assert.equal(payload.review.critical, 0)
assert.equal(payload.review.important, 0)
assert.equal(payload.review.minor, 1)
assert.match(payload.review.conclusion, /ready/i)

assert.doesNotThrow(() => validateRealCorpusExperienceCardsPayload(payload))
const persistedPayload = JSON.parse(await (await import('node:fs/promises')).readFile('tmp/realistic-flow-qa/real-corpus-experience-cards-phase3-0.json', 'utf8'))
const persistedReport = await (await import('node:fs/promises')).readFile('tmp/realistic-flow-qa/real-corpus-experience-cards-phase3-0-report.md', 'utf8')
assert.doesNotThrow(() => validateRealCorpusExperienceCardsPayload(persistedPayload))
assert.doesNotThrow(() => assertRealCorpusExperienceCardsReportMatchesJson(persistedReport, persistedPayload))
assert.match(persistedReport, /review\.threadId=019f300d-e340-78e2-bb59-fd23ccd0ae69/)
assert.match(persistedReport, /review\.important=0/)

console.log('real corpus experience cards phase3.0 contract passed')
