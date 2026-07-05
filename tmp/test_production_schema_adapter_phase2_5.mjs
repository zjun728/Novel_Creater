import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'

import {
  assertProductionSchemaAdapterReportMatchesJson,
  buildProductionSchemaAdapterReport,
  runProductionSchemaAdapterGate,
  validateProductionSchemaAdapterPayload,
} from './run_production_schema_adapter_phase2_5.mjs'

const payload = await runProductionSchemaAdapterGate()
assert.doesNotThrow(() => validateProductionSchemaAdapterPayload(payload))

const backendRouter = fs.readFileSync('backend/routers/project_state.py', 'utf8')
const writerView = fs.readFileSync('frontend/src/views/WriterView.vue', 'utf8')

assert.equal(payload.schemaVersion, 'production-schema-adapter-phase2-5-v1')
assert.equal(payload.status, 'completed')
assert.equal(payload.boundary.touchesRealDb, false)
assert.equal(payload.boundary.startsService, false)
assert.equal(payload.boundary.usesRealProject, false)
assert.match(payload.disposableStore.path, /tmp[\\/]+production-schema-adapter-phase2-5[\\/]+disposable-store\.json/)
assert.equal(path.isAbsolute(payload.disposableStore.path), true)
assert.equal(fs.existsSync(payload.disposableStore.path), true)

for (const tableName of [
  'finalization_markers',
  'project_health_checks',
]) {
  const table = payload.schema.tables.find(row => row.table === tableName)
  assert(table, `schema must include ${tableName}`)
  assert.equal(table.hasProductionCreateTable, true, `${tableName} must be a production CREATE TABLE draft`)
  assert.equal(table.hasAllProvenanceFields, true, `${tableName} must include all provenance fields`)
  assert(table.indexes.length >= 2, `${tableName} must include lookup/idempotence indexes`)
  assert.equal(table.hasCommitStatusConstraint, true, `${tableName} must constrain commit_status`)
}

assert(payload.schema.existingProvenanceTables.every(row => row.hasAllProvenanceFields), 'existing provenance tables must remain covered')
assert.equal(payload.rollback.supported, true)
assert(payload.rollback.steps.some(step => step.includes('DROP TABLE IF EXISTS project_health_checks')))
assert(payload.rollback.steps.some(step => step.includes('DROP TABLE IF EXISTS finalization_markers')))
assert.equal(payload.rollback.executedAgainstRealDb, false)

assert.equal(payload.adapters.backend.hasFinalizationMarkerRoutes, true)
assert.equal(payload.adapters.backend.hasProjectHealthCheckRoutes, true)
assert.equal(payload.adapters.backend.hasIdempotentMarkerUpsert, true)
assert.equal(payload.adapters.backend.hasIdempotentHealthUpsert, true)
assert.equal(payload.adapters.frontend.hasFinalizationMarkerClient, true)
assert.equal(payload.adapters.frontend.hasProjectHealthCheckClient, true)
assert.equal(payload.adapters.frontend.hasReadinessDurableMarkerLoad, true)
assert.equal(payload.adapters.frontend.hasContextDurableMarkerInjection, true)

