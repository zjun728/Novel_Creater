import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'

import {
  assertPlatformRcPreflightReportMatchesJson,
  buildPlatformRcPreflightReport,
  runPlatformRcPreflightGate,
  validatePlatformRcPreflightPayload,
} from './run_platform_rc_preflight_phase2_7.mjs'

const payload = await runPlatformRcPreflightGate()
assert.doesNotThrow(() => validatePlatformRcPreflightPayload(payload))

assert.equal(payload.schemaVersion, 'platform-rc-preflight-phase2-7-v1')
assert.equal(payload.status, 'completed')
assert.equal(payload.boundary.realDbConnection, false)
assert.equal(payload.boundary.realProjectTouched, false)
assert.equal(payload.boundary.serviceStarted, false)
assert.equal(payload.boundary.liveGenerationRun, false)
assert.equal(payload.boundary.phase3Entered, false)
assert.equal(payload.boundary.commitOrPrCreated, false)

assert.match(payload.outputs.jsonPath, /tmp[\\/]+realistic-flow-qa[\\/]+platform-rc-preflight-phase2-7\.json/)
assert.match(payload.outputs.reportPath, /tmp[\\/]+realistic-flow-qa[\\/]+platform-rc-preflight-phase2-7-report\.md/)
assert.equal(path.isAbsolute(payload.outputs.jsonPath), true)
assert.equal(path.isAbsolute(payload.outputs.reportPath), true)

const requiredPreflightLabels = [
  'context_pack_v2_phase1_contract',
  'state_provenance_phase1_2_contract',
  'narrative_voice_scene_phase2_contract',
  'narrative_voice_phase2_evidence_contract',
  'offline_narrative_quality_regression_phase2_1',
  'clean_synthetic_project_regression_phase2_2',
  'ephemeral_persistence_regression_phase2_3',
  'production_schema_adapter_phase2_5',
  'idempotent_migration_inspector_phase2_6',
  'finalization_guard',
  'finalization_postprocess',
  'finalization_retry',
  'finalize_endpoint',
  'draft_prompt_humanity_brief',
  'chase_variety_prompt',
  'formal_writing_standard_closure',
  'writing_standard_prompt_boundary',
  'writer_flow_boundary_audit',
  'writing_style_standards',
]
assert.deepEqual(payload.preflight.requiredLabels, requiredPreflightLabels)
assert.equal(payload.preflight.total, requiredPreflightLabels.length)
assert.equal(payload.preflight.failed, 0)
for (const label of requiredPreflightLabels) {
  const result = payload.preflight.results.find(item => item.label === label)
  assert(result, `missing preflight result ${label}`)
  assert.equal(result.status, 'passed', `${label} should pass`)
  assert.equal(result.exitCode, 0, `${label} exit code should be 0`)
}

const requiredAlignmentLabels = [
  'phase2_1_offline_narrative_regression',
  'phase2_2_clean_synthetic_regression',
  'phase2_3_ephemeral_persistence',
  'phase2_5_production_schema_adapter',
  'phase2_6_idempotent_migration_inspector',
]
assert.deepEqual(payload.alignment.requiredLabels, requiredAlignmentLabels)
assert.equal(payload.alignment.failed, 0)
for (const label of requiredAlignmentLabels) {
  const result = payload.alignment.results.find(item => item.label === label)
  assert(result, `missing alignment result ${label}`)
  assert.equal(result.status, 'passed', `${label} should pass`)
}

for (const group of [
  'longTermCode',
  'backendMigrationSchema',
  'frontendContextProvenanceFinalization',
  'writingQuality',
  'testsRunners',
  'qaReports',
  'generatedTempStores',
]) {
  assert(Array.isArray(payload.manifest.groups[group]), `missing manifest group ${group}`)
}
assert(payload.manifest.groups.backendMigrationSchema.some(item => item.path.includes('backend/migrations/')))
assert(payload.manifest.groups.frontendContextProvenanceFinalization.some(item => item.path.endsWith('frontend/src/utils/contextPackV2.js')))
assert(payload.manifest.groups.writingQuality.some(item => item.path.endsWith('frontend/src/utils/narrativeVoiceContract.js')))
assert(payload.manifest.groups.testsRunners.some(item => item.path.endsWith('tmp/run_platform_rc_preflight_phase2_7.mjs')))
assert(payload.manifest.groups.qaReports.some(item => item.path.endsWith('tmp/realistic-flow-qa/platform-rc-preflight-phase2-7-report.md')))

