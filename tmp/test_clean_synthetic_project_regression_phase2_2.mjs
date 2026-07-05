import assert from 'node:assert/strict'
import fs from 'node:fs'

import {
  assertCleanSyntheticReportMatchesJson,
  buildCleanSyntheticProjectFixture,
  buildCleanSyntheticProjectReport,
  runCleanSyntheticProjectRegression,
  validateCleanSyntheticRegressionPayload,
} from './run_clean_synthetic_project_regression_phase2_2.mjs'

function assertIncludes(haystack, needle, message) {
  assert.equal(String(haystack).includes(needle), true, message)
}

function assertNotIncludes(haystack, needle, message) {
  assert.equal(String(haystack).includes(needle), false, message)
}

const fixture = buildCleanSyntheticProjectFixture()
assert.equal(fixture.schemaVersion, 'clean-synthetic-project-fixture-phase2-2-v1')
assert.equal(fixture.storyBlocks.length, 2, 'fixture must simulate two story blocks')
assert.equal(fixture.stages.length, 3, 'fixture must simulate three stages')
assert(fixture.ledger.chapters.length >= 12 && fixture.ledger.chapters.length <= 20, 'fixture must simulate 12-20 historical chapters')
assert.equal(fixture.ledger.chapters.every(chapter => chapter.status === 'final'), true)
assert.equal(fixture.ledger.chapterVersions.every(version => version.versionType === 'final'), true)
assert(fixture.guardOnly.futureRoadmapSecret, 'fixture must have a guard-only future secret')
assert(fixture.savedBeatPlan.conflictWithFinalFact, 'fixture must include saved beat plan conflict text')
assert.equal(Object.keys(fixture.pollutionVariants).length >= 6, true, 'fixture must include pollution variants')

const payload = runCleanSyntheticProjectRegression()
assert.doesNotThrow(() => validateCleanSyntheticRegressionPayload(payload))

assert.equal(payload.schemaVersion, 'clean-synthetic-project-regression-phase2-2-v1')
assert.equal(payload.status, 'completed')
assert.equal(payload.fixtureCoverage.storyBlocks, 2)
assert.equal(payload.fixtureCoverage.stages, 3)
assert(payload.fixtureCoverage.finalChapters >= 12)
assert.equal(payload.fixtureCoverage.hasSavedBeatConflict, true)
assert.equal(payload.fixtureCoverage.hasGuardOnlyFutureRoadmap, true)

const healthy = payload.results.healthyCleanProject
assert.equal(healthy.ready, true)
assert.equal(healthy.healthBlocked, false)
assert.equal(healthy.creativeContextContainsFutureRoadmap, false)
assert.equal(healthy.sceneCard.hasConflict, true)
assert.equal(healthy.sceneCard.hasEmotionalTurn, true)
assert.equal(healthy.sceneCard.hasStopPoint, true)
assert.equal(healthy.sceneCard.trustedFactCount > 0, true)
assertIncludes(healthy.sceneCard.stopPoint, '不能揭露霜塔城主', 'healthy scene card must preserve stop point')
assertNotIncludes(JSON.stringify(healthy.creativeBoundaryEvidence), fixture.guardOnly.futureRoadmapSecret)

const polluted = payload.results.pollutedProject
assert.equal(polluted.ready, false)
assert.equal(polluted.healthBlocked, true)
for (const code of [
  'untrusted_source',
  'empty_chapter_authority',
  'saved_beat_plan_conflict',
  'guard_snapshot_in_creative_context',
  'finalization_pending',
]) {
  assert(polluted.issueCodes.includes(code), `polluted project must expose ${code}`)
}
for (const issue of polluted.blockingIssues) {
  assert(issue.sourceChapterNum || issue.targetType === 'guard_snapshot', `blocking issue ${issue.code} must carry source chapter or be guard leak`)
  if (issue.targetType !== 'guard_snapshot') {
    assert(issue.sourceVersionId || issue.runId || issue.finalizationId, `blocking issue ${issue.code} must carry source id/run/finalization evidence`)
  }
}

