import assert from 'node:assert/strict'
import fs from 'node:fs/promises'

import {
  assertPlatformSampleRcPreflightReportMatchesJson,
  buildPlatformSampleRcPreflightReport,
  runPlatformSampleRcPreflightPhase34,
  validatePlatformSampleRcPreflightPayload,
} from './run_platform_sample_rc_preflight_phase3_4.mjs'

const ARTIFACTS = [
  'tmp/realistic-flow-qa/platform-sample-rc-preflight-phase3-4.json',
  'tmp/realistic-flow-qa/platform-sample-rc-preflight-phase3-4-report.md',
]

const EXPECTED_SAMPLE_DELTA_FILES = [
  'frontend/src/data/realCorpusExperienceCards.v3.json',
  'frontend/src/data/realCorpusExperienceCardsV3.js',
  'frontend/src/prompts/chapter.js',
  'frontend/src/prompts/chapterDraftPrompt.js',
  'tmp/realistic-flow-qa/real-corpus-experience-cards-phase3-0-report.md',
  'tmp/realistic-flow-qa/real-corpus-experience-cards-phase3-0.json',
  'tmp/realistic-flow-qa/real-corpus-prompt-hookup-phase3-2-report.md',
  'tmp/realistic-flow-qa/real-corpus-prompt-hookup-phase3-2.json',
  'tmp/run_real_corpus_experience_cards_phase3_0.mjs',
  'tmp/run_real_corpus_prompt_hookup_phase3_2.mjs',
  'tmp/test_real_corpus_experience_cards_phase3_0.mjs',
  'tmp/test_real_corpus_prompt_hookup_phase3_2.mjs',
]

async function statArtifact(filePath) {
  try {
    const stat = await fs.stat(filePath)
    return { size: stat.size, mtimeMs: stat.mtimeMs }
  } catch {
    return null
  }
}

function stablePayloadFingerprint(payload) {
  return {
    schemaVersion: payload.schemaVersion,
    status: payload.status,
    branch: {
      current: payload.branch.current,
      basePlatformCommit: payload.branch.basePlatformCommit,
      sampleCandidateCommit: payload.branch.sampleCandidateCommit,
      promptHelperCommit: payload.branch.promptHelperCommit,
    },
    commitChain: payload.commitChain,
    boundary: payload.boundary,
    preflight: {
      requiredCommandLabels: payload.preflight.requiredCommandLabels,
      results: payload.preflight.results.map(result => ({
        label: result.label,
        command: result.command,
        status: result.status,
        exitCode: result.exitCode,
      })),
      failed: payload.preflight.failed,
    },
    alignment: {
      requiredLabels: payload.alignment.requiredLabels,
      results: payload.alignment.results.map(result => ({
        label: result.label,
        jsonPath: result.jsonPath,
        reportPath: result.reportPath,
        status: result.status,
      })),
      failed: payload.alignment.failed,
    },
    leakage: payload.leakage,
    v3PromptHelper: payload.v3PromptHelper,
    acceptanceMatrix: payload.acceptanceMatrix,
    summary: payload.summary,
    nextRecommendedStage: payload.nextRecommendedStage,
    remainingRisks: payload.remainingRisks,
  }
}

const beforeStats = await Promise.all(ARTIFACTS.map(statArtifact))
const payload = await runPlatformSampleRcPreflightPhase34({ writeArtifacts: false })
const afterStats = await Promise.all(ARTIFACTS.map(statArtifact))

assert.deepEqual(afterStats, beforeStats, 'Phase 3.4 API must be read-only unless writeArtifacts=true')
assert.doesNotThrow(() => validatePlatformSampleRcPreflightPayload(payload))
assert.equal(payload.schemaVersion, 'platform-sample-rc-preflight-phase3-4-v1')
assert.equal(payload.status, 'completed')
assert.equal(payload.generatedAt, '2026-07-05T00:00:00.000Z')

assert.equal(payload.branch.current, 'codex/novel-creater-sample-library-v3-prompt-hookup')
assert.match(payload.branch.headCommit, /^[a-f0-9]{7,12}$/)
assert.equal(payload.branch.promptHelperCommit, '66553ee')
assert.equal(payload.commitChain.containsPlatformRcIntegration, true)
assert.equal(payload.commitChain.containsSampleV3Candidate, true)
assert.equal(payload.commitChain.containsPromptHelperGate, true)
assert.deepEqual(payload.commitChain.sampleDeltaFiles, EXPECTED_SAMPLE_DELTA_FILES)
assert.equal(payload.commitChain.sampleDeltaFiles.length, 12)
assert.equal(payload.worktree.nonIgnoredDirtyOutsidePhase34Count, 0)