const generatedDirs = [
  'tmp/ephemeral-persistence-phase2-3/',
  'tmp/production-schema-adapter-phase2-5/',
  'tmp/idempotent-migration-inspector-phase2-6/',
]
for (const dir of generatedDirs) {
  const policy = payload.artifactPolicy.generatedTempStores.find(item => item.path === dir)
  assert(policy, `missing artifact policy for ${dir}`)
  assert.equal(policy.shouldEnterProductionMerge, false)
  assert.equal(policy.recommendedAction, 'ignore_or_exclude_before_merge')
  assert.equal(policy.evidenceMigratedToQaReport, true)
}
assert(payload.artifactPolicy.qaEvidence.every(item => item.retainForAudit === true))
assert.equal(payload.artifactPolicy.gitignoreCoversGeneratedStores, true)

assert.equal(payload.boundaryScan.productionHardcodedIssueIds, false)
assert.equal(payload.boundaryScan.productionLongformBrowser, false)
assert.equal(payload.boundaryScan.productionRealDbDsn, false)
assert.equal(payload.boundaryScan.productionPageGoto, false)
assert.equal(payload.boundaryScan.modelOutputStateWriteRisk, false)

assert.equal(payload.goNoGo.realDbMigration.status, 'no_go_without_explicit_approval')
assert.equal(payload.goNoGo.realDbMigration.requiresExplicitApproval, true)
assert.equal(payload.goNoGo.realDbMigration.requiresBackupRestoreVerification, true)
assert.equal(payload.goNoGo.realCleanProjectRegression.status, 'no_go_until_real_db_migration_gate_approved')
assert.equal(payload.goNoGo.liveCanary.status, 'no_go_until_clean_project_regression_passes')
assert.equal(payload.goNoGo.phase3ProviderAdapter.status, 'no_go_until_platform_rc_accepted')

assert.equal(payload.summary.rcPreflightPassed, true)
assert.equal(payload.summary.fullDiffManifestReady, true)
assert.equal(payload.summary.artifactPolicyReady, true)
assert.equal(payload.summary.boundaryClean, true)
assert.equal(payload.summary.realApplyExecuted, false)
assert.equal(payload.summary.readyForRealDbMigration, false)
assert.equal(payload.summary.readyForLiveCanary, false)

const report = buildPlatformRcPreflightReport(payload)
assert.doesNotThrow(() => assertPlatformRcPreflightReportMatchesJson(report, payload))
assert.match(report, /summary\.rcPreflightPassed=true/)
assert.match(report, /artifactPolicy\.gitignoreCoversGeneratedStores=true/)
assert.match(report, /goNoGo\.realDbMigration=no_go_without_explicit_approval/)

const staleReport = report.replace('summary.rcPreflightPassed=true', 'summary.rcPreflightPassed=false')
assert.throws(
  () => assertPlatformRcPreflightReportMatchesJson(staleReport, payload),
  /summary\.rcPreflightPassed/
)

const duplicateReport = report.replace(
  'summary.boundaryClean=true',
  'summary.boundaryClean=false\nsummary.boundaryClean=true'
)
assert.throws(
  () => assertPlatformRcPreflightReportMatchesJson(duplicateReport, payload),
  /summary\.boundaryClean/
)

if (fs.existsSync('tmp/realistic-flow-qa/platform-rc-preflight-phase2-7.json')) {
  const currentJson = JSON.parse(fs.readFileSync('tmp/realistic-flow-qa/platform-rc-preflight-phase2-7.json', 'utf8'))
  const currentReport = fs.readFileSync('tmp/realistic-flow-qa/platform-rc-preflight-phase2-7-report.md', 'utf8')
  assert.doesNotThrow(() => validatePlatformRcPreflightPayload(currentJson))
  assert.doesNotThrow(() => assertPlatformRcPreflightReportMatchesJson(currentReport, currentJson))
}

console.log('platform RC preflight phase2.7 contract passed')
