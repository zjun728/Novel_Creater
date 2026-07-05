import fs from 'node:fs/promises'
import fsSync from 'node:fs'
import path from 'node:path'
import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'

import {
  assertPlatformRcPreflightReportMatchesJson,
  validatePlatformRcPreflightPayload,
} from './run_platform_rc_preflight_phase2_7.mjs'
import {
  assertRealCorpusExperienceCardsReportMatchesJson,
  validateRealCorpusExperienceCardsPayload,
} from './run_real_corpus_experience_cards_phase3_0.mjs'
import {
  assertRealCorpusPromptHookupReportMatchesJson,
  validatePhase32Payload,
} from './run_real_corpus_prompt_hookup_phase3_2.mjs'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)
const ROOT_DIR = path.resolve(__dirname, '..')
const QA_DIR = path.join(ROOT_DIR, 'tmp/realistic-flow-qa')
const OUT_JSON = path.join(QA_DIR, 'platform-sample-rc-preflight-phase3-4.json')
const OUT_REPORT = path.join(QA_DIR, 'platform-sample-rc-preflight-phase3-4-report.md')
const DETERMINISTIC_GENERATED_AT = '2026-07-05T00:00:00.000Z'

const PHASE34_ALLOWED_DIRTY_PATHS = new Set([
  'tmp/run_platform_sample_rc_preflight_phase3_4.mjs',
  'tmp/test_platform_sample_rc_preflight_phase3_4.mjs',
  'tmp/realistic-flow-qa/platform-sample-rc-preflight-phase3-4.json',
  'tmp/realistic-flow-qa/platform-sample-rc-preflight-phase3-4-report.md',
])

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

const PREFLIGHT_COMMANDS = [
  {
    label: 'phase2_7_platform_rc_preflight',
    command: process.execPath,
    args: [
      '-e',
      "import('./tmp/run_platform_rc_preflight_phase2_7.mjs').then(async m => { const payload = await m.runPlatformRcPreflightGate(); m.validatePlatformRcPreflightPayload(payload); if (!payload.summary.rcPreflightPassed) process.exit(1); }).catch(error => { console.error(error); process.exit(1); })",
    ],
    display: 'node -e import run_platform_rc_preflight_phase2_7.mjs read-only',
  },
  {
    label: 'phase2_7_platform_rc_contract',
    command: process.execPath,
    args: [
      '-e',
      "import('node:fs').then(fs => import('./tmp/run_platform_rc_preflight_phase2_7.mjs').then(m => { const payload = JSON.parse(fs.readFileSync('tmp/realistic-flow-qa/platform-rc-preflight-phase2-7.json', 'utf8')); const report = fs.readFileSync('tmp/realistic-flow-qa/platform-rc-preflight-phase2-7-report.md', 'utf8'); m.validatePlatformRcPreflightPayload(payload); m.assertPlatformRcPreflightReportMatchesJson(report, payload); })).catch(error => { console.error(error); process.exit(1); })",
    ],
    display: 'node -e validate platform-rc-preflight-phase2-7 JSON/report',
  },
  {
    label: 'phase3_0_real_corpus_cards_contract',
    command: process.execPath,
    args: ['tmp/test_real_corpus_experience_cards_phase3_0.mjs'],
    display: 'node tmp\\test_real_corpus_experience_cards_phase3_0.mjs',
  },
  {
    label: 'phase3_2_real_corpus_prompt_hookup_contract',
    command: process.execPath,
    args: ['tmp/test_real_corpus_prompt_hookup_phase3_2.mjs'],
    display: 'node tmp\\test_real_corpus_prompt_hookup_phase3_2.mjs',
  },
  {
    label: 'writing_standard_prompt_boundary',
    command: process.execPath,
    args: ['tmp/test_writing_standard_prompt_boundary_contract.mjs'],
    display: 'node tmp\\test_writing_standard_prompt_boundary_contract.mjs',
  },
  {
    label: 'sample_micro_demo_injection',
    command: process.execPath,
    args: ['tmp/test_sample_micro_demo_injection_contract.mjs'],
    display: 'node tmp\\test_sample_micro_demo_injection_contract.mjs',
  },
  {
    label: 'writing_sample_library_frontend',
    command: process.execPath,
    args: ['tmp/test_writing_sample_library_frontend_contract.mjs'],
    display: 'node tmp\\test_writing_sample_library_frontend_contract.mjs',
  },
  {
    label: 'writing_sample_library_backend',
    command: 'python',
    args: ['tmp/test_writing_sample_library_backend_contract.py'],
    display: 'python tmp\\test_writing_sample_library_backend_contract.py',
  },
  {
    label: 'narrative_voice_scene_phase2',
    command: process.execPath,
    args: ['tmp/test_narrative_voice_scene_contract_phase2.mjs'],
    display: 'node tmp\\test_narrative_voice_scene_contract_phase2.mjs',
  },
  {
    label: 'offline_narrative_quality_regression_phase2_1',
    command: process.execPath,
    args: ['tmp/test_offline_narrative_quality_regression_phase2_1.mjs'],
    display: 'node tmp\\test_offline_narrative_quality_regression_phase2_1.mjs',
  },
]

