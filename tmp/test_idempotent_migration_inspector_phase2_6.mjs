import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'

import {
  assertIdempotentMigrationReportMatchesJson,
  buildPlan,
  buildIdempotentMigrationReport,
  schemaWithFirstNOperations,
  runIdempotentMigrationInspectorGate,
  validateIdempotentMigrationPayload,
} from './run_idempotent_migration_inspector_phase2_6.mjs'

const payload = await runIdempotentMigrationInspectorGate()
assert.doesNotThrow(() => validateIdempotentMigrationPayload(payload))

assert.equal(payload.schemaVersion, 'idempotent-migration-inspector-phase2-6-v1')
assert.equal(payload.status, 'completed')
assert.equal(payload.boundary.realApplyExecuted, false)
assert.equal(payload.boundary.touchesRealDb, false)
assert.equal(payload.boundary.usesRealProject, false)
assert.equal(payload.boundary.startsService, false)
assert.match(payload.simulator.path, /tmp[\\/]+idempotent-migration-inspector-phase2-6[\\/]+schema-simulator\.json/)
assert.equal(path.isAbsolute(payload.simulator.path), true)
assert.equal(fs.existsSync(payload.simulator.path), true)

assert.equal(payload.summary.inspectorPlanIdempotent, true)
assert.equal(payload.summary.realApplyExecuted, false)
assert.equal(payload.summary.backupGateBlocksUnsafeApply, true)
assert.equal(payload.summary.rollbackPlanAvailable, true)
assert.equal(payload.summary.phase25SchemaAdapterStillClosed, true)

const provenanceTables = [
  'chapter_versions',
  'chapter_beat_plans',
  'canon_facts',
  'characters',
  'setting_entities',
  'setting_relations',
  'setting_change_events',
  'project_volumes',
]
const provenanceFields = [
  'provenance',
  'source_chapter_num',
  'source_version_id',
  'run_id',
  'finalization_id',
  'commit_status',
]
const finalizationMarkerFields = [
  'id',
  'project_id',
  'chapter_num',
  'source_chapter_num',
  'source_version_id',
  'run_id',
  'finalization_id',
  'commit_status',
  'reason',
  'provenance',
  'started_at',
  'updated_at',
  'created_at',
]
const projectHealthCheckFields = [
  'id',
  'project_id',
  'chapter_num',
  'source_chapter_num',
  'source_version_id',
  'run_id',
  'finalization_id',
  'commit_status',
  'blocked',
  'blocking_count',
  'warning_count',
  'result_json',
  'issue_summary',
  'provenance',
  'created_at',
  'updated_at',
]
const expectedOperationKeys = new Set([
  ...provenanceTables.flatMap(table => provenanceFields.map(field => `${table}.${field}`)),
  'idx_chapter_versions_provenance',
  'idx_chapter_beat_plans_provenance',
  'idx_canon_facts_provenance',
  'idx_setting_entities_provenance',
  'idx_setting_relations_provenance',
  'idx_setting_change_events_provenance',
  'idx_project_volumes_provenance',
  'finalization_markers',
  ...finalizationMarkerFields.map(field => `finalization_markers.${field}`),
  'finalization_markers.primary_key',
  'finalization_markers.uniq_finalization_marker_run',
  'finalization_markers.idx_finalization_markers_project_chapter',
  'finalization_markers.idx_finalization_markers_finalization',
  'finalization_markers.chk_finalization_markers_commit_status',
  'project_health_checks',
  ...projectHealthCheckFields.map(field => `project_health_checks.${field}`),
  'project_health_checks.primary_key',
  'project_health_checks.uniq_project_health_run',
  'project_health_checks.idx_project_health_checks_project_chapter',
  'project_health_checks.idx_project_health_checks_run',
  'project_health_checks.chk_project_health_checks_commit_status',
])
assert.equal(payload.operations.total, expectedOperationKeys.size, 'migration inspector must parse the exact DDL operation set')
assert.deepEqual(new Set(payload.operations.keys), expectedOperationKeys)
assert(payload.operations.items.some(item =>
  item.type === 'add_constraint' &&
  item.key === 'finalization_markers.primary_key' &&
  /PRIMARY KEY/i.test(item.sourceSql)
))
assert(payload.operations.items.some(item =>
  item.type === 'add_constraint' &&
  item.key === 'project_health_checks.primary_key' &&
  /PRIMARY KEY/i.test(item.sourceSql)
))

const fresh = payload.plans.freshSchema
assert(fresh.applyCount > 0, 'fresh schema should apply required DDL')
assert.equal(fresh.skipExistingCount, 0)
assert.equal(fresh.duplicateApplyCount, 0)
assert.equal(fresh.destructiveApplyCount, 0)

const partial = payload.plans.partialSchema
assert(partial.applyCount > 0, 'partial schema should apply missing objects')
assert(partial.skipExistingCount > 0, 'partial schema should skip existing objects')
assert.equal(partial.duplicateApplyCount, 0)
assert.equal(partial.destructiveApplyCount, 0)
assert(partial.planItems.some(item => item.action === 'skip_existing' && item.key === 'chapter_versions.provenance'))
assert(partial.planItems.some(item => item.action === 'apply' && item.key === 'project_health_checks'))

const full = payload.plans.fullSchema
assert.equal(full.applyCount, 0, 'fully migrated schema should not apply duplicates')
assert(full.skipExistingCount >= payload.operations.total)
assert.equal(full.duplicateApplyCount, 0)
assert.equal(full.destructiveApplyCount, 0)
assert.equal(full.needsManualReviewCount, 0)

