import fs from 'node:fs/promises'
import fsSync from 'node:fs'
import path from 'node:path'
import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'

import {
  assertRegressionReportMatchesJson,
  validateOfflineRegressionPayload,
} from './run_offline_narrative_quality_regression_phase2_1.mjs'
import {
  assertCleanSyntheticReportMatchesJson,
  validateCleanSyntheticRegressionPayload,
} from './run_clean_synthetic_project_regression_phase2_2.mjs'
import {
  assertEphemeralPersistenceReportMatchesJson,
  validateEphemeralPersistencePayload,
} from './run_ephemeral_persistence_regression_phase2_3.mjs'
import {
  assertProductionSchemaAdapterReportMatchesJson,
  validateProductionSchemaAdapterPayload,
} from './run_production_schema_adapter_phase2_5.mjs'
import {
  assertIdempotentMigrationReportMatchesJson,
  validateIdempotentMigrationPayload,
} from './run_idempotent_migration_inspector_phase2_6.mjs'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)
const ROOT_DIR = path.resolve(__dirname, '..')
const OUT_DIR = path.join(__dirname, 'realistic-flow-qa')
const OUT_JSON = path.join(OUT_DIR, 'platform-rc-preflight-phase2-7.json')
const OUT_REPORT = path.join(OUT_DIR, 'platform-rc-preflight-phase2-7-report.md')

const GENERATED_TEMP_STORE_DIRS = [
  'tmp/ephemeral-persistence-phase2-3/',
  'tmp/production-schema-adapter-phase2-5/',
  'tmp/idempotent-migration-inspector-phase2-6/',
]

const REQUIRED_PREFLIGHT_SCRIPTS = [
  ['context_pack_v2_phase1_contract', 'tmp/test_context_pack_v2_phase1_contract.mjs'],
  ['state_provenance_phase1_2_contract', 'tmp/test_state_provenance_phase1_2_contract.mjs'],
  ['narrative_voice_scene_phase2_contract', 'tmp/test_narrative_voice_scene_contract_phase2.mjs'],
  ['narrative_voice_phase2_evidence_contract', 'tmp/test_narrative_voice_phase2_evidence_contract.mjs'],
  ['offline_narrative_quality_regression_phase2_1', 'tmp/test_offline_narrative_quality_regression_phase2_1.mjs'],
  ['clean_synthetic_project_regression_phase2_2', 'tmp/test_clean_synthetic_project_regression_phase2_2.mjs'],
  ['ephemeral_persistence_regression_phase2_3', 'tmp/test_ephemeral_persistence_regression_phase2_3.mjs'],
  ['production_schema_adapter_phase2_5', 'tmp/test_production_schema_adapter_phase2_5.mjs'],
  ['idempotent_migration_inspector_phase2_6', 'tmp/test_idempotent_migration_inspector_phase2_6.mjs'],
  ['finalization_guard', 'tmp/test_finalization_guard.mjs'],
  ['finalization_postprocess', 'tmp/test_finalization_postprocess_contract.mjs'],
  ['finalization_retry', 'tmp/test_finalization_retry_contract.mjs'],
  ['finalize_endpoint', 'tmp/test_finalize_endpoint_contract.mjs'],
  ['draft_prompt_humanity_brief', 'tmp/test_draft_prompt_humanity_brief_contract.mjs'],
  ['chase_variety_prompt', 'tmp/test_chase_variety_prompt_contract.mjs'],
  ['formal_writing_standard_closure', 'tmp/test_formal_writing_standard_closure_contract.mjs'],
  ['writing_standard_prompt_boundary', 'tmp/test_writing_standard_prompt_boundary_contract.mjs'],
  ['writer_flow_boundary_audit', 'tmp/test_writer_flow_boundary_audit_contract.mjs'],
  ['writing_style_standards', 'tmp/test_writing_style_standards_contract.mjs'],
]