const ALIGNMENT_ARTIFACTS = [
  {
    label: 'platform_rc_phase2_7',
    jsonPath: 'tmp/realistic-flow-qa/platform-rc-preflight-phase2-7.json',
    reportPath: 'tmp/realistic-flow-qa/platform-rc-preflight-phase2-7-report.md',
    validate: validatePlatformRcPreflightPayload,
    assertReport: assertPlatformRcPreflightReportMatchesJson,
  },
  {
    label: 'real_corpus_phase3_0',
    jsonPath: 'tmp/realistic-flow-qa/real-corpus-experience-cards-phase3-0.json',
    reportPath: 'tmp/realistic-flow-qa/real-corpus-experience-cards-phase3-0-report.md',
    validate: validateRealCorpusExperienceCardsPayload,
    assertReport: assertRealCorpusExperienceCardsReportMatchesJson,
  },
  {
    label: 'real_corpus_prompt_hookup_phase3_2',
    jsonPath: 'tmp/realistic-flow-qa/real-corpus-prompt-hookup-phase3-2.json',
    reportPath: 'tmp/realistic-flow-qa/real-corpus-prompt-hookup-phase3-2-report.md',
    validate: validatePhase32Payload,
    assertReport: assertRealCorpusPromptHookupReportMatchesJson,
  },
]

function normalPath(filePath) {
  return String(filePath || '').replace(/\\/g, '/')
}

function compact(value, limit = 700) {
  const text = String(value || '').replace(/\s+/g, ' ').trim()
  return text.length > limit ? `${text.slice(0, limit)}...` : text
}

function readText(relativePath) {
  return fsSync.readFileSync(path.join(ROOT_DIR, relativePath), 'utf8')
}

function readJson(relativePath) {
  return JSON.parse(readText(relativePath))
}

function git(args, options = {}) {
  const result = spawnSync('git', args, {
    cwd: ROOT_DIR,
    encoding: 'utf8',
    windowsHide: true,
    ...options,
  })
  if (result.status !== 0 && options.required !== false) {
    throw new Error(`git ${args.join(' ')} failed: ${result.stderr || result.stdout}`)
  }
  return result.stdout.trim()
}

function gitContains(commit) {
  const result = spawnSync('git', ['merge-base', '--is-ancestor', commit, 'HEAD'], {
    cwd: ROOT_DIR,
    encoding: 'utf8',
    windowsHide: true,
  })
  return result.status === 0
}

function parseStatus() {
  const stdout = git(['status', '--short', '--untracked-files=all'])
  return stdout
    .split(/\r?\n/)
    .map(line => line.trimEnd())
    .filter(Boolean)
    .map(line => {
      const status = line.slice(0, 2).trim()
      const rawPath = line.slice(3).trim()
      const filePath = rawPath.includes(' -> ') ? rawPath.split(' -> ').pop() : rawPath
      return { status, path: normalPath(filePath) }
    })
}

function buildBranchAndCommitChain() {
  const sampleDeltaFiles = git(['diff', '--name-only', 'd45a64c..66553ee'])
    .split(/\r?\n/)
    .map(normalPath)
    .filter(Boolean)
    .sort()
  return {
    branch: {
      current: git(['branch', '--show-current']),
      headCommit: git(['rev-parse', '--short', 'HEAD']),
      basePlatformCommit: 'd45a64c',
      sampleCandidateCommit: 'a326c7d',
      promptHelperCommit: '66553ee',
    },
    commitChain: {
      containsPlatformRcIntegration: gitContains('d45a64c'),
      containsSampleV3Candidate: gitContains('a326c7d'),
      containsPromptHelperGate: gitContains('66553ee'),
      sampleDeltaFiles,
    },
  }
}