const beatConflict = payload.results.savedBeatConflict
assert.equal(beatConflict.finalFactWins, true)
assert.equal(beatConflict.beatPlanAuthority, 'plan_evidence_only')
assert.equal(beatConflict.creativeContextContainsConflictingBeat, false)
assertIncludes(beatConflict.authorityFact, fixture.finalFactText)
assertNotIncludes(beatConflict.authorityFact, fixture.savedBeatPlan.conflictWithFinalFact)

const handoff = payload.results.stageHandoff
assert.equal(handoff.sourceType, 'final_state')
assert.equal(handoff.canRebuildFromFinalFacts, true)
assert.equal(handoff.usesFailedCandidate, false)
assert.equal(handoff.rebuildFinalChapterCount >= 12, true)
assert.equal(handoff.activeStage, 'Block 2 / Stage 3: Siege Choice')

const finalization = payload.results.finalizationHalfSuccess
assert.equal(finalization.ready, false)
assert.equal(finalization.blockingIssueCodes.includes('finalization_pending'), true)
assert.equal(finalization.marker.commitStatus, 'failed_after_chapter_commit')
assert.equal(finalization.marker.sourceChapterNum, 14)

const narrative = payload.results.narrativeVoice
assert.equal(narrative.voiceScope, 'expression_only')
assert.equal(narrative.voiceLintOk, true)
assert.equal(narrative.scenePromptContainsFutureRoadmap, false)
assert.equal(narrative.scenePromptContainsGuardSnapshot, false)
assert.equal(narrative.qualityPassed, true)
assert.equal(narrative.promptQualityPassed, true)
assert.equal(narrative.factOrStageOverridePresent, false)

assert.equal(payload.summary.healthyReady, true)
assert.equal(payload.summary.pollutedBlocked, true)
assert.equal(payload.summary.guardLeaksToCreativeContext, 0)
assert.equal(payload.summary.finalizationHalfSuccessBlocked, true)
assert.equal(payload.summary.narrativeVoiceSafe, true)

const report = buildCleanSyntheticProjectReport(payload)
assert.doesNotThrow(() => assertCleanSyntheticReportMatchesJson(report, payload))
assertIncludes(report, 'fixtureFinalChapters=', 'report must expose fixture coverage')
assertIncludes(report, 'healthy.ready=true', 'report must expose healthy readiness')
assertIncludes(report, 'polluted.ready=false', 'report must expose polluted readiness')
assertIncludes(report, 'narrative.qualityPassed=true', 'report must expose narrative evaluator result')
assertIncludes(report, 'No-live synthetic readiness', 'report must state no-live scope')

const staleReport = report.replace(
  `newPromptEquivalentGuardLeaks=${payload.summary.guardLeaksToCreativeContext}`,
  'newPromptEquivalentGuardLeaks=99'
)
assert.throws(
  () => assertCleanSyntheticReportMatchesJson(staleReport, payload),
  /guardLeaksToCreativeContext|newPromptEquivalentGuardLeaks/
)

const duplicateReport = report.replace(
  'healthy.ready=true',
  'healthy.ready=false; healthy.ready=true'
)
assert.throws(
  () => assertCleanSyntheticReportMatchesJson(duplicateReport, payload),
  /healthy\.ready/
)

if (fs.existsSync('tmp/realistic-flow-qa/clean-synthetic-project-regression-phase2-2.json')) {
  const currentJson = JSON.parse(fs.readFileSync('tmp/realistic-flow-qa/clean-synthetic-project-regression-phase2-2.json', 'utf8'))
  const currentReport = fs.readFileSync('tmp/realistic-flow-qa/clean-synthetic-project-regression-phase2-2-report.md', 'utf8')
  assert.doesNotThrow(() => validateCleanSyntheticRegressionPayload(currentJson))
  assert.doesNotThrow(() => assertCleanSyntheticReportMatchesJson(currentReport, currentJson))
}

console.log('clean synthetic project regression phase2.2 no-live contract passed')