const ALIGNMENT_CHECKS = [
  [
    'phase2_1_offline_narrative_regression',
    'tmp/realistic-flow-qa/offline-narrative-quality-regression-phase2-1.json',
    'tmp/realistic-flow-qa/offline-narrative-quality-regression-phase2-1-report.md',
    validateOfflineRegressionPayload,
    assertRegressionReportMatchesJson,
  ],
  [
    'phase2_2_clean_synthetic_regression',
    'tmp/realistic-flow-qa/clean-synthetic-project-regression-phase2-2.json',
    'tmp/realistic-flow-qa/clean-synthetic-project-regression-phase2-2-report.md',
    validateCleanSyntheticRegressionPayload,
    assertCleanSyntheticReportMatchesJson,
  ],
  [
    'phase2_3_ephemeral_persistence',
    'tmp/realistic-flow-qa/ephemeral-persistence-regression-phase2-3.json',
    'tmp/realistic-flow-qa/ephemeral-persistence-regression-phase2-3-report.md',
    validateEphemeralPersistencePayload,
    assertEphemeralPersistenceReportMatchesJson,
  ],
  [
    'phase2_5_production_schema_adapter',
    'tmp/realistic-flow-qa/production-schema-adapter-phase2-5.json',
    'tmp/realistic-flow-qa/production-schema-adapter-phase2-5-report.md',
    validateProductionSchemaAdapterPayload,
    assertProductionSchemaAdapterReportMatchesJson,
  ],
  [
    'phase2_6_idempotent_migration_inspector',
    'tmp/realistic-flow-qa/idempotent-migration-inspector-phase2-6.json',
    'tmp/realistic-flow-qa/idempotent-migration-inspector-phase2-6-report.md',
    validateIdempotentMigrationPayload,
    assertIdempotentMigrationReportMatchesJson,
  ],
]

function readText(filePath) {
  return fsSync.readFileSync(path.resolve(ROOT_DIR, filePath), 'utf8')
}

function readAbsolute(filePath) {
  return fsSync.readFileSync(filePath, 'utf8')
}

function normalPath(filePath) {
  return String(filePath || '').replace(/\\/g, '/')
}

function relativePath(filePath) {
  return normalPath(path.relative(ROOT_DIR, filePath))
}

function compact(value, limit = 500) {
  const text = String(value || '').replace(/\s+/g, ' ').trim()
  return text.length > limit ? `${text.slice(0, limit)}...` : text
}

function parseGitStatus() {
  const result = spawnSync('git', ['status', '--short', '--untracked-files=all'], {
    cwd: ROOT_DIR,
    encoding: 'utf8',
    windowsHide: true,
  })
  if (result.status !== 0) {
    throw new Error(`git status failed: ${result.stderr || result.stdout}`)
  }
  return result.stdout
    .split(/\r?\n/)
    .map(line => line.trimEnd())
    .filter(Boolean)
    .map(line => {
      const status = line.slice(0, 2).trim()
      const rawPath = line.slice(3).trim()
      const filePath = rawPath.includes(' -> ') ? rawPath.split(' -> ').pop() : rawPath
      return {
        status,
        path: normalPath(filePath),
      }
    })
}

function classifyManifestPath(filePath) {
  if (GENERATED_TEMP_STORE_DIRS.some(dir => filePath.startsWith(dir))) return 'generatedTempStores'
  if (filePath.startsWith('tmp/realistic-flow-qa/')) return 'qaReports'
  if (/^tmp\/(?:test|run)_.*\.mjs$/.test(filePath)) return 'testsRunners'
  if (filePath.startsWith('backend/migrations/') ||
    filePath === 'backend/routers/project_state.py' ||
    filePath === 'backend/routers/provenance_support.py') return 'backendMigrationSchema'
  if (filePath.startsWith('frontend/src/utils/context') ||
    filePath.endsWith('stateProvenance.js') ||
    filePath.endsWith('projectHealthCheck.js') ||
    filePath.endsWith('finalizationProtocol.js') ||
    filePath.endsWith('finalizationGuard.js') ||
    filePath === 'frontend/src/views/WriterView.vue' ||
    filePath === 'frontend/src/api/db/client.js' ||
    filePath.startsWith('frontend/src/stores/')) return 'frontendContextProvenanceFinalization'
  if (filePath.endsWith('narrativeVoiceContract.js') ||
    filePath.endsWith('sceneExecutionContract.js') ||
    filePath.endsWith('literaryQualityEvaluator.js') ||
    filePath.startsWith('frontend/src/prompts/')) return 'writingQuality'
  return 'longTermCode'
}