function buildWorktreeStatus() {
  const entries = parseStatus()
  const outsidePhase34 = entries.filter(entry => !PHASE34_ALLOWED_DIRTY_PATHS.has(entry.path))
  return {
    entries,
    dirtyCount: entries.length,
    dirtyOutsidePhase34: outsidePhase34,
    nonIgnoredDirtyOutsidePhase34Count: outsidePhase34.length,
  }
}

function runCommand(commandSpec) {
  const startedAt = Date.now()
  const result = spawnSync(commandSpec.command, commandSpec.args, {
    cwd: ROOT_DIR,
    encoding: 'utf8',
    windowsHide: true,
  })
  return {
    label: commandSpec.label,
    command: commandSpec.display,
    status: result.status === 0 ? 'passed' : 'failed',
    exitCode: result.status ?? 1,
    durationMs: Date.now() - startedAt,
    stdoutTail: compact(result.stdout),
    stderrTail: compact(result.stderr),
  }
}

function runPreflightCommands() {
  const results = PREFLIGHT_COMMANDS.map(runCommand)
  return {
    requiredCommandLabels: PREFLIGHT_COMMANDS.map(command => command.label),
    total: results.length,
    failed: results.filter(result => result.status !== 'passed').length,
    results,
  }
}

function runAlignmentChecks() {
  const results = ALIGNMENT_ARTIFACTS.map(artifact => {
    const startedAt = Date.now()
    try {
      const payload = readJson(artifact.jsonPath)
      const report = readText(artifact.reportPath)
      artifact.validate(payload)
      artifact.assertReport(report, payload)
      return {
        label: artifact.label,
        jsonPath: artifact.jsonPath,
        reportPath: artifact.reportPath,
        status: 'passed',
        durationMs: Date.now() - startedAt,
        error: '',
      }
    } catch (error) {
      return {
        label: artifact.label,
        jsonPath: artifact.jsonPath,
        reportPath: artifact.reportPath,
        status: 'failed',
        durationMs: Date.now() - startedAt,
        error: compact(error?.stack || error?.message || error),
      }
    }
  })
  return {
    requiredLabels: ALIGNMENT_ARTIFACTS.map(artifact => artifact.label),
    total: results.length,
    failed: results.filter(result => result.status !== 'passed').length,
    results,
  }
}

function buildLeakageAndHelperEvidence(phase32Payload) {
  return {
    leakage: {
      sourceLeaks: phase32Payload.summary.sourceLeaks,
      futureLeaks: phase32Payload.summary.futureLeaks,
      guardStateLeaks: phase32Payload.hookupDesign.doesNotEnterStateAuthority === true ? 0 : 1,
      lowSignalSelectedCards: phase32Payload.summary.lowSignalSelectedCards,
      promptBudgetViolations: phase32Payload.summary.promptBudgetViolations,
      sampleV3PromptRegressions: phase32Payload.summary.sampleV3PromptRegressions,
    },
    v3PromptHelper: {
      optIn: phase32Payload.hookupDesign.optInFlag === 'enableRealCorpusExperienceCards',
      expressionOnly: phase32Payload.hookupDesign.expressionOnly === true,
      doesNotEnterStateAuthority: phase32Payload.hookupDesign.doesNotEnterStateAuthority === true,
      productionDefaultEnabled: phase32Payload.hookupDesign.defaultProductionEnabled === true,
      sampleV3PromptHelperCommitted: gitContains('66553ee'),
      maxCardsWithoutFormalStandard: phase32Payload.formatterBudget.maxCardsWithoutFormalStandard,
      maxCardsWithFormalStandard: phase32Payload.formatterBudget.maxCardsWithFormalStandard,
      helperScenes: phase32Payload.summary.helperScenes,
      averageSignalLift: phase32Payload.summary.averageSignalLift,
    },
  }
}

function buildAcceptanceMatrix(summary, v3PromptHelper) {
  return {
    readyForRealProjectReadOnlyHealthCheck: summary.combinedPreflightPassed,
    readyForDisposableRealDbMigrationDryRun: summary.combinedPreflightPassed,
    readyForLiveGeneration: false,
    readyForLiveGenerationReason: '仍未完成真实项目只读健康检查、一次性 disposable/backup preflight、provider/runtime smoke，因此 live generation 必须保持 no-go。',
    realDbTouched: false,
    liveTouched: false,
    modelUsed: false,
    productionDefaultV3Enabled: v3PromptHelper.productionDefaultEnabled,
    sampleV3PromptHelperCommitted: v3PromptHelper.sampleV3PromptHelperCommitted,
  }
}