assert.match(backendRouter, /def _is_missing_project_state_table_error\(error\):/)
assert.match(backendRouter, /except Exception as error:[\s\S]*_is_missing_project_state_table_error\(error\)[\s\S]*return \[\]/)
assert.match(backendRouter, /return _migration_unavailable_response\([\s\S]*"finalization_markers"[\s\S]*\)/)
assert.match(backendRouter, /return _migration_unavailable_response\([\s\S]*"project_health_checks"[\s\S]*\)/)
assert.match(writerView, /function isProjectStateMigrationUnavailable\(error\)/)
assert.match(writerView, /const mentionsProjectStateTable = \([\s\S]*message\.includes\('finalization_markers'\)[\s\S]*message\.includes\('project_health_checks'\)[\s\S]*\)/)
assert.match(writerView, /const missingProjectStateTableError = mentionsProjectStateTable && \(/)
assert.match(writerView, /missingProjectStateTableError/)
assert.doesNotMatch(writerView, /message\.includes\('finalization_markers'\)\s*\|\|\s*message\.includes\('project_health_checks'\)\s*\|\|\s*message\.includes\('no such table'\)/)
assert.match(writerView, /catch \(error\) \{[\s\S]*isProjectStateMigrationUnavailable\(error\)[\s\S]*durableFinalizationMarkers\.value = \[\][\s\S]*return \[\]/)
assert.match(writerView, /async function saveDurableFinalizationMarker\(/)
assert.match(writerView, /catch \(error\) \{[\s\S]*isProjectStateMigrationUnavailable\(error\)[\s\S]*return null/)

assert.equal(payload.results.marker.idempotent, true)
assert.equal(payload.results.marker.readBackCount, 1)
assert.equal(payload.results.marker.commitStatus, 'failed_after_chapter_commit')
assert.equal(payload.results.halfSuccessReadinessBlocked, true)

assert.equal(payload.results.healthCheck.idempotent, true)
assert.equal(payload.results.healthCheck.readBackCount, 1)
assert.equal(payload.results.healthCheck.creativeContextContainsHealthJson, false)
assert.equal(payload.results.healthCheck.entersStateAuthority, false)

assert.equal(payload.results.unknownDegradedExcludedFromCreative, true)
assert.equal(payload.results.savedBeatConflictFinalFactWins, true)
assert.equal(payload.results.guardSnapshotLeakBlocked, true)
assert.equal(payload.results.disposableRollback.removedCollections, true)
assert.equal(payload.results.disposableRollback.postRollbackReadBlocked, true)
assert.equal(payload.schema.idempotence.newTablesRepeatSafe, true)
assert.equal(payload.schema.idempotence.existingAlterRepeatSafe, false)
assert.equal(payload.schema.idempotence.productionApplyRequiresInspector, true)
assert.match(payload.schema.idempotence.unavailableReason, /ALTER TABLE/i)

const report = buildProductionSchemaAdapterReport(payload)
assert.doesNotThrow(() => assertProductionSchemaAdapterReportMatchesJson(report, payload))
assert.match(report, /schema.finalizationMarkersClosed=true/)
assert.match(report, /schema.projectHealthChecksClosed=true/)
assert.match(report, /adapter.backendClosed=true/)
assert.match(report, /adapter.frontendClosed=true/)
assert.match(report, /dryRun.schemaParserPassed=true/)
assert.match(report, /dryRun.migrationIdempotenceReady=false/)

const staleReport = report.replace('schema.finalizationMarkersClosed=true', 'schema.finalizationMarkersClosed=false')
assert.throws(
  () => assertProductionSchemaAdapterReportMatchesJson(staleReport, payload),
  /finalizationMarkersClosed/
)

const duplicateReport = report.replace(
  'adapter.backendClosed=true',
  'adapter.backendClosed=false\nadapter.backendClosed=true'
)
assert.throws(
  () => assertProductionSchemaAdapterReportMatchesJson(duplicateReport, payload),
  /adapter\.backendClosed|backendClosed/
)

if (fs.existsSync('tmp/realistic-flow-qa/production-schema-adapter-phase2-5.json')) {
  const currentJson = JSON.parse(fs.readFileSync('tmp/realistic-flow-qa/production-schema-adapter-phase2-5.json', 'utf8'))
  const currentReport = fs.readFileSync('tmp/realistic-flow-qa/production-schema-adapter-phase2-5-report.md', 'utf8')
  assert.doesNotThrow(() => validateProductionSchemaAdapterPayload(currentJson))
  assert.doesNotThrow(() => assertProductionSchemaAdapterReportMatchesJson(currentReport, currentJson))
}

console.log('production schema adapter phase2.5 contract passed')