function addManifestEntry(groups, entry) {
  const group = classifyManifestPath(entry.path)
  groups[group].push({
    path: entry.path,
    status: entry.status,
    mergeRole: group === 'qaReports' ? 'qa_evidence'
      : group === 'generatedTempStores' ? 'generated_disposable_store'
        : group === 'testsRunners' ? 'deterministic_test_or_runner'
          : 'long_term_code',
  })
}

function buildFullDiffManifest() {
  const groups = {
    longTermCode: [],
    backendMigrationSchema: [],
    frontendContextProvenanceFinalization: [],
    writingQuality: [],
    testsRunners: [],
    qaReports: [],
    generatedTempStores: [],
  }
  const seen = new Set()
  for (const entry of parseGitStatus()) {
    seen.add(entry.path)
    addManifestEntry(groups, entry)
  }
  for (const dir of GENERATED_TEMP_STORE_DIRS) {
    if (!seen.has(dir) && fsSync.existsSync(path.join(ROOT_DIR, dir))) {
      addManifestEntry(groups, { status: 'ignored_generated', path: dir })
    }
  }
  for (const reportPath of [
    relativePath(OUT_JSON),
    relativePath(OUT_REPORT),
  ]) {
    if (!seen.has(reportPath)) {
      addManifestEntry(groups, { status: fsSync.existsSync(path.join(ROOT_DIR, reportPath)) ? '??' : 'planned', path: reportPath })
    }
  }
  return {
    generatedAt: new Date().toISOString(),
    totalFiles: Object.values(groups).reduce((sum, files) => sum + files.length, 0),
    groups,
    groupCounts: Object.fromEntries(Object.entries(groups).map(([key, files]) => [key, files.length])),
  }
}

function gitignoreCoversGeneratedStores() {
  const text = readText('.gitignore')
  return GENERATED_TEMP_STORE_DIRS.every(dir => text.includes(dir))
}

function buildArtifactPolicy(manifest) {
  return {
    qaEvidence: manifest.groups.qaReports.map(item => ({
      path: item.path,
      retainForAudit: true,
      shouldEnterProductionMerge: true,
      role: 'qa_evidence_report_or_json',
    })),
    generatedTempStores: GENERATED_TEMP_STORE_DIRS.map(dir => ({
      path: dir,
      exists: fsSync.existsSync(path.join(ROOT_DIR, dir)),
      shouldEnterProductionMerge: false,
      recommendedAction: 'ignore_or_exclude_before_merge',
      evidenceMigratedToQaReport: true,
      retainedForLocalAuditUntilRcAccepted: true,
    })),
    gitignoreCoversGeneratedStores: gitignoreCoversGeneratedStores(),
  }
}