function buildSummary({ preflight, alignment, worktree, commitChain, leakage, v3PromptHelper }) {
  const boundaryClean = leakage.sourceLeaks === 0 &&
    leakage.futureLeaks === 0 &&
    leakage.guardStateLeaks === 0 &&
    leakage.lowSignalSelectedCards === 0 &&
    leakage.promptBudgetViolations === 0 &&
    leakage.sampleV3PromptRegressions === 0 &&
    v3PromptHelper.optIn === true &&
    v3PromptHelper.expressionOnly === true &&
    v3PromptHelper.productionDefaultEnabled === false
  return {
    combinedPreflightPassed: preflight.failed === 0 &&
      alignment.failed === 0 &&
      worktree.nonIgnoredDirtyOutsidePhase34Count === 0 &&
      commitChain.containsPlatformRcIntegration &&
      commitChain.containsSampleV3Candidate &&
      commitChain.containsPromptHelperGate &&
      boundaryClean,
    boundaryClean,
    platformRcIncluded: commitChain.containsPlatformRcIntegration,
    sampleV3CandidateIncluded: commitChain.containsSampleV3Candidate,
    promptHelperGateIncluded: commitChain.containsPromptHelperGate,
    nonIgnoredDirtyOutsidePhase34Count: worktree.nonIgnoredDirtyOutsidePhase34Count,
    preflightFailures: preflight.failed,
    alignmentFailures: alignment.failed,
  }
}

export async function runPlatformSampleRcPreflightPhase34(options = {}) {
  const { branch, commitChain } = buildBranchAndCommitChain()
  const worktree = buildWorktreeStatus()
  const preflight = runPreflightCommands()
  const alignment = runAlignmentChecks()
  const phase32Payload = readJson('tmp/realistic-flow-qa/real-corpus-prompt-hookup-phase3-2.json')
  validatePhase32Payload(phase32Payload)
  const { leakage, v3PromptHelper } = buildLeakageAndHelperEvidence(phase32Payload)
  const summary = buildSummary({ preflight, alignment, worktree, commitChain, leakage, v3PromptHelper })
  const acceptanceMatrix = buildAcceptanceMatrix(summary, v3PromptHelper)
  const payload = {
    schemaVersion: 'platform-sample-rc-preflight-phase3-4-v1',
    status: 'completed',
    generatedAt: options.generatedAt || DETERMINISTIC_GENERATED_AT,
    outputs: {
      jsonPath: normalPath(path.relative(ROOT_DIR, OUT_JSON)),
      reportPath: normalPath(path.relative(ROOT_DIR, OUT_REPORT)),
    },
    branch,
    commitChain,
    worktree,
    boundary: {
      serviceStarted: false,
      realDbConnection: false,
      realProjectTouched: false,
      liveGenerationRun: false,
      projectStateWritten: false,
      modelRun: false,
      providerAdapterEntered: false,
      pushOrPrCreated: false,
    },
    preflight,
    alignment,
    leakage,
    v3PromptHelper,
    acceptanceMatrix,
    summary,
    nextRecommendedStage: 'Real Project Read-Only Health Check & Disposable Backup Preflight',
    remainingRisks: [
      'No real project read-only health check has run.',
      'No real DB migration, cleanup, quarantine, or purge has run.',
      'No live generation/canary has run.',
      'No model/provider runtime smoke has run.',
      'V3 helper remains opt-in and not production-default enabled.',
    ],
    review: options.review || null,
  }
  validatePlatformSampleRcPreflightPayload(payload)
  const report = buildPlatformSampleRcPreflightReport(payload)
  assertPlatformSampleRcPreflightReportMatchesJson(report, payload)
  if (options.writeArtifacts === true) {
    await fs.mkdir(QA_DIR, { recursive: true })
    await fs.writeFile(OUT_JSON, `${JSON.stringify(payload, null, 2)}\n`, 'utf8')
    await fs.writeFile(OUT_REPORT, report, 'utf8')
  }
  return payload
}