const requiredCommandLabels = [
  'phase2_7_platform_rc_preflight',
  'phase2_7_platform_rc_contract',
  'phase3_0_real_corpus_cards_contract',
  'phase3_2_real_corpus_prompt_hookup_contract',
  'writing_standard_prompt_boundary',
  'sample_micro_demo_injection',
  'writing_sample_library_frontend',
  'writing_sample_library_backend',
  'narrative_voice_scene_phase2',
  'offline_narrative_quality_regression_phase2_1',
]
assert.deepEqual(payload.preflight.requiredCommandLabels, requiredCommandLabels)
assert.equal(payload.preflight.failed, 0)
for (const label of requiredCommandLabels) {
  const result = payload.preflight.results.find(item => item.label === label)
  assert(result, `missing command result ${label}`)
  assert.equal(result.status, 'passed', `${label} should pass`)
  assert.equal(result.exitCode, 0, `${label} exit code should be zero`)
}

assert.equal(payload.alignment.failed, 0)
for (const label of [
  'platform_rc_phase2_7',
  'real_corpus_phase3_0',
  'real_corpus_prompt_hookup_phase3_2',
]) {
  const result = payload.alignment.results.find(item => item.label === label)
  assert(result, `missing alignment result ${label}`)
  assert.equal(result.status, 'passed', `${label} alignment should pass`)
}

assert.equal(payload.leakage.sourceLeaks, 0)
assert.equal(payload.leakage.futureLeaks, 0)
assert.equal(payload.leakage.guardStateLeaks, 0)
assert.equal(payload.leakage.lowSignalSelectedCards, 0)
assert.equal(payload.leakage.promptBudgetViolations, 0)
assert.equal(payload.leakage.sampleV3PromptRegressions, 0)
assert.equal(payload.v3PromptHelper.optIn, true)
assert.equal(payload.v3PromptHelper.expressionOnly, true)
assert.equal(payload.v3PromptHelper.productionDefaultEnabled, false)
assert.equal(payload.v3PromptHelper.sampleV3PromptHelperCommitted, true)

assert.equal(payload.acceptanceMatrix.readyForRealProjectReadOnlyHealthCheck, true)
assert.equal(payload.acceptanceMatrix.readyForDisposableRealDbMigrationDryRun, true)
assert.equal(payload.acceptanceMatrix.readyForLiveGeneration, false)
assert.match(payload.acceptanceMatrix.readyForLiveGenerationReason, /真实项目只读健康检查/)
assert.equal(payload.acceptanceMatrix.realDbTouched, false)
assert.equal(payload.acceptanceMatrix.liveTouched, false)
assert.equal(payload.acceptanceMatrix.modelUsed, false)
assert.equal(payload.acceptanceMatrix.productionDefaultV3Enabled, false)
assert.equal(payload.acceptanceMatrix.sampleV3PromptHelperCommitted, true)

assert.equal(payload.boundary.serviceStarted, false)
assert.equal(payload.boundary.realDbConnection, false)
assert.equal(payload.boundary.realProjectTouched, false)
assert.equal(payload.boundary.liveGenerationRun, false)
assert.equal(payload.boundary.projectStateWritten, false)
assert.equal(payload.boundary.modelRun, false)
assert.equal(payload.boundary.providerAdapterEntered, false)
assert.equal(payload.boundary.pushOrPrCreated, false)

const report = buildPlatformSampleRcPreflightReport(payload)
assertPlatformSampleRcPreflightReportMatchesJson(report, payload)

const staleReport = report.replace(
  'acceptance.readyForLiveGeneration=false',
  'acceptance.readyForLiveGeneration=true',
)
assert.throws(
  () => assertPlatformSampleRcPreflightReportMatchesJson(staleReport, payload),
  /acceptance\.readyForLiveGeneration/,
)

const duplicateReport = report.replace(
  'summary.combinedPreflightPassed=true',
  'summary.combinedPreflightPassed=false\nsummary.combinedPreflightPassed=true',
)
assert.throws(
  () => assertPlatformSampleRcPreflightReportMatchesJson(duplicateReport, payload),
  /summary\.combinedPreflightPassed/,
)

try {
  const persistedPayload = JSON.parse(await fs.readFile(ARTIFACTS[0], 'utf8'))
  const persistedReport = await fs.readFile(ARTIFACTS[1], 'utf8')
  assertPlatformSampleRcPreflightReportMatchesJson(persistedReport, persistedPayload)
  assert.deepEqual(
    stablePayloadFingerprint(persistedPayload),
    stablePayloadFingerprint(payload),
    'persisted Phase 3.4 artifact pair must match current generated stable evidence',
  )
} catch (error) {
  if (error.code !== 'ENOENT') throw error
}

console.log('platform + sample library v3 RC preflight phase3.4 contract passed')