function scanBoundary(manifest) {
  const productionGroups = [
    'longTermCode',
    'backendMigrationSchema',
    'frontendContextProvenanceFinalization',
    'writingQuality',
  ]
  const productionFiles = productionGroups
    .flatMap(group => manifest.groups[group])
    .map(item => item.path)
    .filter(filePath => fsSync.existsSync(path.join(ROOT_DIR, filePath)) && fsSync.statSync(path.join(ROOT_DIR, filePath)).isFile())
  const patterns = [
    ['issueIds', /#98|第98|#99|第99|#50|第50/g],
    ['longformBrowser', /LongformBrowser/g],
    ['realDbDsn', /DATABASE_URL|REAL_DB|PROD_DB|mysql:\/\/|postgres:\/\/|sqlite:\/\//g],
    ['pageGoto', /page\.goto/g],
    ['modelOutputStateWrite', /模型输出.*(?:正文|小纲|beat plan|DB)|model output.*(?:state|DB|chapter body|beat plan)/gi],
  ]
  const hits = []
  for (const filePath of productionFiles) {
    const text = readText(filePath)
    for (const [category, pattern] of patterns) {
      pattern.lastIndex = 0
      const matches = [...text.matchAll(pattern)]
      if (matches.length) hits.push({ category, path: filePath, count: matches.length })
    }
  }
  return {
    productionHardcodedIssueIds: hits.some(hit => hit.category === 'issueIds'),
    productionLongformBrowser: hits.some(hit => hit.category === 'longformBrowser'),
    productionRealDbDsn: hits.some(hit => hit.category === 'realDbDsn'),
    productionPageGoto: hits.some(hit => hit.category === 'pageGoto'),
    modelOutputStateWriteRisk: hits.some(hit => hit.category === 'modelOutputStateWrite'),
    hits,
  }
}

function runNodeScript(label, scriptPath) {
  const startedAt = Date.now()
  const result = spawnSync(process.execPath, [scriptPath], {
    cwd: ROOT_DIR,
    encoding: 'utf8',
    windowsHide: true,
  })
  return {
    label,
    command: `node ${scriptPath.replace(/\//g, '\\')}`,
    status: result.status === 0 ? 'passed' : 'failed',
    exitCode: result.status ?? 1,
    durationMs: Date.now() - startedAt,
    stdoutTail: compact(result.stdout, 700),
    stderrTail: compact(result.stderr, 700),
  }
}

function runPreflightScripts() {
  const results = REQUIRED_PREFLIGHT_SCRIPTS.map(([label, scriptPath]) => runNodeScript(label, scriptPath))
  return {
    requiredLabels: REQUIRED_PREFLIGHT_SCRIPTS.map(([label]) => label),
    total: results.length,
    failed: results.filter(result => result.status !== 'passed').length,
    results,
  }
}

function runAlignmentChecks() {
  const results = ALIGNMENT_CHECKS.map(([label, jsonPath, reportPath, validate, assertAlign]) => {
    const startedAt = Date.now()
    try {
      const payload = JSON.parse(readText(jsonPath))
      const report = readText(reportPath)
      validate(payload)
      assertAlign(report, payload)
      return {
        label,
        status: 'passed',
        jsonPath,
        reportPath,
        durationMs: Date.now() - startedAt,
        error: '',
      }
    } catch (error) {
      return {
        label,
        status: 'failed',
        jsonPath,
        reportPath,
        durationMs: Date.now() - startedAt,
        error: compact(error?.stack || error?.message || error),
      }
    }
  })
  return {
    requiredLabels: ALIGNMENT_CHECKS.map(([label]) => label),
    total: results.length,
    failed: results.filter(result => result.status !== 'passed').length,
    results,
  }
}

function buildGoNoGo() {
  return {
    realDbMigration: {
      status: 'no_go_without_explicit_approval',
      requiresExplicitApproval: true,
      requiresBackupRestoreVerification: true,
      requiresTargetDbIdentity: true,
      requiresInspectorDryRunDiff: true,
      requiresRollbackOrRestorePlan: true,
    },
    realCleanProjectRegression: {
      status: 'no_go_until_real_db_migration_gate_approved',
      prerequisites: [
        'RC artifact policy accepted',
        'real DB migration gate explicitly approved or deferred',
        'disposable/clean fixture evidence retained',
        'no production health-check/context boundary regressions',
      ],
    },
    liveCanary: {
      status: 'no_go_until_clean_project_regression_passes',
      prerequisites: [
        'real clean project regression passed',
        'operator rollback and durable marker recovery playbook approved',
        'no model output persisted outside approved live chain',
      ],
    },
    phase3ProviderAdapter: {
      status: 'no_go_until_platform_rc_accepted',
      prerequisites: [
        'platform RC merge accepted',
        'provider adapter design reviewed separately',
      ],
    },
  }
}

function buildSummary(preflight, alignment, manifest, artifactPolicy, boundaryScan) {
  return {
    rcPreflightPassed: preflight.failed === 0 && alignment.failed === 0,
    fullDiffManifestReady: manifest.totalFiles > 0 &&
      Object.values(manifest.groups).every(files => Array.isArray(files)),
    artifactPolicyReady: artifactPolicy.gitignoreCoversGeneratedStores &&
      artifactPolicy.generatedTempStores.every(item => item.shouldEnterProductionMerge === false && item.evidenceMigratedToQaReport),
    boundaryClean: !boundaryScan.productionHardcodedIssueIds &&
      !boundaryScan.productionLongformBrowser &&
      !boundaryScan.productionRealDbDsn &&
      !boundaryScan.productionPageGoto &&
      !boundaryScan.modelOutputStateWriteRisk,
    realApplyExecuted: false,
    readyForRealDbMigration: false,
    readyForLiveCanary: false,
  }
}

export async function runPlatformRcPreflightGate() {
  const manifest = buildFullDiffManifest()
  const artifactPolicy = buildArtifactPolicy(manifest)
  const boundaryScan = scanBoundary(manifest)
  const preflight = runPreflightScripts()
  const alignment = runAlignmentChecks()
  const goNoGo = buildGoNoGo()
  const summary = buildSummary(preflight, alignment, manifest, artifactPolicy, boundaryScan)
  return {
    schemaVersion: 'platform-rc-preflight-phase2-7-v1',
    status: 'completed',
    timestamp: new Date().toISOString(),
    outputs: {
      jsonPath: OUT_JSON,
      reportPath: OUT_REPORT,
    },
    boundary: {
      realDbConnection: false,
      realProjectTouched: false,
      serviceStarted: false,
      liveGenerationRun: false,
      phase3Entered: false,
      commitOrPrCreated: false,
    },
    manifest,
    artifactPolicy,
    boundaryScan,
    preflight,
    alignment,
    goNoGo,
    knownWarnings: [
      {
        source: 'frontend build',
        warning: 'Vite INEFFECTIVE_DYNAMIC_IMPORT for writerStore chunking remains a known non-blocking warning from earlier phases.',
      },
      {
        source: 'git diff --check',
        warning: 'Windows CRLF normalization warnings may appear; no whitespace errors were observed in Phase 2.6 verification.',
      },
    ],
    remainingRisks: [
      'Real DB migration has not executed and still requires explicit approval.',
      'Generated temp stores are local disposable artifacts and should not enter production merge.',
      'Real project cleanup/quarantine/purge has not run.',
      'Real clean project regression and live canary have not run.',
      'Phase 3 provider/model adapter remains out of scope.',
    ],
    summary,
  }
}

export function validatePlatformRcPreflightPayload(payload = {}) {
  if (payload.schemaVersion !== 'platform-rc-preflight-phase2-7-v1') {
    throw new Error('Invalid Phase 2.7 platform RC preflight schemaVersion')
  }
  if (payload.status !== 'completed') return true
  for (const key of ['realDbConnection', 'realProjectTouched', 'serviceStarted', 'liveGenerationRun', 'phase3Entered', 'commitOrPrCreated']) {
    if (payload.boundary?.[key] !== false) throw new Error(`boundary.${key} must be false`)
  }
  if (!path.isAbsolute(payload.outputs?.jsonPath || '')) throw new Error('outputs.jsonPath must be absolute')
  if (!path.isAbsolute(payload.outputs?.reportPath || '')) throw new Error('outputs.reportPath must be absolute')
  if (payload.preflight?.failed !== 0) throw new Error('orchestrated preflight has failed scripts')
  if (payload.alignment?.failed !== 0) throw new Error('alignment checks failed')
  if (payload.preflight?.total !== REQUIRED_PREFLIGHT_SCRIPTS.length) throw new Error('preflight script count mismatch')
  if (payload.alignment?.total !== ALIGNMENT_CHECKS.length) throw new Error('alignment check count mismatch')
  if (!payload.artifactPolicy?.gitignoreCoversGeneratedStores) throw new Error('generated stores must be covered by .gitignore')
  for (const dir of GENERATED_TEMP_STORE_DIRS) {
    const policy = payload.artifactPolicy.generatedTempStores.find(item => item.path === dir)
    if (!policy) throw new Error(`missing generated temp store policy for ${dir}`)
    if (policy.shouldEnterProductionMerge !== false) throw new Error(`${dir} must not enter production merge`)
    if (policy.evidenceMigratedToQaReport !== true) throw new Error(`${dir} evidence must be migrated to QA report/JSON`)
  }
  const expectedSummary = buildSummary(payload.preflight, payload.alignment, payload.manifest, payload.artifactPolicy, payload.boundaryScan)
  for (const [key, expected] of Object.entries(expectedSummary)) {
    if (payload.summary?.[key] !== expected) throw new Error(`summary.${key} mismatch`)
  }
  if (payload.summary.readyForRealDbMigration !== false) throw new Error('Phase 2.7 must not mark real DB migration ready')
  if (payload.summary.readyForLiveCanary !== false) throw new Error('Phase 2.7 must not mark live canary ready')
  return true
}

export function buildPlatformRcPreflightReport(payload) {
  validatePlatformRcPreflightPayload(payload)
  const lines = [
    '# Platform RC Preflight Phase 2.7 Report',
    '',
    'Status: completed deterministic RC preflight. This is a release-candidate freeze gate, not a real DB migration, real project regression, live canary, or Phase 3 provider adapter.',
    '',
    '## Scope Guard',
    '- Did not start backend/frontend dev server, runner, or page.goto.',
    '- Did not run formal chapter generation/finalization chain.',
    '- Did not connect to or write a real DB; no real migration/cleanup/quarantine/purge executed.',
    '- Did not touch real project data, restore LongformBrowser, or run #98/#99/#50.',
    '- Did not save model output as project正文、小纲、beat plan, or DB state.',
    '- Did not enter real clean project regression/live canary or Phase 3 provider/model adapter work.',
    '- Did not create commit/PR.',
    '',
    '## Summary',
    `summary.rcPreflightPassed=${payload.summary.rcPreflightPassed}`,
    `summary.fullDiffManifestReady=${payload.summary.fullDiffManifestReady}`,
    `summary.artifactPolicyReady=${payload.summary.artifactPolicyReady}`,
    `summary.boundaryClean=${payload.summary.boundaryClean}`,
    `summary.realApplyExecuted=${payload.summary.realApplyExecuted}`,
    `summary.readyForRealDbMigration=${payload.summary.readyForRealDbMigration}`,
    `summary.readyForLiveCanary=${payload.summary.readyForLiveCanary}`,
    '',
    '## Orchestrated Preflight',
    `preflight.total=${payload.preflight.total}`,
    `preflight.failed=${payload.preflight.failed}`,
    '| label | status | exitCode |',
    '| --- | --- | --- |',
    ...payload.preflight.results.map(result => `| ${result.label} | ${result.status} | ${result.exitCode} |`),
    '',
    '## Alignment Probes',
    `alignment.total=${payload.alignment.total}`,
    `alignment.failed=${payload.alignment.failed}`,
    '| label | status |',
    '| --- | --- |',
    ...payload.alignment.results.map(result => `| ${result.label} | ${result.status} |`),
    '',
    '## Full Diff Manifest',
    `manifest.totalFiles=${payload.manifest.totalFiles}`,
    ...Object.entries(payload.manifest.groupCounts).map(([group, count]) => `manifest.${group}.count=${count}`),
    '',
    '## Artifact Retention Policy',
    `artifactPolicy.gitignoreCoversGeneratedStores=${payload.artifactPolicy.gitignoreCoversGeneratedStores}`,
    '| path | should_enter_production_merge | recommended_action | evidence_migrated |',
    '| --- | --- | --- | --- |',
    ...payload.artifactPolicy.generatedTempStores.map(item =>
      `| ${item.path} | ${item.shouldEnterProductionMerge} | ${item.recommendedAction} | ${item.evidenceMigratedToQaReport} |`
    ),
    '',
    '## Boundary Scan',
    `boundary.productionHardcodedIssueIds=${payload.boundaryScan.productionHardcodedIssueIds}`,
    `boundary.productionLongformBrowser=${payload.boundaryScan.productionLongformBrowser}`,
    `boundary.productionRealDbDsn=${payload.boundaryScan.productionRealDbDsn}`,
    `boundary.productionPageGoto=${payload.boundaryScan.productionPageGoto}`,
    `boundary.modelOutputStateWriteRisk=${payload.boundaryScan.modelOutputStateWriteRisk}`,
    '',
    '## Go / No-Go',
    `goNoGo.realDbMigration=${payload.goNoGo.realDbMigration.status}`,
    `goNoGo.realDbMigration.requiresExplicitApproval=${payload.goNoGo.realDbMigration.requiresExplicitApproval}`,
    `goNoGo.realDbMigration.requiresBackupRestoreVerification=${payload.goNoGo.realDbMigration.requiresBackupRestoreVerification}`,
    `goNoGo.realCleanProjectRegression=${payload.goNoGo.realCleanProjectRegression.status}`,
    `goNoGo.liveCanary=${payload.goNoGo.liveCanary.status}`,
    `goNoGo.phase3ProviderAdapter=${payload.goNoGo.phase3ProviderAdapter.status}`,
    '',
    '## Known Warnings',
    ...payload.knownWarnings.map(item => `- ${item.source}: ${item.warning}`),
    '',
    '## Remaining Risks',
    ...payload.remainingRisks.map(item => `- ${item}`),
    '',
    '## Fresh Full-Diff Review',
    payload.review
      ? `review.threadId=${payload.review.threadId}\nreview.critical=${payload.review.critical}\nreview.important=${payload.review.important}\nreview.conclusion=${payload.review.conclusion}`
      : 'Fresh full-diff review pending.',
  ]
  if (Array.isArray(payload.verification?.commands) && payload.verification.commands.length) {
    lines.push('', '## Verification')
    lines.push(`verification.commandCount=${payload.verification.commands.length}`)
    lines.push('| command | result |')
    lines.push('| --- | --- |')
    for (const command of payload.verification.commands) {
      lines.push(`| ${command.command} | ${command.result} |`)
    }
  }
  return `${lines.join('\n')}\n`
}

export function assertPlatformRcPreflightReportMatchesJson(reportText, payload) {
  validatePlatformRcPreflightPayload(payload)
  const report = String(reportText || '')
  const checks = {
    'summary.rcPreflightPassed': payload.summary.rcPreflightPassed,
    'summary.fullDiffManifestReady': payload.summary.fullDiffManifestReady,
    'summary.artifactPolicyReady': payload.summary.artifactPolicyReady,
    'summary.boundaryClean': payload.summary.boundaryClean,
    'summary.realApplyExecuted': payload.summary.realApplyExecuted,
    'summary.readyForRealDbMigration': payload.summary.readyForRealDbMigration,
    'summary.readyForLiveCanary': payload.summary.readyForLiveCanary,
    'preflight.total': payload.preflight.total,
    'preflight.failed': payload.preflight.failed,
    'alignment.total': payload.alignment.total,
    'alignment.failed': payload.alignment.failed,
    'manifest.totalFiles': payload.manifest.totalFiles,
    'artifactPolicy.gitignoreCoversGeneratedStores': payload.artifactPolicy.gitignoreCoversGeneratedStores,
    'boundary.productionHardcodedIssueIds': payload.boundaryScan.productionHardcodedIssueIds,
    'boundary.productionLongformBrowser': payload.boundaryScan.productionLongformBrowser,
    'boundary.productionRealDbDsn': payload.boundaryScan.productionRealDbDsn,
    'boundary.productionPageGoto': payload.boundaryScan.productionPageGoto,
    'boundary.modelOutputStateWriteRisk': payload.boundaryScan.modelOutputStateWriteRisk,
    'goNoGo.realDbMigration': payload.goNoGo.realDbMigration.status,
    'goNoGo.realDbMigration.requiresExplicitApproval': payload.goNoGo.realDbMigration.requiresExplicitApproval,
    'goNoGo.realDbMigration.requiresBackupRestoreVerification': payload.goNoGo.realDbMigration.requiresBackupRestoreVerification,
    'goNoGo.realCleanProjectRegression': payload.goNoGo.realCleanProjectRegression.status,
    'goNoGo.liveCanary': payload.goNoGo.liveCanary.status,
    'goNoGo.phase3ProviderAdapter': payload.goNoGo.phase3ProviderAdapter.status,
  }
  for (const [group, count] of Object.entries(payload.manifest.groupCounts)) {
    checks[`manifest.${group}.count`] = count
  }
  if (payload.review) {
    checks['review.threadId'] = payload.review.threadId
    checks['review.critical'] = payload.review.critical
    checks['review.important'] = payload.review.important
    checks['review.conclusion'] = payload.review.conclusion
  }
  if (Array.isArray(payload.verification?.commands) && payload.verification.commands.length) {
    checks['verification.commandCount'] = payload.verification.commands.length
  }
  for (const [key, expected] of Object.entries(checks)) {
    const actual = extractSingleLineValue(report, key)
    if (actual !== String(expected)) throw new Error(`Report/JSON mismatch for ${key}: ${actual} expected ${expected}`)
  }
  for (const result of payload.preflight.results) {
    const row = findSingleMarkdownRow(report, result.label)
    assertMarkdownCells(parseMarkdownRow(row), [result.label, result.status, result.exitCode], `preflight.${result.label}`)
  }
  for (const result of payload.alignment.results) {
    const row = findSingleMarkdownRow(report, result.label)
    assertMarkdownCells(parseMarkdownRow(row), [result.label, result.status], `alignment.${result.label}`)
  }
  for (const policy of payload.artifactPolicy.generatedTempStores) {
    const row = findSingleMarkdownRow(report, policy.path)
    assertMarkdownCells(parseMarkdownRow(row), [
      policy.path,
      policy.shouldEnterProductionMerge,
      policy.recommendedAction,
      policy.evidenceMigratedToQaReport,
    ], `artifactPolicy.${policy.path}`)
  }
  if (Array.isArray(payload.verification?.commands) && payload.verification.commands.length) {
    for (const command of payload.verification.commands) {
      const row = findSingleMarkdownRow(report, command.command)
      assertMarkdownCells(parseMarkdownRow(row), [command.command, command.result], `verification.${command.command}`)
    }
  }
  return true
}

function escapeRegExp(value) {
  return String(value).replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

function extractSingleLineValue(report, key) {
  const pattern = new RegExp(`^${escapeRegExp(key)}=(.*)$`, 'gm')
  const matches = [...String(report || '').matchAll(pattern)]
  if (matches.length !== 1) throw new Error(`Report/JSON mismatch for ${key}: appears ${matches.length} times`)
  return matches[0][1].trim()
}

function findSingleMarkdownRow(report, firstCell) {
  const pattern = new RegExp(`^\\| ${escapeRegExp(String(firstCell))} \\|.*$`, 'gm')
  const matches = [...String(report || '').matchAll(pattern)]
  if (matches.length !== 1) throw new Error(`Report/JSON mismatch for row ${firstCell}: appears ${matches.length} times`)
  return matches[0][0]
}

function parseMarkdownRow(row) {
  return String(row)
    .trim()
    .replace(/^\|/, '')
    .replace(/\|$/, '')
    .split('|')
    .map(cell => cell.trim())
}

function assertMarkdownCells(cells, expectedValues, label) {
  if (cells.length !== expectedValues.length) {
    throw new Error(`Report/JSON mismatch for ${label}: expected ${expectedValues.length} cells, got ${cells.length}`)
  }
  expectedValues.forEach((expected, index) => {
    if (cells[index] !== String(expected)) {
      throw new Error(`Report/JSON mismatch for ${label}[${index}]: ${cells[index]} expected ${expected}`)
    }
  })
}

async function main() {
  const payload = await runPlatformRcPreflightGate()
  const report = buildPlatformRcPreflightReport(payload)
  assertPlatformRcPreflightReportMatchesJson(report, payload)
  await fs.mkdir(OUT_DIR, { recursive: true })
  await fs.writeFile(OUT_JSON, `${JSON.stringify(payload, null, 2)}\n`, 'utf8')
  await fs.writeFile(OUT_REPORT, report, 'utf8')
  console.log(`platform RC preflight phase2.7 wrote ${OUT_JSON} and ${OUT_REPORT}`)
}

if (process.argv[1] && path.resolve(process.argv[1]) === __filename) {
  main().catch(error => {
    console.error(error)
    process.exit(1)
  })
}