export function validatePlatformSampleRcPreflightPayload(payload = {}) {
  if (payload.schemaVersion !== 'platform-sample-rc-preflight-phase3-4-v1') {
    throw new Error('invalid Phase 3.4 schemaVersion')
  }
  if (payload.status !== 'completed') throw new Error('Phase 3.4 payload must be completed')
  if (payload.branch?.current !== 'codex/novel-creater-sample-library-v3-prompt-hookup') {
    throw new Error('Phase 3.4 must run on sample library prompt hookup branch')
  }
  for (const key of ['serviceStarted', 'realDbConnection', 'realProjectTouched', 'liveGenerationRun', 'projectStateWritten', 'modelRun', 'providerAdapterEntered', 'pushOrPrCreated']) {
    if (payload.boundary?.[key] !== false) throw new Error(`boundary.${key} must be false`)
  }
  if (payload.commitChain?.containsPlatformRcIntegration !== true) throw new Error('missing d45a64c platform RC integration')
  if (payload.commitChain?.containsSampleV3Candidate !== true) throw new Error('missing a326c7d sample V3 candidate')
  if (payload.commitChain?.containsPromptHelperGate !== true) throw new Error('missing 66553ee prompt helper gate')
  if (!Array.isArray(payload.commitChain?.sampleDeltaFiles) || payload.commitChain.sampleDeltaFiles.length !== 12) {
    throw new Error('sample delta file inventory must contain 12 files')
  }
  const actualDelta = [...payload.commitChain.sampleDeltaFiles].sort()
  if (JSON.stringify(actualDelta) !== JSON.stringify(EXPECTED_SAMPLE_DELTA_FILES)) {
    throw new Error('sample delta file inventory does not match the expected Phase 3.0/3.2 file set')
  }
  if (payload.worktree?.nonIgnoredDirtyOutsidePhase34Count !== 0) {
    throw new Error('worktree has non-Phase 3.4 dirty files')
  }
  if (payload.preflight?.failed !== 0) throw new Error('aggregate preflight commands failed')
  if (payload.preflight?.total !== PREFLIGHT_COMMANDS.length) throw new Error('aggregate preflight command count mismatch')
  if (payload.alignment?.failed !== 0) throw new Error('aggregate alignment failed')
  if (payload.alignment?.total !== ALIGNMENT_ARTIFACTS.length) throw new Error('alignment artifact count mismatch')
  for (const key of ['sourceLeaks', 'futureLeaks', 'guardStateLeaks', 'lowSignalSelectedCards', 'promptBudgetViolations', 'sampleV3PromptRegressions']) {
    if (payload.leakage?.[key] !== 0) throw new Error(`leakage.${key} must be zero`)
  }
  if (payload.v3PromptHelper?.optIn !== true) throw new Error('V3 helper must be opt-in')
  if (payload.v3PromptHelper?.expressionOnly !== true) throw new Error('V3 helper must be expression-only')
  if (payload.v3PromptHelper?.doesNotEnterStateAuthority !== true) throw new Error('V3 helper must not enter stateAuthority')
  if (payload.v3PromptHelper?.productionDefaultEnabled !== false) throw new Error('V3 helper must not be production-default enabled')
  if (payload.v3PromptHelper?.sampleV3PromptHelperCommitted !== true) throw new Error('Phase 3.3 helper commit must be included')
  if (payload.acceptanceMatrix?.readyForRealProjectReadOnlyHealthCheck !== true) throw new Error('read-only health check gate should be ready')
  if (payload.acceptanceMatrix?.readyForDisposableRealDbMigrationDryRun !== true) throw new Error('disposable DB dry-run gate should be ready')
  if (payload.acceptanceMatrix?.readyForLiveGeneration !== false) throw new Error('live generation must remain false')
  for (const key of ['realDbTouched', 'liveTouched', 'modelUsed', 'productionDefaultV3Enabled']) {
    if (payload.acceptanceMatrix?.[key] !== false) throw new Error(`acceptance.${key} must be false`)
  }
  if (payload.acceptanceMatrix?.sampleV3PromptHelperCommitted !== true) throw new Error('acceptance must show committed V3 helper')
  if (payload.summary?.combinedPreflightPassed !== true) throw new Error('combined preflight must pass')
  if (payload.summary?.boundaryClean !== true) throw new Error('boundary must be clean')
  return true
}

