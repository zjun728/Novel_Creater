import assert from 'node:assert/strict'
import { existsSync, mkdirSync, readFileSync } from 'node:fs'
import path from 'node:path'
import { writeLiveReport } from './live-qa/reports/live-report-writer.mjs'

const outDir = path.join('tmp', 'live-qa-contract-output', `report-writer-${Date.now()}`)
mkdirSync(outDir, { recursive: true })

const jsonPath = path.join(outDir, 'live-report.json')
const mdPath = path.join(outDir, 'live-report.md')

const fixtureReport = {
  mode: 'live',
  createdCleanProject: false,
  usesArchivedReports: false,
  project: {
    id: 'fixture-project-id',
    name: 'FixtureLongform'
  },
  serviceCleanupDiagnostics: {
    killedPids: [1001, 1002],
    skippedStalePids: [],
    pending: false
  },
  aiProxy: {
    aiProxyUsed: true,
    providerId: 'fixture-provider',
    providerName: 'Fixture Provider',
    modelName: 'Fixture Model',
    browserConsoleCorsErrors: 0,
    backendAiRequests: 12,
    providerChatCompletionUrls: ['/v1/chat/completions'],
    realRequestStages: [{ stage: 'chapter-title', ok: true }]
  },
  modelBinding: {
    status: {
      hasBinding: true,
      inherited: true,
      inheritedFromProjectTitle: 'Seed Project'
    },
    settingsPageShowsInheritance: true,
    expectedProviderName: 'Fixture Provider',
    expectedModelName: 'Fixture Model',
    expectedProviderId: 'fixture-provider',
    inheritedProviderMatched: true,
    actualProviderModelMatched: true,
    usedDeepseekV4ProFallback: false,
    taskProviders: [{ taskName: 'draft', providerName: 'Fixture Provider' }]
  },
  planningHierarchy: {
    projectChaptersPageChecked: true,
    legacyTextFound: []
  },
  stepsCompleted: ['open project', 'write chapter'],
  settingInitialization: {
    groupedProgressVisible: true,
    pendingCandidatesCreated: 0,
    acceptedCandidates: 2,
    failedGroups: []
  },
  volumePlanning: {
    generated: true,
    placeholderWarnings: [],
    diagnostics: { ok: true }
  },
  chapterReports: [{
    chapterNum: 88,
    title: 'Fixture Title',
    wordCount: 4659,
    wordCountPolicyStatus: 'within_target',
    titleQuality: { titleValid: true, titleInvalidReason: '' },
    storyBlockId: 'block-1',
    blockStageId: 'stage-1',
    blockStageSnapshot: { stagePurpose: 'fixture stage' },
    previousStoryBlockReviewDecision: 'continue_current_block',
    previousStoryBlockStageContinues: false,
    storyBlockReviewDecision: 'continue_current_block',
    postFinalizeWaitPassed: true,
    postFinalizeFailed: false,
    finalizationMarkerClearedAt: '2026-06-29T00:00:00.000Z',
    storyBlockStageContinues: true,
    storyBlockStageContinueReason: 'fixture',
    stageContinuationDepth: 1,
    settlementDecision: 'continue',
    currentBlockCompletedStages: [{ id: 'stage-1' }, { stageId: 'stage-2' }]
  }],
  storyBlockGranularity: {
    blocksCreated: 1,
    averageChaptersPerBlock: 2,
    singleChapterBlockCount: 0,
    consecutiveSingleChapterBlocks: 0,
    storyBlockGranularityWarning: '',
    storyBlockGranularityQualityHold: '',
    storyBlockStalledWarning: '',
    activeBlockRemainingStages: []
  },
  storyBlockSummaries: [{
    id: 'block-1',
    status: 'active',
    coveredChapterCount: 2,
    executedStageCount: 1,
    completedStageCount: 1,
    stageCount: 3,
    closedUnexecutedStageCount: 0,
    invalidatedStageCount: 0,
    remainingStageCount: 2,
    blockCloseReasonType: '',
    earlyCloseAllowed: false,
    singleChapterCompletedWholeBlock: false,
    completionEvidence: 'fixture evidence',
    singleChapterBlockReason: ''
  }],
  qualityWarnings: [{ code: 'fixture_warning', message: 'quality observation' }],
  qualityBacklog: [{ code: 'fixture_backlog', message: 'quality backlog' }],
  beatPlanQualityRebuilds: [{ chapterNum: 88, retry: 1, message: 'rebuilt' }],
  hardFailWordCountChapters: [],
  blocker: {
    blocked: true,
    code: 'fixture_blocker',
    message: 'fixture blocker'
  },
  acceptance: {
    completedChapters: 1,
    passed: false,
    reason: 'fixture blocker'
  }
}

const result = writeLiveReport({
  report: fixtureReport,
  jsonPath,
  mdPath,
  phaseTarget: 88,
  formatCompletedStageIds: stages => stages.map(stage => stage.id || stage.stageId).join('|')
})

assert.deepEqual(result, { jsonPath, mdPath })
assert.equal(existsSync(jsonPath), true, 'JSON report should be written')
assert.equal(existsSync(mdPath), true, 'Markdown report should be written')

const writtenJson = JSON.parse(readFileSync(jsonPath, 'utf8'))
assert.equal(writtenJson.project.name, 'FixtureLongform')
assert.equal(writtenJson.blocker.code, 'fixture_blocker')

const md = readFileSync(mdPath, 'utf8')
for (const section of ['## AI 代理', '## 模型继承', '## 规划层级', '## 章节', '## 故事块摘要', '## 质量观察', '## 阻断']) {
  assert.match(md, new RegExp(section), `Markdown report should include ${section}`)
}
assert.match(md, /完成章节: 1\/88/)
assert.match(md, /stage-1\|stage-2/)
assert.match(md, /fixture_warning: quality observation/)
assert.match(md, /fixture_blocker/)

const runnerSource = readFileSync('tmp/run_longform_browser_240w_phase1.mjs', 'utf8')
assert.doesNotMatch(runnerSource, /writeFileSync\s*\(\s*REPORT_MD\b/, 'runner should not write markdown report directly')
assert.doesNotMatch(runnerSource, /writeFileSync\s*\(\s*REPORT_JSON\b/, 'runner should not write JSON report directly')
assert.doesNotMatch(runnerSource, /const\s+lines\s*=\s*\[\s*['"`]# 240 万字长篇真实浏览器第一阶段报告/, 'runner should not keep long markdown lines construction')
assert.match(runnerSource, /writeLiveReport\s*\(/, 'runner wrapper should delegate to live-report-writer')

const writerSource = readFileSync('tmp/live-qa/reports/live-report-writer.mjs', 'utf8')
assert.doesNotMatch(writerSource, /chromium|page\.|fetch\s*\(|api\s*\(|aiomysql|mysql|SELECT\s+/i, 'report writer must stay pure: no browser/API/DB access')

console.log('live runner report writer contract passed')
