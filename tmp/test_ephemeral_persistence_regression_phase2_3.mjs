import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'

import {
  assertEphemeralPersistenceReportMatchesJson,
  buildEphemeralPersistenceReport,
  runEphemeralPersistenceRegression,
  validateEphemeralPersistencePayload,
} from './run_ephemeral_persistence_regression_phase2_3.mjs'

const payload = await runEphemeralPersistenceRegression()
assert.doesNotThrow(() => validateEphemeralPersistencePayload(payload))

assert.equal(payload.schemaVersion, 'ephemeral-persistence-regression-phase2-3-v1')
assert.equal(payload.status, 'completed')
assert.equal(payload.persistence.strategy, 'ephemeral-json-store')
assert.match(payload.persistence.storePath, /tmp[\\/]+ephemeral-persistence-phase2-3[\\/]+project-store\.json/)
assert.equal(path.isAbsolute(payload.persistence.storePath), true)
assert.equal(payload.persistence.touchesRealDb, false)
assert.equal(fs.existsSync(payload.persistence.storePath), true)

const store = JSON.parse(fs.readFileSync(payload.persistence.storePath, 'utf8'))
assert.equal(store.schemaVersion, 'ephemeral-project-store-phase2-3-v1')
assert.equal(store.metadata.syntheticOnly, true)
assert.equal(store.metadata.realDbConnection, false)

const schema = payload.schemaDryRun
assert.equal(schema.mode, 'migration-sql-parse-dry-run-plus-json-store-schema')
assert.equal(schema.executedAgainstRealDb, false)
for (const table of [
  'chapter_versions',
  'canon_facts',
  'setting_entities',
  'setting_relations',
  'setting_change_events',
  'project_volumes',
  'chapter_beat_plans',
]) {
  const row = schema.tables.find(item => item.table === table)
  assert(row, `schema dry-run must include ${table}`)
  assert.equal(row.hasAllProvenanceFields, true, `${table} must expose provenance fields`)
}
assert(schema.adapterGaps.some(gap => gap.collection === 'finalization_markers'))
assert(schema.ephemeralCollections.some(row => row.collection === 'finalization_markers' && row.hasAllProvenanceFields))

for (const row of payload.writeReadCoverage) {
  assert(row.wrote > 0, `${row.collection} must write records`)
  assert(row.read > 0, `${row.collection} must read records`)
  assert.equal(row.provenanceComplete, true, `${row.collection} must preserve provenance metadata`)
}

assert.equal(payload.results.healthy.ready, true)
assert.equal(payload.results.healthy.healthBlocked, false)
assert.equal(payload.results.healthy.creativeContextContainsFutureRoadmap, false)

assert.equal(payload.results.polluted.ready, false)
assert.equal(payload.results.polluted.healthBlocked, true)
for (const code of [
  'finalization_pending',
  'untrusted_source',
  'empty_chapter_authority',
  'saved_beat_plan_conflict',
  'guard_snapshot_in_creative_context',
]) {
  assert(payload.results.polluted.issueCodes.includes(code), `polluted readback must include ${code}`)
}
for (const issue of payload.results.polluted.blockingIssues) {
  assert(issue.sourceChapterNum || issue.targetType === 'guard_snapshot', `${issue.code} must carry source chapter or be guard leak`)
  if (issue.targetType !== 'guard_snapshot') {
    assert(issue.sourceVersionId || issue.runId || issue.finalizationId, `${issue.code} must carry source version/run/finalization evidence`)
  }
}

assert.equal(payload.results.savedBeatConflict.finalFactWins, true)
assert.equal(payload.results.savedBeatConflict.beatPlanAuthority, 'plan_evidence_only')
assert.equal(payload.results.savedBeatConflict.creativeContextContainsConflictingBeat, false)

assert.equal(payload.results.stageHandoff.sourceType, 'final_state')
assert.equal(payload.results.stageHandoff.canRebuildFromFinalFacts, true)
assert.equal(payload.results.stageHandoff.usesFailedCandidate, false)