export function buildPlatformSampleRcPreflightReport(payload) {
  validatePlatformSampleRcPreflightPayload(payload)
  const lines = [
    '# Platform + Sample Library v3 RC Preflight Phase 3.4 Report',
    '',
    'Status: deterministic no-model/no-live aggregate acceptance gate. This report does not claim live generation, real DB migration, real project regression, model validation, provider adapter readiness, push, or PR.',
    '',
    '## Scope Guard',
    '- Did not start backend/frontend dev server, runner, or page.goto.',
    '- Did not run formal chapter generation/finalization chain.',
    '- Did not connect to or write a real DB; no migration/cleanup/quarantine/purge executed.',
    '- Did not touch real project data, restore LongformBrowser, or run #98/#99/#50.',
    '- Did not run a model or enter provider/model adapter code.',
    '- Did not save model output as project body, outline, beat plan, or DB state.',
    '- Did not push or create PR.',
    '',
    '## Branch And Commit Chain',
    `branch.current=${payload.branch.current}`,
    `branch.headCommit=${payload.branch.headCommit}`,
    `branch.basePlatformCommit=${payload.branch.basePlatformCommit}`,
    `branch.sampleCandidateCommit=${payload.branch.sampleCandidateCommit}`,
    `branch.promptHelperCommit=${payload.branch.promptHelperCommit}`,
    `commitChain.containsPlatformRcIntegration=${payload.commitChain.containsPlatformRcIntegration}`,
    `commitChain.containsSampleV3Candidate=${payload.commitChain.containsSampleV3Candidate}`,
    `commitChain.containsPromptHelperGate=${payload.commitChain.containsPromptHelperGate}`,
    `commitChain.sampleDeltaFileCount=${payload.commitChain.sampleDeltaFiles.length}`,
    `worktree.nonIgnoredDirtyOutsidePhase34Count=${payload.worktree.nonIgnoredDirtyOutsidePhase34Count}`,
    '| sample_delta_file |',
    '| --- |',
    ...payload.commitChain.sampleDeltaFiles.map(filePath => `| ${filePath} |`),
    '',
    '## Summary',
    `summary.combinedPreflightPassed=${payload.summary.combinedPreflightPassed}`,
    `summary.boundaryClean=${payload.summary.boundaryClean}`,
    `summary.platformRcIncluded=${payload.summary.platformRcIncluded}`,
    `summary.sampleV3CandidateIncluded=${payload.summary.sampleV3CandidateIncluded}`,
    `summary.promptHelperGateIncluded=${payload.summary.promptHelperGateIncluded}`,
    `summary.preflightFailures=${payload.summary.preflightFailures}`,
    `summary.alignmentFailures=${payload.summary.alignmentFailures}`,
    '',
    '## Acceptance Matrix',
    `acceptance.readyForRealProjectReadOnlyHealthCheck=${payload.acceptanceMatrix.readyForRealProjectReadOnlyHealthCheck}`,
    `acceptance.readyForDisposableRealDbMigrationDryRun=${payload.acceptanceMatrix.readyForDisposableRealDbMigrationDryRun}`,
    `acceptance.readyForLiveGeneration=${payload.acceptanceMatrix.readyForLiveGeneration}`,
    `acceptance.readyForLiveGenerationReason=${payload.acceptanceMatrix.readyForLiveGenerationReason}`,
    `acceptance.realDbTouched=${payload.acceptanceMatrix.realDbTouched}`,
    `acceptance.liveTouched=${payload.acceptanceMatrix.liveTouched}`,
    `acceptance.modelUsed=${payload.acceptanceMatrix.modelUsed}`,
    `acceptance.productionDefaultV3Enabled=${payload.acceptanceMatrix.productionDefaultV3Enabled}`,
    `acceptance.sampleV3PromptHelperCommitted=${payload.acceptanceMatrix.sampleV3PromptHelperCommitted}`,
    '',
    '## Preflight Commands',
    `preflight.total=${payload.preflight.total}`,
    `preflight.failed=${payload.preflight.failed}`,
    '| label | status | exitCode | command |',
    '| --- | --- | ---: | --- |',
    ...payload.preflight.results.map(result => `| ${result.label} | ${result.status} | ${result.exitCode} | ${result.command} |`),
    '',
    '## Artifact Alignment',
    `alignment.total=${payload.alignment.total}`,
    `alignment.failed=${payload.alignment.failed}`,
    '| label | status | json | report |',
    '| --- | --- | --- | --- |',
    ...payload.alignment.results.map(result => `| ${result.label} | ${result.status} | ${result.jsonPath} | ${result.reportPath} |`),
    '',
    '## V3 Prompt Helper Boundary',
    `leakage.sourceLeaks=${payload.leakage.sourceLeaks}`,
    `leakage.futureLeaks=${payload.leakage.futureLeaks}`,
    `leakage.guardStateLeaks=${payload.leakage.guardStateLeaks}`,
    `leakage.lowSignalSelectedCards=${payload.leakage.lowSignalSelectedCards}`,
    `leakage.promptBudgetViolations=${payload.leakage.promptBudgetViolations}`,
    `leakage.sampleV3PromptRegressions=${payload.leakage.sampleV3PromptRegressions}`,
    `v3PromptHelper.optIn=${payload.v3PromptHelper.optIn}`,
    `v3PromptHelper.expressionOnly=${payload.v3PromptHelper.expressionOnly}`,
    `v3PromptHelper.doesNotEnterStateAuthority=${payload.v3PromptHelper.doesNotEnterStateAuthority}`,
    `v3PromptHelper.productionDefaultEnabled=${payload.v3PromptHelper.productionDefaultEnabled}`,
    `v3PromptHelper.sampleV3PromptHelperCommitted=${payload.v3PromptHelper.sampleV3PromptHelperCommitted}`,
    `v3PromptHelper.maxCardsWithoutFormalStandard=${payload.v3PromptHelper.maxCardsWithoutFormalStandard}`,
    `v3PromptHelper.maxCardsWithFormalStandard=${payload.v3PromptHelper.maxCardsWithFormalStandard}`,
    `v3PromptHelper.averageSignalLift=${payload.v3PromptHelper.averageSignalLift}`,
    '',
    '## Remaining Risks',
    ...payload.remainingRisks.map(item => `- ${item}`),
    '',
    '## Next Stage Recommendation',
    `nextRecommendedStage=${payload.nextRecommendedStage}`,
    '',
    '## Fresh Full-Surface Review',
    payload.review
      ? `review.threadId=${payload.review.threadId}\nreview.critical=${payload.review.critical}\nreview.important=${payload.review.important}\nreview.minor=${payload.review.minor}\nreview.conclusion=${payload.review.conclusion}`
      : 'Fresh full-surface review pending.',
  ]
  return `${lines.join('\n')}\n`
}