const driftSchema = schemaWithFirstNOperations(payload.operations.items, payload.operations.items.length)
driftSchema.tables.chapter_versions.columns.provenance.definition = 'provenance TEXT DEFAULT NULL'
driftSchema.tables.finalization_markers.indexes.idx_finalization_markers_project_chapter.definition =
  'INDEX idx_finalization_markers_project_chapter (project_id)'
driftSchema.tables.finalization_markers.constraints.chk_finalization_markers_commit_status.definition =
  'CONSTRAINT chk_finalization_markers_commit_status CHECK (commit_status IN (\"committed\"))'
const driftPlan = buildPlan(payload.operations.items, driftSchema, 'drift_schema')
assert.equal(driftPlan.duplicateApplyCount, 0)
assert.equal(driftPlan.destructiveApplyCount, 0)
assert(driftPlan.needsManualReviewCount > 0, 'definition drift must require manual review')
assert(driftPlan.planItems.some(item =>
  item.action === 'needs_manual_review' &&
  item.key === 'chapter_versions.provenance' &&
  item.reason === 'definition_mismatch'
))
assert(driftPlan.planItems.some(item =>
  item.action === 'needs_manual_review' &&
  item.key === 'finalization_markers.idx_finalization_markers_project_chapter' &&
  item.reason === 'definition_mismatch'
))
assert(driftPlan.planItems.some(item =>
  item.action === 'needs_manual_review' &&
  item.key === 'finalization_markers.chk_finalization_markers_commit_status' &&
  item.reason === 'definition_mismatch'
))

const missingDefinitionSchema = schemaWithFirstNOperations(payload.operations.items, payload.operations.items.length)
missingDefinitionSchema.tables.chapter_versions.columns.provenance = { definition: '' }
const missingDefinitionPlan = buildPlan(payload.operations.items, missingDefinitionSchema, 'missing_definition_schema')
assert(missingDefinitionPlan.planItems.some(item =>
  item.action === 'needs_manual_review' &&
  item.key === 'chapter_versions.provenance' &&
  item.reason === 'missing_existing_definition'
))

assert.equal(payload.rollback.planAvailable, true)
assert.equal(payload.rollback.tableRollbackAvailable, true)
assert.equal(payload.rollback.fullRollbackAvailable, false)
assert.equal(payload.rollback.requiresBackupRestoreForIrreversibleAlter, true)
assert(payload.rollback.irreversibleOperationCount > 0)
assert.equal(payload.rollback.executedAgainstRealDb, false)
assert(payload.rollback.items.some(item => item.key === 'project_health_checks' && item.action === 'drop_created_table'))
assert(payload.rollback.items.some(item => item.key === 'finalization_markers' && item.action === 'drop_created_table'))
assert(payload.rollback.items.some(item => item.key === 'existing_table_provenance_alters' && item.action === 'backup_restore_required'))
assert(payload.rollback.items.every(item => item.requiresBackupApproval))

assert.equal(payload.backupGate.unsafeApplyBlocked, true)
assert.equal(payload.backupGate.safeApplyAllowed, false)
assert.equal(payload.backupGate.disposableDryRunAllowed, true)
assert.equal(payload.backupGate.realApplyWithoutRestoreBlocked, true)
assert.equal(payload.backupGate.realDbDsnPresent, false)
assert.equal(payload.backupGate.blockedReason, 'backup_restore_plan_required')

assert.equal(payload.phase25Regression.finalizationMarkersClosed, true)
assert.equal(payload.phase25Regression.projectHealthChecksClosed, true)
assert.equal(payload.phase25Regression.durableReadinessWired, true)
assert.equal(payload.phase25Regression.healthArtifactsStayOutOfCreativeContext, true)

assert.equal(payload.boundaryScan.productionHardcodedIssueIds, false)
assert.equal(payload.boundaryScan.longformBrowserInProductionDiff, false)
assert.equal(payload.boundaryScan.realDbDsnInPhase26, false)

const report = buildIdempotentMigrationReport(payload)
assert.doesNotThrow(() => assertIdempotentMigrationReportMatchesJson(report, payload))
assert.match(report, /inspector.inspectorPlanIdempotent=true/)
assert.match(report, /backupGate.unsafeApplyBlocked=true/)
assert.match(report, /boundary.realApplyExecuted=false/)

const staleReport = report.replace('inspector.inspectorPlanIdempotent=true', 'inspector.inspectorPlanIdempotent=false')
assert.throws(
  () => assertIdempotentMigrationReportMatchesJson(staleReport, payload),
  /inspectorPlanIdempotent/
)

const duplicateReport = report.replace(
  'backupGate.unsafeApplyBlocked=true',
  'backupGate.unsafeApplyBlocked=false\nbackupGate.unsafeApplyBlocked=true'
)
assert.throws(
  () => assertIdempotentMigrationReportMatchesJson(duplicateReport, payload),
  /backupGate\.unsafeApplyBlocked/
)

if (fs.existsSync('tmp/realistic-flow-qa/idempotent-migration-inspector-phase2-6.json')) {
  const currentJson = JSON.parse(fs.readFileSync('tmp/realistic-flow-qa/idempotent-migration-inspector-phase2-6.json', 'utf8'))
  const currentReport = fs.readFileSync('tmp/realistic-flow-qa/idempotent-migration-inspector-phase2-6-report.md', 'utf8')
  assert.doesNotThrow(() => validateIdempotentMigrationPayload(currentJson))
  assert.doesNotThrow(() => assertIdempotentMigrationReportMatchesJson(currentReport, currentJson))
}

console.log('idempotent migration inspector phase2.6 contract passed')