assert.equal(payload.results.finalizationHalfSuccess.ready, false)
assert(payload.results.finalizationHalfSuccess.blockingIssueCodes.includes('finalization_pending'))
assert.equal(payload.results.finalizationHalfSuccess.marker.commitStatus, 'failed_after_chapter_commit')

assert.equal(payload.results.narrativeVoice.voiceScope, 'expression_only')
assert.equal(payload.results.narrativeVoice.voiceLintOk, true)
assert.equal(payload.results.narrativeVoice.scenePromptContainsFutureRoadmap, false)
assert.equal(payload.results.narrativeVoice.factOrStageOverridePresent, false)
assert.equal(payload.results.narrativeVoice.qualityPassed, true)

assert.equal(payload.cleanupDryRun.mode, 'dry-run-only')
assert.equal(payload.cleanupDryRun.writesRealData, false)
assert(payload.cleanupDryRun.proposedActions.some(action => action.action === 'quarantine'))
assert(payload.cleanupDryRun.projectionRebuild.rejectedProjectionSources > 0)

const report = buildEphemeralPersistenceReport(payload)
assert.doesNotThrow(() => assertEphemeralPersistenceReportMatchesJson(report, payload))
assert.match(report, /临时环境通过不等于真实项目迁移\/清理完成/)
assert.match(report, /ephemeral\.healthyReady=true/)
assert.match(report, /ephemeral\.pollutedBlocked=true/)

const staleReport = report.replace(
  `ephemeral.pollutedBlocked=${payload.summary.pollutedBlocked}`,
  'ephemeral.pollutedBlocked=false'
)
assert.throws(
  () => assertEphemeralPersistenceReportMatchesJson(staleReport, payload),
  /pollutedBlocked/
)

const duplicateReport = report.replace(
  'ephemeral.healthyReady=true',
  'ephemeral.healthyReady=false; ephemeral.healthyReady=true'
)
assert.throws(
  () => assertEphemeralPersistenceReportMatchesJson(duplicateReport, payload),
  /healthyReady|ephemeral\.healthyReady/
)

const payloadWithReview = structuredClone(payload)
payloadWithReview.review = {
  threadId: '019f2ee1-40eb-78e0-9e48-ae2aaf7f9dc0',
  critical: 0,
  important: 0,
  conclusion: 'Ready',
}
payloadWithReview.verification = {
  commands: [
    { command: 'node tmp\\test_ephemeral_persistence_regression_phase2_3.mjs', result: 'passed' },
    { command: 'npm --prefix frontend run build', result: 'passed' },
  ],
}
const reviewedReport = buildEphemeralPersistenceReport(payloadWithReview)
assert.doesNotThrow(() => assertEphemeralPersistenceReportMatchesJson(reviewedReport, payloadWithReview))
assert.throws(
  () => assertEphemeralPersistenceReportMatchesJson(
    reviewedReport.replace('review.conclusion=Ready', 'review.conclusion=Not Ready'),
    payloadWithReview
  ),
  /review\.conclusion|conclusion/
)
assert.throws(
  () => assertEphemeralPersistenceReportMatchesJson(
    reviewedReport.replace(
      'verification.commandCount=2',
      'verification.commandCount=2\nverification.commandCount=2'
    ),
    payloadWithReview
  ),
  /verification\.commandCount/
)

if (fs.existsSync('tmp/realistic-flow-qa/ephemeral-persistence-regression-phase2-3.json')) {
  const currentJson = JSON.parse(fs.readFileSync('tmp/realistic-flow-qa/ephemeral-persistence-regression-phase2-3.json', 'utf8'))
  const currentReport = fs.readFileSync('tmp/realistic-flow-qa/ephemeral-persistence-regression-phase2-3-report.md', 'utf8')
  assert.doesNotThrow(() => validateEphemeralPersistencePayload(currentJson))
  assert.doesNotThrow(() => assertEphemeralPersistenceReportMatchesJson(currentReport, currentJson))
}

console.log('ephemeral persistence regression phase2.3 contract passed')