export function assertPlatformSampleRcPreflightReportMatchesJson(reportText, payload) {
  validatePlatformSampleRcPreflightPayload(payload)
  const report = String(reportText || '')
  const checks = {
    'branch.current': payload.branch.current,
    'branch.headCommit': payload.branch.headCommit,
    'branch.basePlatformCommit': payload.branch.basePlatformCommit,
    'branch.sampleCandidateCommit': payload.branch.sampleCandidateCommit,
    'branch.promptHelperCommit': payload.branch.promptHelperCommit,
    'commitChain.containsPlatformRcIntegration': payload.commitChain.containsPlatformRcIntegration,
    'commitChain.containsSampleV3Candidate': payload.commitChain.containsSampleV3Candidate,
    'commitChain.containsPromptHelperGate': payload.commitChain.containsPromptHelperGate,
    'commitChain.sampleDeltaFileCount': payload.commitChain.sampleDeltaFiles.length,
    'worktree.nonIgnoredDirtyOutsidePhase34Count': payload.worktree.nonIgnoredDirtyOutsidePhase34Count,
    'summary.combinedPreflightPassed': payload.summary.combinedPreflightPassed,
    'summary.boundaryClean': payload.summary.boundaryClean,
    'summary.platformRcIncluded': payload.summary.platformRcIncluded,
    'summary.sampleV3CandidateIncluded': payload.summary.sampleV3CandidateIncluded,
    'summary.promptHelperGateIncluded': payload.summary.promptHelperGateIncluded,
    'summary.preflightFailures': payload.summary.preflightFailures,
    'summary.alignmentFailures': payload.summary.alignmentFailures,
    'acceptance.readyForRealProjectReadOnlyHealthCheck': payload.acceptanceMatrix.readyForRealProjectReadOnlyHealthCheck,
    'acceptance.readyForDisposableRealDbMigrationDryRun': payload.acceptanceMatrix.readyForDisposableRealDbMigrationDryRun,
    'acceptance.readyForLiveGeneration': payload.acceptanceMatrix.readyForLiveGeneration,
    'acceptance.readyForLiveGenerationReason': payload.acceptanceMatrix.readyForLiveGenerationReason,
    'acceptance.realDbTouched': payload.acceptanceMatrix.realDbTouched,
    'acceptance.liveTouched': payload.acceptanceMatrix.liveTouched,
    'acceptance.modelUsed': payload.acceptanceMatrix.modelUsed,
    'acceptance.productionDefaultV3Enabled': payload.acceptanceMatrix.productionDefaultV3Enabled,
    'acceptance.sampleV3PromptHelperCommitted': payload.acceptanceMatrix.sampleV3PromptHelperCommitted,
    'preflight.total': payload.preflight.total,
    'preflight.failed': payload.preflight.failed,
    'alignment.total': payload.alignment.total,
    'alignment.failed': payload.alignment.failed,
    'leakage.sourceLeaks': payload.leakage.sourceLeaks,
    'leakage.futureLeaks': payload.leakage.futureLeaks,
    'leakage.guardStateLeaks': payload.leakage.guardStateLeaks,
    'leakage.lowSignalSelectedCards': payload.leakage.lowSignalSelectedCards,
    'leakage.promptBudgetViolations': payload.leakage.promptBudgetViolations,
    'leakage.sampleV3PromptRegressions': payload.leakage.sampleV3PromptRegressions,
    'v3PromptHelper.optIn': payload.v3PromptHelper.optIn,
    'v3PromptHelper.expressionOnly': payload.v3PromptHelper.expressionOnly,
    'v3PromptHelper.doesNotEnterStateAuthority': payload.v3PromptHelper.doesNotEnterStateAuthority,
    'v3PromptHelper.productionDefaultEnabled': payload.v3PromptHelper.productionDefaultEnabled,
    'v3PromptHelper.sampleV3PromptHelperCommitted': payload.v3PromptHelper.sampleV3PromptHelperCommitted,
    'v3PromptHelper.maxCardsWithoutFormalStandard': payload.v3PromptHelper.maxCardsWithoutFormalStandard,
    'v3PromptHelper.maxCardsWithFormalStandard': payload.v3PromptHelper.maxCardsWithFormalStandard,
    'v3PromptHelper.averageSignalLift': payload.v3PromptHelper.averageSignalLift,
    'nextRecommendedStage': payload.nextRecommendedStage,
  }
  if (payload.review) {
    checks['review.threadId'] = payload.review.threadId
    checks['review.critical'] = payload.review.critical
    checks['review.important'] = payload.review.important
    checks['review.minor'] = payload.review.minor
    checks['review.conclusion'] = payload.review.conclusion
  }
  for (const [key, expected] of Object.entries(checks)) {
    const actual = extractSingleLineValue(report, key)
    if (actual !== String(expected)) throw new Error(`Report/JSON mismatch for ${key}: ${actual} expected ${expected}`)
  }
  for (const result of payload.preflight.results) {
    const row = findSingleMarkdownRow(report, result.label)
    assertMarkdownCells(parseMarkdownRow(row), [result.label, result.status, result.exitCode, result.command], `preflight.${result.label}`)
  }
  for (const result of payload.alignment.results) {
    const row = findSingleMarkdownRow(report, result.label)
    assertMarkdownCells(parseMarkdownRow(row), [result.label, result.status, result.jsonPath, result.reportPath], `alignment.${result.label}`)
  }
  for (const filePath of payload.commitChain.sampleDeltaFiles) {
    const row = findSingleMarkdownRow(report, filePath)
    assertMarkdownCells(parseMarkdownRow(row), [filePath], `sampleDelta.${filePath}`)
  }
  return true
}

function escapeRegExp(value) {
  return String(value).replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

function extractSingleLineValue(report, key) {
  const pattern = new RegExp(`^${escapeRegExp(key)}=(.*)$`, 'gm')
  const matches = [...String(report || '').matchAll(pattern)]
  if (matches.length !== 1) throw new Error(`Report key ${key} appears ${matches.length} times`)
  return matches[0][1].trim()
}

function findSingleMarkdownRow(report, firstCell) {
  const pattern = new RegExp(`^\\| ${escapeRegExp(String(firstCell))} \\|.*$`, 'gm')
  const matches = [...String(report || '').matchAll(pattern)]
  if (matches.length !== 1) throw new Error(`Report row ${firstCell} appears ${matches.length} times`)
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
  const payload = await runPlatformSampleRcPreflightPhase34({ writeArtifacts: true })
  console.log(`platform + sample RC preflight phase3.4 wrote ${payload.outputs.jsonPath} and ${payload.outputs.reportPath}`)
  console.log(`combinedPreflightPassed=${payload.summary.combinedPreflightPassed} readyForLiveGeneration=${payload.acceptanceMatrix.readyForLiveGeneration}`)
}

if (process.argv[1] && path.resolve(process.argv[1]) === __filename) {
  main().catch(error => {
    console.error(error)
    process.exit(1)
  })
}
