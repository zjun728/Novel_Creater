import { chromium } from './playwright-run/node_modules/playwright/index.mjs'
import { createHash } from 'node:crypto'
import { existsSync, mkdirSync, readFileSync } from 'node:fs'
import path from 'node:path'
import {
  assertChapterRangeFreeze,
  assertNoUnexpectedChapterStarted,
  assertSettingsAndRelationHealth,
  collectFreezeGuardSummary
} from './live-qa/guards/live-run-freeze-guards.mjs'
import { collectProjectHealthSnapshotFromApi } from './live-qa/audits/project-health-api-snapshot.mjs'
import { summarizeProjectHealthSnapshot } from './live-qa/audits/project-health-audit.mjs'
import { writeLiveReport } from './live-qa/reports/live-report-writer.mjs'
import { buildLiveRunnerRuntimeConfig } from './live-qa/runners/live-runner-runtime-config.mjs'
import {
  SETTING_CHANGE_CLASSIFICATIONS,
  classifySettingChangeRisk,
  isBatchAcceptableSettingChange,
  isPlaceholderSettingEntity,
  sortSettingEventsForConfirmation as sortSettingEventsByConfirmationOrder
} from '../frontend/src/utils/settingChangeRisk.js'
import {
  assessChapterWordCount,
  buildChapterWordTarget
} from '../frontend/src/utils/chapterWordTarget.js'
import { cleanGeneratedChapterText, getChapterTitleQuality } from '../frontend/src/prompts/chapter.js'

const FRONTEND = 'http://127.0.0.1:5173'
const API_BASE = 'http://127.0.0.1:8000/api'
const OUT_DIR = 'tmp/realistic-flow-qa'
const REPORT_JSON = process.env.LIVE_REPORT_JSON || path.join(OUT_DIR, 'latest-longform-browser-live-report.json')
const REPORT_MD = process.env.LIVE_REPORT_MD || path.join(OUT_DIR, 'latest-longform-browser-live-report.md')
const CHROME = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe'
const runtimeConfig = buildLiveRunnerRuntimeConfig({
  env: process.env
})
const EXISTING_PROJECT_ID = runtimeConfig.existingProjectId
const EXISTING_PROJECT_NAME = runtimeConfig.existingProjectName
const START_CHAPTER = runtimeConfig.startChapter
const STAGE_SETTLEMENT_DIAGNOSTICS = process.env.STAGE_SETTLEMENT_DIAGNOSTICS || path.join(OUT_DIR, `stage-continuation-settlement-before-${START_CHAPTER}.json`)
const RESUME_CHAPTER_WINDOW = runtimeConfig.resumeChapterWindow
const DEFAULT_PHASE_TARGET = runtimeConfig.defaultPhaseTarget
const MAX_PHASE_TARGET = runtimeConfig.maxPhaseTarget
const SETTING_CONFIRMATION_ORDER = ['new_entity', 'update_entity', 'relationship']
const PHASE_TARGET = runtimeConfig.phaseTarget
const RUN_CHAPTER_COUNT = runtimeConfig.runChapterCount
const FREEZE_FORBIDDEN_CHAPTERS = runtimeConfig.forbiddenChapters
const FINALIZATION_TIMEOUT_MS = Math.max(
  600000,
  Number(process.env.FINALIZATION_TIMEOUT_MS || 600000) || 600000
)
const BEAT_PLAN_ENTRY_LABELS = [
  '先做小纲'
]
const DRAFT_MODAL_ENTRY_LABELS = [
  '保存小纲并生成正文',
  '确认小纲并生成正文',
  '开始生成本章',
  '生成正文',
  '生成本章'
]
const DRAFT_ENTRY_LABELS = [
  '生成本章',
  '生成正文',
  '开始生成本章'
]
const DRAFT_REGENERATION_ENTRY_LABELS = [
  '重新生成正文',
  '重新生成本章',
  '重生成正文',
  '重新生成',
  ...DRAFT_ENTRY_LABELS
]
const DRAFT_GENERATION_ENTRY_LABELS = DRAFT_MODAL_ENTRY_LABELS
const DRAFT_GENERATION_PREP_LABELS = BEAT_PLAN_ENTRY_LABELS
const DRAFT_GENERATION_PAGE_ENTRY_LABELS = DRAFT_ENTRY_LABELS
const EXPECTED_PROVIDER_NAME = '联通云-DeepSeek-V4-Flash'
const EXPECTED_MODEL_NAME = 'DeepSeek-V4-Flash'
const EXPECTED_PROVIDER_ID = runtimeConfig.expectedProviderId

function loadStageSettlementDiagnostics() {
  if (!STAGE_SETTLEMENT_DIAGNOSTICS || !existsSync(STAGE_SETTLEMENT_DIAGNOSTICS)) return null
  try {
    return JSON.parse(readFileSync(STAGE_SETTLEMENT_DIAGNOSTICS, 'utf8'))
  } catch (error) {
    return {
      source: STAGE_SETTLEMENT_DIAGNOSTICS,
      error: error.message
    }
  }
}

const projectName = `LongformBrowser240w_${timestamp()}`
const liveConsoleErrors = []
const liveConsoleErrorEvents = []
const liveNetworkEvents = []
const postFinalizeSettlementByChapter = new Map()
const report = {
  mode: 'live',
  createdAt: new Date().toISOString(),
  createdCleanProject: runtimeConfig.createCleanProject,
  usesArchivedReports: false,
  target: {
    targetWords: 2400000,
    targetChapters: 480,
    phaseTargetChapters: PHASE_TARGET,
    startChapter: START_CHAPTER,
    endChapter: PHASE_TARGET,
    runChapterCount: RUN_CHAPTER_COUNT
  },
  project: {
    id: EXISTING_PROJECT_ID,
    name: EXISTING_PROJECT_NAME || projectName,
    failedSampleKept: 'LongformBrowser240w_20260618011942',
    failedSampleId: 'e39cc9f1-4697-402b-a32c-564bee7d1e36'
  },
  environment: {
    frontend: FRONTEND,
    backend: API_BASE,
    fixedPortsReused: true,
    browser: 'Chrome via Playwright'
  },
  serviceCleanupDiagnostics: {
    source: null,
    killedPids: [],
    skippedStalePids: [],
    skippedReason: [],
    pending: true
  },
  stageContinuationSettlementDiagnostics: loadStageSettlementDiagnostics(),
  aiProxy: {
    aiProxyUsed: false,
    providerId: '',
    providerName: '',
    modelName: '',
    browserConsoleCorsErrors: 0,
    backendAiRequests: 0,
    providerChatCompletionUrls: [],
    realRequestStages: []
  },
  stepsCompleted: [],
  settingInitialization: {
    groupedProgressVisible: false,
    diagnostics: [],
    pendingCandidatesCreated: 0,
    acceptedCandidates: 0,
    failedGroups: []
  },
  volumePlanning: {
    generated: false,
    placeholderWarnings: [],
    diagnostics: null
  },
  modelBinding: {
    status: null,
    settingsPageShowsInheritance: false,
    expectedProviderName: EXPECTED_PROVIDER_NAME,
    expectedModelName: EXPECTED_MODEL_NAME,
    expectedProviderId: EXPECTED_PROVIDER_ID,
    inheritedProviderMatched: false,
    actualProviderModelMatched: false,
    usedDeepseekV4ProFallback: false,
    taskProviders: {}
  },
  planningHierarchy: {
    projectChaptersPageChecked: false,
    legacyTextFound: []
  },
  storyBlockSummaries: [],
  storyBlockGranularity: {
    blocksCreated: 0,
    chaptersPerBlock: [],
    averageChaptersPerBlock: 0,
    singleChapterBlockCount: 0,
    consecutiveSingleChapterBlocks: 0,
    blockCompletionEvidence: [],
    storyBlockGranularityWarning: null,
    storyBlockStalledWarning: null,
    stageCountPerBlock: [],
    executedStageCountPerBlock: [],
    completedStageCountPerBlock: [],
    closedUnexecutedStageCountPerBlock: [],
    invalidatedStageCountPerBlock: [],
    storyBlockGranularityQualityHold: null,
    activeBlockRemainingStages: []
  },
  qualityWarnings: [],
  qualityBacklog: [
    {
      code: 'initial_setting_entity_name_quality',
      message: '初始设定抽取出现异常实体名：“现死去三年”。'
    },
    {
      code: 'setting_summary_placeholder_quality',
      message: '“陆沉舟之父”实体 summary 曾出现“第 ? 章自动识别的设定”，后续需单独修复实体命名/摘要质量。'
    },
    {
      code: 'chapter_1_too_short',
      message: '第 1 章曾出现明显低于 4500-6000 字目标体量的问题；本轮记录，不修。'
    },
    {
      code: 'chapter_2_bad_title',
      message: '第 2 章曾出现弱标题问题；本轮记录，不修章名策略。'
    },
    {
      code: 'story_block_prompt_overloaded',
      message: '第 3 章小纲空响应疑似与小纲上下文过载相关；本轮只修小纲上下文瘦身和诊断。'
    }
  ],
  beatPlanQualityRebuilds: [],
  chapterReports: [],
  hardFailWordCountChapters: [],
  pendingSettingsCount: 0,
  freezeGuardSummary: null,
  blocker: null,
  acceptance: {
    passed: false,
    completedChapters: 0,
    reason: ''
  }
}

mkdirSync(OUT_DIR, { recursive: true })

function timestamp() {
  const now = new Date()
  const pad = n => String(n).padStart(2, '0')
  return `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}_${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`
}

function mark(step) {
  if (!report.stepsCompleted.includes(step)) report.stepsCompleted.push(step)
}

function pushLiveNetworkEvent(event) {
  liveNetworkEvents.push({
    at: new Date().toISOString(),
    ...event
  })
  if (liveNetworkEvents.length > 400) {
    liveNetworkEvents.splice(0, liveNetworkEvents.length - 400)
  }
}

function pushLiveConsoleError(text) {
  liveConsoleErrors.push(text)
  liveConsoleErrorEvents.push({
    at: new Date().toISOString(),
    text
  })
  if (liveConsoleErrors.length > 200) {
    liveConsoleErrors.splice(0, liveConsoleErrors.length - 200)
  }
  if (liveConsoleErrorEvents.length > 200) {
    liveConsoleErrorEvents.splice(0, liveConsoleErrorEvents.length - 200)
  }
}

function consoleErrorsSince(startedAtMs = 0) {
  return consoleErrorEventsSince(startedAtMs).map(event => event.text)
}

function consoleErrorEventsSince(startedAtMs = 0) {
  const threshold = Number(startedAtMs || 0)
  return liveConsoleErrorEvents.filter(event => !threshold || Date.parse(event.at) >= threshold)
}

function staleConsoleErrorsBefore(startedAtMs = 0) {
  const threshold = Number(startedAtMs || 0)
  if (!threshold) return []
  return liveConsoleErrorEvents
    .filter(event => Date.parse(event.at) < threshold && isContextFailureText(event.text))
    .map(event => event.text)
}

function isContextFailureText(text = '') {
  return /创作上下文.*失败|上下文.*失败|加载.*失败|Failed to fetch/i.test(String(text || ''))
}

function isoFromMs(value = 0) {
  return value ? new Date(value).toISOString() : ''
}

function latestPostFinalizeAiProxyFailureText() {
  return liveConsoleErrors
    .slice()
    .reverse()
    .find(text => {
      const value = String(text || '')
      return /后端 AI 代理请求失败|供应商返回失败/.test(value) &&
        /(?:502|503|504|Bad Gateway)/i.test(value) &&
        /memory_auditModelId|memory_audit|定稿后|审稿失败/.test(value)
    }) || ''
}

function classifyPostFinalizeMarkerFailure(marker = {}, fallbackText = '') {
  if (!marker?.retryablePostprocessFailure && !marker?.storyBlockSettlementFailure && !marker?.postFinalizeFailed) return null
  const storyBlockFailure = marker.storyBlockSettlementFailure || null
  const retryableFailure = marker.retryablePostprocessFailure || null
  const detail = storyBlockFailure || retryableFailure || {}
  const message = detail.message || fallbackText || '定稿后处理失败。'
  const conflictText = `${marker.status || ''} ${detail.code || ''} ${message}`
  if (storyBlockFailure || /story_block_stage_update_conflict|已被小纲或定稿章节引用的阶段不能回改|已锁定阶段不能被删除或替换/i.test(conflictText)) {
    return {
      code: 'post_finalize_story_block_settlement_failed',
      conflictCode: 'story_block_stage_update_conflict',
      stage: 'post_finalize_story_block_settlement_failed',
      reasonKey: 'story_block_settlement_failure',
      message: `定稿后故事块结算失败：${message}`,
      detail,
      retryable: false
    }
  }
  return {
    code: 'post_finalize_ai_proxy_failed',
    conflictCode: '',
    stage: 'post_finalize_ai_proxy_failed',
    reasonKey: 'retryable_postprocess_failure',
    message: `定稿后 AI 代理请求失败：${message || '后处理需要重试。'}`,
    detail,
    retryable: detail.retryable !== false
  }
}

function promotePostFinalizeAiProxyFailureFromConsole() {
  if (report.blocker) return false
  const failureText = latestPostFinalizeAiProxyFailureText()
  if (!failureText) return false
  const chapter = report.chapterReports.at(-1) || null
  if (chapter) {
    chapter.postFinalizeFailed = true
    chapter.retryablePostprocessFailure = true
    chapter.postFinalizeFailureMessage = failureText
    chapter.progressStage = chapter.progressStage || 'post_finalize_ai_proxy_failed'
  }
  report.blocker = {
    blocked: true,
    stage: 'post_finalize',
    code: 'post_finalize_ai_proxy_failed',
    chapterNum: chapter?.chapterNum || null,
    message: `定稿后 AI 代理请求失败：${failureText}`,
    consoleError: failureText,
    providerName: report.aiProxy.providerName,
    modelName: report.aiProxy.modelName,
    aiProxyUsed: report.aiProxy.aiProxyUsed,
    browserConsoleCorsErrors: report.aiProxy.browserConsoleCorsErrors,
    providerChatCompletionUrls: report.aiProxy.providerChatCompletionUrls.length
  }
  report.acceptance.passed = false
  report.acceptance.reason = report.blocker.message
  return true
}

function promoteFinalizeFailureFromFlowEvents() {
  if (report.blocker) return false
  for (const chapter of report.chapterReports) {
    const failed = chapter.flowEvents?.finalize_failed
    if (!failed) continue
    const belowHardMinModal = Boolean(failed.finalizeDiagnostics?.belowHardMinModal) ||
      isBelowHardMinModalText(failed.finalizeDiagnostics?.modalText || '') ||
      (Array.isArray(failed.finalizeDiagnostics?.dialogTexts) && failed.finalizeDiagnostics.dialogTexts.some(isBelowHardMinModalText))
    const staleBelowHardMinModal = Boolean(failed.finalizeDiagnostics?.modalStale) ||
      failed.finalizeDiagnostics?.blockerSource === 'stale_modal'
    const selectedVersionStale = Boolean(failed.finalizeDiagnostics?.selectedVersionStale) ||
      failed.finalizeDiagnostics?.blockerSource === 'selected_version_stale'
    const code = staleBelowHardMinModal
      ? 'stale_below_hard_min_modal'
      : (selectedVersionStale
          ? 'selected_version_stale'
          : (belowHardMinModal ? 'chapter_below_hard_min' : (failed.code || 'finalize_timed_out')))
    const isTimeout = code === 'finalize_timed_out'
    const message = code === 'stale_below_hard_min_modal'
      ? `第 ${chapter.chapterNum} 章旧低字数弹窗阻断定稿。`
      : code === 'selected_version_stale'
      ? `第 ${chapter.chapterNum} 章最新候选已过硬线，但页面仍选中旧候选。`
      : code === 'chapter_below_hard_min'
      ? `第 ${chapter.chapterNum} 章低于硬下限，未进入定稿。`
      : isTimeout
      ? `第 ${chapter.chapterNum} 章定稿超时：${failed.message || 'finalize timed out'}`
      : `第 ${chapter.chapterNum} 章定稿失败：${failed.message || code}`
    report.blocker = {
      blocked: true,
      stage: code === 'selected_version_stale'
        ? 'finalize_version_selection'
        : (code === 'chapter_below_hard_min' || code === 'stale_below_hard_min_modal' ? 'word_count_quality_gate' : 'finalize'),
      code,
      chapterNum: chapter.chapterNum,
      message,
      finalizeDiagnostics: chapter.finalizeDiagnostics || failed.finalizeDiagnostics || null
    }
    report.acceptance.passed = false
    report.acceptance.reason = report.blocker.message
    return true
  }
  return false
}

function syncReportBlockerFromFlowEvents() {
  if (syncHardWordCountBlocker()) return
  if (promoteChapterBelowHardMinFromFlowEvents()) return
  if (report.blocker) {
    if (!report.acceptance.reason) {
      report.acceptance.reason = report.blocker.message || report.blocker.code || '流程已阻断。'
    }
    return
  }
  promotePostFinalizeAiProxyFailureFromConsole()
  if (report.blocker) return
  promoteFinalizeFailureFromFlowEvents()
  if (report.blocker) return
  for (const chapter of report.chapterReports) {
    const failed = chapter.flowEvents?.settings_confirmation_failed
    if (!failed) continue
    const pendingHardConflicts = Array.isArray(failed.pendingHardConflicts) ? failed.pendingHardConflicts : []
    const code = failed.code || (pendingHardConflicts.length ? 'hard_conflict_setting_review_required' : 'settings_confirmation_failed')
    if (code !== 'hard_conflict_setting_review_required' && !pendingHardConflicts.length) continue
    report.blocker = {
      blocked: true,
      stage: 'settings_confirmation_failed',
      code: 'hard_conflict_setting_review_required',
      chapterNum: chapter.chapterNum,
      message: failed.message || '仍有硬冲突设定需要逐条确认，处理后才能进入下一章。',
      pendingHardConflicts
    }
    report.acceptance.passed = false
    report.acceptance.reason = report.blocker.message
    return
  }
  if (report.acceptance.passed === false && report.acceptance.reason && !report.blocker) {
    report.blocker = {
      blocked: true,
      stage: 'acceptance_failed',
      code: 'acceptance_failed',
      message: report.acceptance.reason
    }
  }
}

function promoteChapterBelowHardMinFromFlowEvents() {
  if (report.blocker) return false
  for (const chapter of report.chapterReports) {
    const failed = chapter.flowEvents?.chapter_below_hard_min
    if (!failed) continue
    const hardFailWordCountChapters = failed.hardFailWordCountChapters || [{
      chapterNum: chapter.chapterNum,
      title: chapter.title || '',
      wordCount: chapter.wordCount || failed.candidateWordCount || 0,
      cjkCharCount: chapter.cjkCharCount || 0,
      status: chapter.wordCountPolicy?.status || 'below_hard_min',
      hardMin: failed.liveHardMin || failed.appHardMin || chapter.wordCountPolicy?.hardMin || null,
      softMin: chapter.wordCountPolicy?.softMin || null,
      targetRange: chapter.wordCountPolicy?.targetRange || null
    }]
    report.hardFailWordCountChapters = hardFailWordCountChapters
    report.blocker = {
      blocked: true,
      stage: 'word_count_quality_gate',
      code: 'chapter_below_hard_min',
      chapterNum: chapter.chapterNum,
      message: `第 ${chapter.chapterNum} 章低于硬下限，未进入定稿。`,
      hardFailWordCountChapters,
      appHardMin: failed.appHardMin || null,
      liveHardMin: failed.liveHardMin || null,
      wordTarget: failed.wordTarget || chapter.wordTarget || null,
      candidateWordCount: failed.candidateWordCount || chapter.wordCount || 0,
      modalText: failed.modalText || '',
      regenerateAttempted: Boolean(failed.regenerateAttempted),
      regenerateSucceeded: Boolean(failed.regenerateSucceeded)
    }
    report.acceptance.passed = false
    report.acceptance.reason = report.blocker.message
    return true
  }
  return false
}

function syncHardWordCountBlocker() {
  const hardFailWordCountChapters = report.chapterReports
    .filter(chapter => chapter.finalized && chapter.wordCountPolicy && chapter.wordCountPolicy.hardPass === false)
    .map(chapter => ({
      chapterNum: chapter.chapterNum,
      title: chapter.title || '',
      wordCount: chapter.wordCount || 0,
      cjkCharCount: chapter.cjkCharCount || 0,
      status: chapter.wordCountPolicy.status,
      hardMin: chapter.wordCountPolicy.hardMin,
      softMin: chapter.wordCountPolicy.softMin,
      targetRange: chapter.wordCountPolicy.targetRange
    }))
  if (!hardFailWordCountChapters.length && report.blocker?.code === 'chapter_below_hard_min') {
    report.hardFailWordCountChapters = Array.isArray(report.blocker.hardFailWordCountChapters)
      ? report.blocker.hardFailWordCountChapters
      : report.hardFailWordCountChapters
    return false
  }
  report.hardFailWordCountChapters = hardFailWordCountChapters
  if (!hardFailWordCountChapters.length) return false

  const first = hardFailWordCountChapters[0]
  report.blocker = {
    blocked: true,
    stage: 'word_count_quality_gate',
    code: 'chapter_below_hard_min',
    chapterNum: first.chapterNum,
    message: `第 ${first.chapterNum} 章正文低于硬下限，请扩写或重新生成后再定稿。`,
    hardFailWordCountChapters
  }
  report.acceptance.passed = false
  report.acceptance.reason = report.blocker.message
  return true
}

function writeReport() {
  syncReportBlockerFromFlowEvents()
  return writeLiveReport({
    report,
    jsonPath: REPORT_JSON,
    mdPath: REPORT_MD,
    phaseTarget: PHASE_TARGET,
    formatCompletedStageIds
  })
}

function expectedRelationRiskFromReport() {
  return {
    activeRelationCount: report.relationshipAudit?.activeRelationCount,
    activeSyntheticRelationCount: 0,
    activeSelfRelationCount: 0,
    activeWrongLayerRelationCount: 0,
    activeMissingEndpointRelationCount: 0
  }
}

async function refreshProjectHealthAuditForFreezeGuard() {
  if (!report.project.id) {
    report.projectHealthAudit = {
      ok: false,
      skipped: true,
      skippedReason: 'projectIdMissing',
      relationshipAudit: null,
      pendingSettingsCount: report.pendingSettingsCount ?? 0
    }
    return report.projectHealthAudit
  }
  const snapshot = await collectProjectHealthSnapshotFromApi({
    api,
    projectId: report.project.id
  })
  const health = summarizeProjectHealthSnapshot(snapshot, {
    projectId: report.project.id,
    forbiddenChapters: FREEZE_FORBIDDEN_CHAPTERS
  })
  report.projectHealthAudit = health
  report.relationshipAudit = health.relationshipAudit
  report.pendingSettingsCount = health.pendingSettingsCount
  return health
}

async function runFreezeGuards() {
  await refreshProjectHealthAuditForFreezeGuard()
  const unexpectedChapterNum = PHASE_TARGET + 1
  const expectedRelationRisk = expectedRelationRiskFromReport()
  assertChapterRangeFreeze({
    report,
    startChapter: START_CHAPTER,
    endChapter: PHASE_TARGET,
    forbiddenChapters: FREEZE_FORBIDDEN_CHAPTERS
  })
  assertNoUnexpectedChapterStarted({ report, chapterNum: unexpectedChapterNum })
  assertSettingsAndRelationHealth({
    report,
    expectedPendingCount: 0,
    expectedRelationRisk
  })
  report.freezeGuardSummary = collectFreezeGuardSummary({
    report,
    startChapter: START_CHAPTER,
    endChapter: PHASE_TARGET,
    forbiddenChapters: FREEZE_FORBIDDEN_CHAPTERS,
    unexpectedChapterNum,
    expectedPendingCount: 0,
    expectedRelationRisk
  })
  return report.freezeGuardSummary
}

async function api(pathname, options = {}) {
  const res = await fetch(`${API_BASE}${pathname}`, options)
  if (!res.ok) throw new Error(`API ${res.status} ${pathname}: ${await res.text()}`)
  const text = await res.text()
  return text ? JSON.parse(text) : null
}

function toList(value) {
  return Array.isArray(value) ? value : []
}

function providerBrief(provider) {
  if (!provider) return null
  return {
    id: provider.id || '',
    name: provider.name || '',
    model: provider.model || '',
    providerType: provider.providerType || provider.provider_type || '',
    supportsJSON: provider.supportsJSON !== false && provider.supports_json !== false
  }
}

function normalizeProviderToken(value = '') {
  return String(value || '').trim().toLowerCase()
}

function providerMatchesExpected(provider = {}) {
  const providerId = normalizeProviderToken(provider.id || provider.providerId)
  const providerName = normalizeProviderToken(provider.name || provider.providerName)
  const modelName = normalizeProviderToken(provider.model || provider.modelName)
  const expectedProviderId = normalizeProviderToken(EXPECTED_PROVIDER_ID)
  const expectedProviderName = normalizeProviderToken(EXPECTED_PROVIDER_NAME)
  const expectedModelName = normalizeProviderToken(EXPECTED_MODEL_NAME)
  const providerMatched = expectedProviderId
    ? providerId === expectedProviderId
    : providerName === expectedProviderName
  return providerMatched && modelName === expectedModelName
}

function pushAiProxyStage(stage) {
  report.aiProxy.realRequestStages.push({
    at: new Date().toISOString(),
    ...stage
  })
  if (report.aiProxy.realRequestStages.length > 120) {
    report.aiProxy.realRequestStages = report.aiProxy.realRequestStages.slice(-120)
  }
}

function isBackendAiProxyUrl(url) {
  return url.includes('/api/ai/chat-completions')
}

function isBrowserProviderChatCompletionUrl(url) {
  return /\/chat\/completions(?:\?|$)/.test(url) && !url.includes('/api/ai/chat-completions')
}

function isBackendApiUrl(url) {
  return typeof url === 'string' && url.startsWith(API_BASE)
}

function apiPathFromUrl(url) {
  try {
    const parsed = new URL(url)
    return parsed.pathname.replace(/^\/api/, '') + parsed.search
  } catch {
    return String(url || '').replace(API_BASE, '')
  }
}

function isWriterContextApiPath(pathname = '') {
  return /\/projects\/[^/]+\/(?:bible|outline|characters|plot-threads|canon-facts|settings\/entities|settings\/relations|settings\/change-events|volumes|story-blocks|correction-tasks|seeds|content-state|chapters)(?:[/?]|$)/.test(pathname)
}

function contextNetworkEventsSince(startedAtMs = 0) {
  return liveNetworkEvents.filter(event => {
    const at = Date.parse(event.at || '')
    return Number.isFinite(at) &&
      at >= startedAtMs &&
      isWriterContextApiPath(event.path || apiPathFromUrl(event.url || ''))
  })
}

function updateAiProxyProviderFromBinding(taskProviders = {}) {
  const provider = taskProviders.writing || Object.values(taskProviders).find(Boolean)
  if (!provider) return
  report.aiProxy.providerId = provider.id || ''
  report.aiProxy.providerName = provider.name || ''
  report.aiProxy.modelName = provider.model || ''
}

async function resolveTaskProvidersForReport(projectId) {
  const [status, bindings, providers] = await Promise.all([
    api(`/projects/${projectId}/bindings/status`).catch(error => ({ error: error.message })),
    api(`/projects/${projectId}/bindings`).catch(() => null),
    api('/providers').catch(() => [])
  ])
  const providerList = toList(providers)
  const byId = new Map(providerList.map(provider => [provider.id, provider]))
  const taskFieldMap = {
    writing: 'writingModelId',
    brainstorm: 'brainstormModelId',
    outline: 'outlineModelId',
    audit: 'auditModelId',
    summary: 'summaryModelId',
    extraction: 'extractionModelId',
    market: 'marketModelId',
    polish: 'polishModelId'
  }
  const taskProviders = {}
  for (const [task, field] of Object.entries(taskFieldMap)) {
    const provider = byId.get(bindings?.[field])
    taskProviders[task] = providerBrief(provider)
  }
  const usedProviders = Object.values(taskProviders).filter(Boolean)
  const fallbackPattern = /deepseek[-_\s]*v4[-_\s]*pro/i
  const actualProviderModelMatched = usedProviders.length > 0 && usedProviders.every(providerMatchesExpected)
  return {
    status,
    bindings,
    taskProviders,
    actualProviderModelMatched,
    inheritedProviderMatched: actualProviderModelMatched,
    usedDeepseekV4ProFallback: usedProviders.some(provider => fallbackPattern.test(`${provider.name} ${provider.model}`))
  }
}

async function validateModelInheritance(page) {
  const resolved = await resolveTaskProvidersForReport(report.project.id)
  report.modelBinding.status = resolved.status
  report.modelBinding.taskProviders = resolved.taskProviders
  report.modelBinding.inheritedProviderMatched = resolved.inheritedProviderMatched
  report.modelBinding.actualProviderModelMatched = resolved.actualProviderModelMatched
  report.modelBinding.usedDeepseekV4ProFallback = resolved.usedDeepseekV4ProFallback
  updateAiProxyProviderFromBinding(resolved.taskProviders)

  await page.evaluate(projectId => {
    window.localStorage?.setItem('novel_creator_last_binding_project_id', projectId)
  }, report.project.id).catch(() => {})
  await page.goto(`${FRONTEND}/settings`, { waitUntil: 'domcontentloaded' })
  report.modelBinding.settingsPageShowsInheritance = await waitFor('settings page inherited binding status', async () =>
    page.getByText(/已继承上一个项目模型配置/).isVisible().catch(() => false),
  60000, 1000).catch(() => false)

  if (!report.modelBinding.status?.hasBinding) {
    throw new Error('新项目没有继承到任务模型映射')
  }
  if (!report.modelBinding.status?.inherited) {
    throw new Error('新项目任务模型映射未标记为继承状态')
  }
  if (!report.modelBinding.settingsPageShowsInheritance) {
    throw new Error('设置页未显示模型配置继承来源')
  }
  if (!report.modelBinding.inheritedProviderMatched) {
    throw new Error(`继承模型不是期望的 ${EXPECTED_PROVIDER_NAME} / ${EXPECTED_MODEL_NAME}`)
  }
  if (report.modelBinding.usedDeepseekV4ProFallback) {
    throw new Error('检测到 deepseek-v4-pro 兜底模型被用于任务映射')
  }
  mark('validated_inherited_task_model_binding_in_browser')
}

async function validatePlanningHierarchyText(page) {
  await page.goto(`${FRONTEND}/project/${report.project.id}?tab=chapters`, { waitUntil: 'domcontentloaded' })
  const bodyText = await page.locator('body').innerText({ timeout: 60000 }).catch(() => '')
  const legacyPhrases = [
    '未来 3-5 章近景规划',
    '先按分卷建立粗结构',
    '近景滚动规划进入章节上下文'
  ]
  report.planningHierarchy.projectChaptersPageChecked = true
  report.planningHierarchy.legacyTextFound = legacyPhrases.filter(phrase => bodyText.includes(phrase))
  if (report.planningHierarchy.legacyTextFound.length) {
    throw new Error(`章节管理页仍出现旧主链路文案：${report.planningHierarchy.legacyTextFound.join(', ')}`)
  }
  mark('validated_planning_hierarchy_text_in_browser')
}

async function waitFor(description, predicate, timeoutMs = 120000, intervalMs = 2000) {
  const started = Date.now()
  let lastError = null
  while (Date.now() - started < timeoutMs) {
    try {
      const value = await predicate()
      if (value) return value
    } catch (error) {
      lastError = error
    }
    await new Promise(resolve => setTimeout(resolve, intervalMs))
  }
  throw new Error(`${description} timed out${lastError ? `: ${lastError.message}` : ''}`)
}

function exactButton(page, text) {
  return page.getByRole('button', { name: new RegExp(`^${escapeRegExp(text)}$`) })
}

function escapeRegExp(text) {
  return String(text).replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

async function clickButton(page, text, timeout = 30000) {
  const locator = exactButton(page, text).last()
  await locator.waitFor({ state: 'visible', timeout })
  await waitFor(`button ${text} enabled`, async () => locator.isEnabled(), timeout, 500)
  try {
    await locator.click({ timeout })
  } catch (error) {
    const message = String(error?.message || '')
    const maskCount = await page.locator('.n-modal-mask').count().catch(() => 0)
    const blockedByDialog = maskCount > 0
      || /intercepts pointer events|n-modal-mask|Timeout/i.test(message)
    if (!blockedByDialog) throw error
    await dismissAppDialogs(page)
    await waitFor(`button ${text} enabled after dialog cleanup`, async () => locator.isEnabled(), timeout, 500)
    await locator.click({ timeout })
  }
}

async function tryClickExactButton(page, text, timeout = 5000) {
  const locator = exactButton(page, text).last()
  const visible = await locator.isVisible().catch(() => false)
  if (!visible) return false
  const enabled = await locator.isEnabled().catch(() => false)
  if (!enabled) return false
  try {
    await locator.click({ timeout })
    return true
  } catch {
    return false
  }
}

async function collectVisibleButtons(page) {
  return page.locator('button').evaluateAll(buttons => {
    const isVisible = element => {
      const style = window.getComputedStyle(element)
      const rect = element.getBoundingClientRect()
      return style.display !== 'none' &&
        style.visibility !== 'hidden' &&
        rect.width > 0 &&
        rect.height > 0
    }
    return buttons
      .map((button, index) => ({
        index,
        text: String(button.innerText || button.textContent || '').replace(/\s+/g, ' ').trim(),
        visible: isVisible(button),
        enabled: !(button.disabled || button.getAttribute('aria-disabled') === 'true'),
        title: button.getAttribute('title') || '',
        className: button.className || ''
      }))
      .filter(item => item.visible)
  }).catch(() => [])
}

async function isBeatPlanModalVisible(page) {
  return page.locator('.n-modal, .n-modal-container, .n-dialog').evaluateAll(nodes => {
    const isVisible = element => {
      const style = window.getComputedStyle(element)
      const rect = element.getBoundingClientRect()
      return style.display !== 'none' &&
        style.visibility !== 'hidden' &&
        rect.width > 0 &&
        rect.height > 0
    }
    return nodes.some(node => {
      const text = String(node.innerText || node.textContent || '')
      return isVisible(node) && /小纲|生成正文|生成本章/.test(text)
    })
  }).catch(() => false)
}

async function collectDraftGenerationEntryDiagnostics(page, chapterNum, chapterId = '') {
  const visibleButtonItems = await collectVisibleButtons(page)
  const visibleButtons = visibleButtonItems.map(item => item.text).filter(Boolean)
  const enabledButtons = visibleButtonItems
    .filter(item => item.enabled)
    .map(item => item.text)
    .filter(Boolean)
  const visible = await collectVisibleDiagnostics(page)
  const beatPlanRecord = await api(`/projects/${report.project.id}/chapter-beat-plan/${chapterNum}`).catch(() => null)
  return {
    currentUrl: page.url(),
    visibleButtons,
    enabledButtons,
    visibleButtonItems,
    beatPlanModalVisible: await isBeatPlanModalVisible(page),
    activeAction: visible.activeAction || [],
    hasSavedBeatPlan: Boolean(beatPlanRecord?.content),
    chapterId,
    chapterBeatPlanId: beatPlanRecord?.id || '',
    page: visible
  }
}

async function collectWriterContextDiagnostics(page, chapterNum, contextWaitStartedAtMs = 0, writerEnteredAtMs = contextWaitStartedAtMs) {
  const chapterId = await currentChapterId(chapterNum).catch(() => '')
  const entryDiagnostics = await collectDraftGenerationEntryDiagnostics(page, chapterNum, chapterId)
  const writerHumanityContextDiagnostics = await readWriterHumanityContextDiagnostics(page, chapterNum)
  const messages = await visibleMessageTexts(page)
  const eventWindowStartedAtMs = Number(writerEnteredAtMs || contextWaitStartedAtMs || 0)
  const labels = Array.from(new Set([
    ...DRAFT_GENERATION_PREP_LABELS,
    ...DRAFT_GENERATION_PAGE_ENTRY_LABELS,
    ...DRAFT_GENERATION_ENTRY_LABELS
  ]))
  const disabledDraftEntryLabels = labels.filter(label =>
    entryDiagnostics.visibleButtons.includes(label) &&
    !entryDiagnostics.enabledButtons.includes(label)
  )
  const enabledDraftEntryLabels = labels.filter(label => entryDiagnostics.enabledButtons.includes(label))
  const contextLoadingVisible = entryDiagnostics.visibleButtons.includes('上下文加载中') ||
    await page.getByText(/上下文加载中|正在加载创作上下文/).isVisible().catch(() => false)
  const contextEvents = contextNetworkEventsSince(eventWindowStartedAtMs)
  const contextApiRequests = contextEvents
    .filter(event => event.kind === 'request')
    .map(event => ({
      at: event.at,
      method: event.method,
      path: event.path || apiPathFromUrl(event.url || '')
    }))
  const contextApiFailures = contextEvents
    .filter(event => event.kind === 'requestfailed' || Number(event.status || 0) >= 400)
    .map(event => ({
      at: event.at,
      method: event.method,
      path: event.path || apiPathFromUrl(event.url || ''),
      status: event.status || null,
      errorText: event.errorText || ''
    }))
  const visibleContextFailureTexts = await page.getByText(/创作上下文加载失败|上下文加载失败/).allTextContents().catch(() => [])
  const visibleContextFailureMessages = [...messages, ...visibleContextFailureTexts]
    .filter(text => /创作上下文.*失败|上下文加载.*失败/i.test(String(text || '')))
  const recentConsoleContextFailures = consoleErrorsSince(eventWindowStartedAtMs).filter(isContextFailureText)
  const staleConsoleErrorsIgnored = staleConsoleErrorsBefore(eventWindowStartedAtMs)
  const currentContextFailures = [
    ...visibleContextFailureMessages.map(message => ({ source: 'visible', message })),
    ...recentConsoleContextFailures.map(message => ({ source: 'console', message })),
    ...contextApiFailures.map(failure => ({
      source: 'api',
      message: `${failure.method || 'GET'} ${failure.path || ''} ${failure.status || failure.errorText || ''}`.trim(),
      ...failure
    }))
  ]
  const contextFailureMessages = currentContextFailures.map(failure => failure.message).filter(Boolean)
  return {
    ...entryDiagnostics,
    writerEnteredAt: isoFromMs(writerEnteredAtMs),
    contextWaitStartedAt: isoFromMs(contextWaitStartedAtMs),
    contextLoadingVisible,
    contextLoadingDurationMs: Math.max(0, Date.now() - contextWaitStartedAtMs),
    contextApiRequests,
    contextApiFailures,
    disabledDraftEntryLabels,
    enabledDraftEntryLabels,
    lastConsoleErrors: liveConsoleErrors.slice(-12),
    visibleErrorMessages: visibleContextFailureMessages,
    recentConsoleContextFailures,
    staleConsoleErrorsIgnored,
    currentContextFailures,
    contextFailureMessages,
    writerHumanityContextDiagnostics,
    companionVoiceCardsInjected: writerHumanityContextDiagnostics?.companionVoiceCardsInjected ?? null,
    companionVoiceCardNames: writerHumanityContextDiagnostics?.companionVoiceCardNames || [],
    sampleCardInjected: writerHumanityContextDiagnostics?.sampleCardInjected ?? false,
    sampleCardId: writerHumanityContextDiagnostics?.sampleCardId || '',
    sampleCardTitle: writerHumanityContextDiagnostics?.sampleCardTitle || '',
    sampleCardType: writerHumanityContextDiagnostics?.sampleCardType || '',
    sampleInjectionReason: writerHumanityContextDiagnostics?.sampleInjectionReason || '',
    microDemoChars: writerHumanityContextDiagnostics?.microDemoChars || 0,
    sourceFieldsStripped: writerHumanityContextDiagnostics?.sourceFieldsStripped ?? true,
    sampleLeakageDetected: writerHumanityContextDiagnostics?.sampleLeakageDetected ?? false
  }
}

async function waitForWriterContextReady(page, chapterNum, options = {}) {
  const timeoutMs = typeof options === 'number'
    ? options
    : Math.max(1000, Number(options.timeoutMs || 180000) || 180000)
  const writerEnteredAtMs = typeof options === 'object' && options.writerEnteredAtMs
    ? Number(options.writerEnteredAtMs)
    : Date.now()
  const started = Date.now()
  let lastDiagnostics = null
  while (Date.now() - started < timeoutMs) {
    lastDiagnostics = await collectWriterContextDiagnostics(page, chapterNum, started, writerEnteredAtMs)
    const contextReadyByEnabledEntry = !lastDiagnostics.contextLoadingVisible &&
      lastDiagnostics.enabledDraftEntryLabels.length > 0 &&
      lastDiagnostics.contextApiFailures.length === 0
    if (contextReadyByEnabledEntry) {
      return {
        ...lastDiagnostics,
        contextReadyByEnabledEntry: true
      }
    }
    if (lastDiagnostics.currentContextFailures.length) {
      const error = new Error(`writer_context_loading_failed: 第 ${chapterNum} 章创作上下文加载失败：${lastDiagnostics.contextFailureMessages[0]}`)
      error.code = 'writer_context_loading_failed'
      error.liveDiagnostics = {
        stage: 'writer_context_loading_failed',
        chapterNum,
        ...lastDiagnostics
      }
      throw error
    }
    if (!lastDiagnostics.contextLoadingVisible || lastDiagnostics.enabledDraftEntryLabels.length) {
      return {
        ...lastDiagnostics,
        contextReadyByEnabledEntry: false
      }
    }
    await new Promise(resolve => setTimeout(resolve, 1000))
  }

  const diagnostics = lastDiagnostics || await collectWriterContextDiagnostics(page, chapterNum, started, writerEnteredAtMs)
  const error = new Error(`writer_context_loading_timeout: 第 ${chapterNum} 章写字台创作上下文加载超时。`)
  error.code = 'writer_context_loading_timeout'
  error.liveDiagnostics = {
    stage: 'writer_context_loading_timeout',
    chapterNum,
    ...diagnostics,
    contextLoadingDurationMs: Math.max(0, Date.now() - started)
  }
  throw error
}

async function clickGenerationEntryByLabels(page, chapterNum, labels, options = {}) {
  const chapterId = options.chapterId || (await currentChapterId(chapterNum).catch(() => ''))
  const timeoutMs = Math.max(1000, Number(options.clickTimeoutMs || 5000) || 5000)
  const started = Date.now()
  let lastDiagnostics = null

  while (Date.now() - started < timeoutMs) {
    const diagnostics = await collectDraftGenerationEntryDiagnostics(page, chapterNum, chapterId)
    const matchingVisibleLabels = labels.filter(label => diagnostics.visibleButtons.includes(label))
    const matchingEnabledLabels = labels.filter(label => diagnostics.enabledButtons.includes(label))
    lastDiagnostics = {
      ...diagnostics,
      matchingVisibleLabels,
      matchingEnabledLabels,
      entryVisibleButDisabled: matchingVisibleLabels.length > 0 && matchingEnabledLabels.length === 0,
      entryWaitTimedOut: false
    }

    for (const label of labels) {
      const locator = exactButton(page, label).last()
      const visible = await locator.isVisible().catch(() => false)
      if (!visible) continue
      const enabled = await locator.isEnabled().catch(() => false)
      if (!enabled) continue
      try {
        const remainingMs = Math.max(1000, timeoutMs - (Date.now() - started))
        await locator.click({ timeout: Math.min(remainingMs, 10000) })
      } catch {
        continue
      }
      const clickedAt = new Date().toISOString()
      return {
        clicked: true,
        label,
        clickedAt,
        diagnostics: lastDiagnostics
      }
    }

    await new Promise(resolve => setTimeout(resolve, 500))
  }

  const diagnostics = lastDiagnostics || await collectDraftGenerationEntryDiagnostics(page, chapterNum, chapterId)
  const code = options.errorCode || 'generation_entry_not_found'
  const message = options.errorMessage || `第 ${chapterNum} 章找不到生成入口。`
  const error = new Error(`${code}: ${message}`)
  error.code = code
  error.liveDiagnostics = {
    stage: code,
    chapterNum,
    ...diagnostics,
    matchingVisibleLabels: labels.filter(label => (diagnostics.visibleButtons || []).includes(label)),
    matchingEnabledLabels: labels.filter(label => (diagnostics.enabledButtons || []).includes(label)),
    entryVisibleButDisabled: labels.some(label => (diagnostics.visibleButtons || []).includes(label)) &&
      !labels.some(label => (diagnostics.enabledButtons || []).includes(label)),
    entryWaitTimedOut: true
  }
  throw error
}

async function clickBeatPlanEntry(page, chapterNum, options = {}) {
  const clicked = await clickGenerationEntryByLabels(page, chapterNum, BEAT_PLAN_ENTRY_LABELS, {
    ...options,
    errorCode: 'beat_plan_entry_not_found',
    errorMessage: `第 ${chapterNum} 章找不到小纲生成入口。`
  })
  return {
    ...clicked,
    beatPlanEntryLabel: clicked.label,
    beatPlanStartedAt: clicked.clickedAt
  }
}

async function clickDraftEntry(page, chapterNum, options = {}) {
  const labels = options.includeModal === false
    ? DRAFT_ENTRY_LABELS
    : Array.from(new Set([...DRAFT_MODAL_ENTRY_LABELS, ...DRAFT_ENTRY_LABELS]))
  const clicked = await clickGenerationEntryByLabels(page, chapterNum, labels, {
    ...options,
    errorCode: 'draft_generation_entry_not_found',
    errorMessage: `第 ${chapterNum} 章找不到正文生成入口。`
  })
  return {
    ...clicked,
    generationEntryLabel: clicked.label,
    draftGenerationEntryLabel: clicked.label,
    draftGenerationStartedAt: clicked.clickedAt
  }
}

async function clickDraftRegenerationEntry(page, chapterNum, options = {}) {
  const clicked = await clickGenerationEntryByLabels(page, chapterNum, DRAFT_REGENERATION_ENTRY_LABELS, {
    ...options,
    errorCode: 'draft_regeneration_entry_not_found',
    errorMessage: `第 ${chapterNum} 章找不到正文重生入口。`
  })
  return {
    ...clicked,
    generationEntryLabel: clicked.label,
    draftGenerationEntryLabel: clicked.label,
    draftGenerationStartedAt: clicked.clickedAt,
    regenerateEntryLabel: clicked.label,
    regenerateStartedAt: clicked.clickedAt
  }
}

async function clickDraftGenerationEntry(page, chapterNum, options = {}) {
  return clickDraftEntry(page, chapterNum, options)
}

async function collectVisibleDiagnostics(page) {
  const messageText = await page.locator('.n-message, .n-notification, .n-alert').evaluateAll(nodes =>
    nodes.map(node => node.innerText || node.textContent || '').filter(Boolean).slice(-10)
  ).catch(() => [])
  const activeAction = await page.getByText(/正在生成本章|正在生成小纲|正在生成故事块规划|AI 正在处理正文/).allTextContents().catch(() => [])
  return {
    messages: messageText,
    activeAction,
    url: page.url()
  }
}

async function visibleButtonStates(page) {
  const labels = ['本章审稿', '本章审稿（只读）', '定稿', '继续定稿', '仍然定稿', '关闭', '确认']
  const states = {}
  for (const label of labels) {
    const locator = exactButton(page, label).last()
    states[label] = {
      visible: await locator.isVisible().catch(() => false),
      enabled: await locator.isEnabled().catch(() => false)
    }
  }
  return states
}

async function collectDialogAndMessageTexts(page) {
  return page.locator('.n-dialog, .n-modal, .n-message, .n-notification, .app-message-dialog-content')
    .evaluateAll(nodes => nodes.map(node => node.innerText || node.textContent || '').filter(Boolean).slice(-10))
    .catch(() => [])
}

function isBelowHardMinModalText(text = '') {
  return /正文低于硬下限|低于硬下限，请扩写或重新生成/i.test(String(text || ''))
}

async function findBelowHardMinModalText(page) {
  const texts = await collectDialogAndMessageTexts(page)
  return texts.find(isBelowHardMinModalText) || ''
}

function modalCandidateWordCount(text = '') {
  const source = String(text || '')
  const preferred = source.match(/本章约\s*(\d{3,6})\s*字/)
  if (preferred) return Number(preferred[1])
  const fallback = source.match(/(?:正文约|当前约|约)\s*(\d{3,6})\s*字/)
  if (fallback) return Number(fallback[1])
  const any = source.match(/(\d{3,6})\s*字/)
  return any ? Number(any[1]) : 0
}

function summarizeFinalizeVersion(version = null, wordTarget = buildLiveChapterWordTarget()) {
  if (!version) {
    return {
      versionId: '',
      wordCount: 0,
      contentHash: '',
      hardPass: false,
      policy: wordCountPolicy(0, wordTarget)
    }
  }
  const wordCount = versionWordCount(version)
  const policy = wordCountPolicy(wordCount, wordTarget)
  return {
    versionId: String(version.id || ''),
    wordCount,
    contentHash: contentHash(version.content || ''),
    hardPass: Boolean(policy.hardPass),
    policy
  }
}

function buildFinalizeVersionStateDiagnostics({
  selectedVersion = null,
  latestCandidate = null,
  modalText = '',
  wordTarget = buildLiveChapterWordTarget()
} = {}) {
  const selected = summarizeFinalizeVersion(selectedVersion, wordTarget)
  const latest = summarizeFinalizeVersion(latestCandidate, wordTarget)
  const modalWordCount = modalCandidateWordCount(modalText)
  const latestCandidateHardPass = Boolean(latest.versionId && latest.hardPass)
  const selectedVersionStale = Boolean(
    selected.versionId &&
    latest.versionId &&
    selected.versionId !== latest.versionId &&
    latestCandidateHardPass
  )
  const modalStale = Boolean(
    modalText &&
    modalWordCount > 0 &&
    latestCandidateHardPass &&
    modalWordCount < Number(wordTarget?.hardMin || latest.policy?.hardMin || 0) &&
    modalWordCount !== latest.wordCount
  )
  const currentCandidateBelowHardMin = Boolean(selected.versionId && selected.hardPass === false)
  const blockerSource = modalStale
    ? 'stale_modal'
    : (selectedVersionStale ? 'selected_version_stale' : (currentCandidateBelowHardMin ? 'current_candidate' : ''))
  return {
    selectedVersionId: selected.versionId,
    selectedVersionWordCount: selected.wordCount,
    selectedVersionHash: selected.contentHash,
    selectedVersionHardPass: selected.hardPass,
    latestCandidateVersionId: latest.versionId,
    latestCandidateWordCount: latest.wordCount,
    latestCandidateHash: latest.contentHash,
    latestCandidateHardPass,
    modalText,
    modalCandidateWordCount: modalWordCount,
    modalStale,
    selectedVersionStale,
    blockerSource,
    appHardMin: Number(wordTarget?.hardMin || 0),
    liveHardMin: Number(wordTarget?.hardMin || 0),
    wordTarget,
    selectedVersionPolicy: selected.policy,
    latestCandidatePolicy: latest.policy
  }
}

async function selectedVersionIdFromPage(page) {
  return page.locator('[data-current-version="true"][data-version-id]')
    .first()
    .getAttribute('data-version-id')
    .catch(() => '')
}

async function finalizationVersionDiagnostics(page, chapterNum, modalText = '') {
  const chapter = await findChapter(chapterNum).catch(() => null)
  const chapterId = chapter?.id || await currentChapterId(chapterNum).catch(() => '')
  const versions = chapterId
    ? await api(`/projects/${report.project.id}/chapters/${chapterId}/versions`).catch(() => [])
    : []
  const wordTarget = buildLiveChapterWordTarget()
  const latestCandidate = latestHardPassCandidateVersion(versions, wordTarget) || latestCandidateVersion(versions)
  const selectedVersionId = await selectedVersionIdFromPage(page)
  const selectedVersion = (versions || []).find(version => String(version.id || '') === String(selectedVersionId || '')) ||
    latestCandidate ||
    null
  return {
    chapterId,
    versions,
    ...buildFinalizeVersionStateDiagnostics({
      selectedVersion,
      latestCandidate,
      modalText,
      wordTarget
    })
  }
}

async function closeBelowHardMinModal(page) {
  const closeButton = page.locator('.n-dialog, .n-modal, .n-message, .n-notification, .app-message-dialog-content')
    .filter({ hasText: /正文低于硬下限|低于硬下限，请扩写或重新生成/ })
    .last()
    .getByRole('button', { name: /^关闭$|^确定$|^知道了$/ })
    .last()
  if (await closeButton.isVisible().catch(() => false)) {
    await closeButton.click({ timeout: 5000 }).catch(() => {})
  } else {
    await page.keyboard.press('Escape').catch(() => {})
  }
  await page.waitForTimeout(500)
  const remainingText = await findBelowHardMinModalText(page)
  return !remainingText
}

function setLiveBlocker(code, chapterNum, message, diagnostics = {}) {
  report.blocker = {
    blocked: true,
    stage: code === 'selected_version_stale' ? 'finalize_version_selection' : 'word_count_quality_gate',
    code,
    chapterNum,
    message,
    ...diagnostics
  }
  report.acceptance.passed = false
  report.acceptance.reason = message
  writeReport()
}

function throwStaleBelowHardMinModal(chapterNum, diagnostics = {}) {
  const message = `第 ${chapterNum} 章低字数旧弹窗未能关闭，未进入定稿。`
  setLiveBlocker('stale_below_hard_min_modal', chapterNum, message, diagnostics)
  markChapterFlowEvent(chapterNum, 'stale_below_hard_min_modal', diagnostics)
  const error = new Error(`stale_below_hard_min_modal: ${message}`)
  error.code = 'stale_below_hard_min_modal'
  error.liveDiagnostics = diagnostics
  throw error
}

function throwSelectedVersionStale(chapterNum, diagnostics = {}) {
  const message = `第 ${chapterNum} 章最新候选已过硬线，但页面仍选中旧低字数候选。`
  setLiveBlocker('selected_version_stale', chapterNum, message, diagnostics)
  markChapterFlowEvent(chapterNum, 'selected_version_stale', diagnostics)
  const error = new Error(`selected_version_stale: ${message}`)
  error.code = 'selected_version_stale'
  error.liveDiagnostics = diagnostics
  throw error
}

async function dismissStaleBelowHardMinModalIfSafe(page, chapterNum, stage = 'below_hard_min_modal_check', details = {}) {
  const modalText = await findBelowHardMinModalText(page)
  if (!modalText) {
    return { modalPresent: false, modalStale: false, modalText: '' }
  }
  const versionDiagnostics = await finalizationVersionDiagnostics(page, chapterNum, modalText)
  const maskCountBeforeDismiss = await page.locator('.n-modal-mask').count().catch(() => 0)
  const diagnostics = {
    stage,
    ...versionDiagnostics,
    ...details,
    modalText,
    modalStale: versionDiagnostics.modalStale,
    closeBelowHardMinModalAttempted: Boolean(versionDiagnostics.modalStale),
    closeBelowHardMinModalSucceeded: false,
    maskCountBeforeDismiss,
    maskCountAfterDismiss: maskCountBeforeDismiss
  }
  if (!versionDiagnostics.modalStale) {
    return {
      modalPresent: true,
      modalStale: false,
      diagnostics
    }
  }
  const closed = await closeBelowHardMinModal(page)
  const maskCountAfterDismiss = await page.locator('.n-modal-mask').count().catch(() => 0)
  diagnostics.closeBelowHardMinModalSucceeded = closed
  diagnostics.maskCountAfterDismiss = maskCountAfterDismiss
  markChapterFlowEvent(chapterNum, closed ? 'stale_below_hard_min_modal_dismissed' : 'stale_below_hard_min_modal_close_failed', diagnostics)
  if (!closed) throwStaleBelowHardMinModal(chapterNum, diagnostics)
  return {
    modalPresent: true,
    modalStale: true,
    closeBelowHardMinModalSucceeded: true,
    diagnostics
  }
}

async function readPageBusyState(page) {
  const bodyText = await page.locator('body').innerText({ timeout: 5000 }).catch(() => '')
  return {
    auditRunning: /审稿中|正在审稿|一致性审稿/.test(bodyText),
    finalizeSubmitting: /正在定稿|定稿中/.test(bodyText),
    memoryProcessing: /正在提取记忆|正在处理记忆|记忆/.test(bodyText),
    finalizationActionBusy: /正在定稿|定稿中|正在提取|审稿中|正在审稿/.test(bodyText)
  }
}

async function collectPostDraftDiagnostics(page, chapterNum, stage) {
  const chapter = await findChapter(chapterNum).catch(() => null)
  const versions = chapter?.id
    ? await api(`/projects/${report.project.id}/chapters/${chapter.id}/versions`).catch(() => [])
    : []
  const dialogTexts = await collectDialogAndMessageTexts(page)
  const belowHardMinModalText = dialogTexts.find(isBelowHardMinModalText) || ''
  const chapterEntry = report.chapterReports.find(item => Number(item.chapterNum) === Number(chapterNum)) || null
  return {
    stage,
    url: page.url(),
    visibleButtonStates: await visibleButtonStates(page),
    dialogTexts,
    belowHardMinModal: Boolean(belowHardMinModalText),
    modalText: belowHardMinModalText,
    appHardMin: chapterEntry?.wordCountPolicy?.appHardMin || chapterEntry?.wordCountPolicy?.hardMin || null,
    liveHardMin: chapterEntry?.wordCountPolicy?.liveHardMin || chapterEntry?.wordCountPolicy?.hardMin || null,
    wordTarget: chapterEntry?.wordTarget || chapterEntry?.wordCountPolicy?.wordTarget || null,
    candidateWordCount: chapterEntry?.wordCount || chapter?.wordCount || chapter?.word_count || 0,
    regenerateAttempted: Boolean(chapterEntry?.flowEvents?.below_hard_min_auto_regenerate_started),
    regenerateSucceeded: Boolean(chapterEntry?.flowEvents?.below_hard_min_auto_regenerate_succeeded),
    messages: await visibleMessageTexts(page),
    pageState: await readPageBusyState(page),
    chapterStatus: chapter?.status || '',
    finalVersionId: chapter?.finalVersionId || chapter?.final_version_id || null,
    versionCount: Array.isArray(versions) ? versions.length : 0,
    candidateVersionCount: Array.isArray(versions)
      ? versions.filter(version => (version.versionType || version.version_type || version.type) === 'ai_candidate').length
      : 0,
    finalVersionCount: Array.isArray(versions)
      ? versions.filter(version => (version.versionType || version.version_type || version.type) === 'final').length
      : 0,
    ...summarizeAuditTexts(dialogTexts),
    consoleErrors: liveConsoleErrors.slice(-12),
    visible: await collectVisibleDiagnostics(page)
  }
}

async function collectSettingsConfirmationDiagnostics(page, chapterNum, stage) {
  const pendingSettings = await api(`/projects/${report.project.id}/settings/change-events?status=pending_review`).catch(() => [])
  const acceptedSettings = await api(`/projects/${report.project.id}/settings/change-events?status=accepted`).catch(() => [])
  const settingEntities = await api(`/projects/${report.project.id}/settings/entities`).catch(() => [])
  const pendingFacts = ((await api(`/projects/${report.project.id}/canon-facts`).catch(() => [])) || [])
    .filter(fact => fact.status === 'pending_review')
  const classifiedPendingSettings = classifySettingEvents(pendingSettings, settingEntities)
  return {
    ...(await collectPostDraftDiagnostics(page, chapterNum, stage)),
    pendingSettingsCount: Array.isArray(pendingSettings) ? pendingSettings.length : null,
    pendingSettingIds: classifiedPendingSettings.map(item => item.id).filter(Boolean),
    pendingSettings: classifiedPendingSettings,
    acceptedSettingsCount: Array.isArray(acceptedSettings) ? acceptedSettings.length : null,
    pendingCanonFactsCount: pendingFacts.length
  }
}

function classifySettingEvents(events = [], settingEntities = []) {
  return (Array.isArray(events) ? events : []).map(event => {
    const existingEntity = findExistingSettingEntity(event, settingEntities)
    const placeholderEntity = isPlaceholderSettingEntity(existingEntity)
    const risk = classifySettingChangeRisk(event, { existingEntity })
    return {
      id: event.id || '',
      entityName: event.entityName || '',
      changeType: event.changeType || '',
      fieldPath: event.fieldPath || '',
      oldValue: event.oldValue || '',
      newValue: event.newValue || '',
      evidence: event.evidence || '',
      confidence: event.confidence ?? null,
      classification: risk.classification,
      fieldTier: risk.fieldTier || '',
      suggestedRehomeTarget: risk.rehomeTargetField || risk.suggestedRehomeTarget || '',
      conflictWarnings: risk.conflictWarnings || [],
      whyBlocked: risk.whyBlocked || '',
      classificationConflictDiagnostic: settingClassificationConflictDiagnostic(risk),
      existingEntity: existingEntity ? {
        id: existingEntity.id || '',
        entityType: existingEntity.entityType || '',
        name: existingEntity.name || '',
        summary: existingEntity.summary || '',
        category: existingEntity.category || '',
        profile: existingEntity.profile || {},
        tags: existingEntity.tags || []
      } : null,
      placeholderEntity,
      cannotAutoConfirmReason: risk.classification === SETTING_CHANGE_CLASSIFICATIONS.hardConflict
        ? (risk.whyBlocked || (risk.conflictWarnings || []).join('；') || '硬冲突设定需要逐条确认')
        : ''
    }
  })
}

function pendingHardConflictDiagnostics(events = [], settingEntities = []) {
  return classifySettingEvents(events, settingEntities)
    .filter(item => item.classification === SETTING_CHANGE_CLASSIFICATIONS.hardConflict)
    .map(item => ({
      entityName: item.entityName,
      fieldPath: item.fieldPath,
      oldValue: item.oldValue,
      newValue: item.newValue,
      classification: item.classification,
      fieldTier: item.fieldTier,
      suggestedRehomeTarget: item.suggestedRehomeTarget || '',
      whyBlocked: item.whyBlocked || item.conflictWarnings.join('；') || '硬冲突设定需要逐条确认',
      classificationConflictDiagnostic: item.classificationConflictDiagnostic || null
    }))
}

function settingClassificationConflictDiagnostic(risk = {}) {
  const text = [
    risk.whyBlocked,
    ...(Array.isArray(risk.conflictWarnings) ? risk.conflictWarnings : [])
  ].filter(Boolean).join('；')
  if (
    risk.classification === SETTING_CHANGE_CLASSIFICATIONS.hardConflict &&
    /隐藏信息揭示|旧设定细化|身份揭示|背景揭示|线索揭示|reveal_or_refinement/i.test(text)
  ) {
    return {
      code: 'classification_priority_conflict',
      message: '该设定同时包含 reveal/refinement 诊断与 hard_conflict 分类，请检查硬字段结构性风险是否覆盖了揭示优先级。',
      whyBlocked: risk.whyBlocked || '',
      conflictWarnings: risk.conflictWarnings || []
    }
  }
  return null
}

function syncHardConflictBlockerFromFlow(chapterNum, code, error, pending = [], settingEntities = []) {
  const pendingHardConflicts = pendingHardConflictDiagnostics(pending, settingEntities)
  if (code !== 'hard_conflict_setting_review_required' && !pendingHardConflicts.length) return
  report.blocker = {
    blocked: true,
    stage: 'settings_confirmation_failed',
    code: 'hard_conflict_setting_review_required',
    chapterNum,
    message: error?.message || '仍有硬冲突设定需要逐条确认，处理后才能进入下一章。',
    pendingHardConflicts
  }
  report.acceptance.passed = false
  report.acceptance.reason = report.blocker.message
}

function splitSettingEventsByRisk(events = [], settingEntities = []) {
  const classified = classifySettingEvents(sortSettingEventsForConfirmation(events), settingEntities)
  return {
    classified,
    hardConflicts: classified.filter(item => item.classification === SETTING_CHANGE_CLASSIFICATIONS.hardConflict),
    batchAcceptable: classified.filter(item => item.classification !== SETTING_CHANGE_CLASSIFICATIONS.hardConflict)
  }
}

function detectUnconfirmedAutoAcceptableRelationshipSettings(events = [], settingEntities = []) {
  const split = splitSettingEventsByRisk(events, settingEntities)
  if (split.hardConflicts.length) return null
  const stuck = split.batchAcceptable.filter(item => {
    const changeType = String(item.changeType || item.change_type || '').trim()
    const pendingHardConflicts = Array.isArray(item.pendingHardConflicts) ? item.pendingHardConflicts : []
    return changeType === 'relationship' &&
      pendingHardConflicts.length === 0 &&
      isBatchAcceptableSettingChange(item)
  })
  if (!stuck.length) return null
  return {
    code: 'relationship_auto_confirm_failed',
    message: '低风险关系设定未能自动确认，请检查关系归位或批量确认流程。',
    pendingSettingIds: stuck.map(item => item.id).filter(Boolean),
    pendingSettings: stuck
  }
}

function sortSettingEventsForConfirmation(events = []) {
  return sortSettingEventsByConfirmationOrder(events)
}

function findExistingSettingEntity(event = {}, settingEntities = []) {
  if (!Array.isArray(settingEntities)) return null
  if (event.entityId) {
    const byId = settingEntities.find(entity => entity.id === event.entityId)
    if (byId) return byId
  }
  const name = String(event.entityName || '').trim()
  const type = String(event.entityType || '').trim()
  if (!name) return null
  return settingEntities.find(entity =>
    entity.name === name && (!type || entity.entityType === type)
  ) || null
}

function summarizeAuditTexts(texts = []) {
  const text = Array.isArray(texts) ? texts.join('\n') : String(texts || '')
  const issueMatches = [...text.matchAll(/发现\s*(\d+)\s*个问题/g)]
  const issueCount = issueMatches.length ? Math.max(...issueMatches.map(match => Number(match[1]) || 0)) : 0
  const hardIssueCount = Math.max(
    (text.match(/严重|主要|critical|major/gi) || []).length,
    text.includes('严重/主要') ? 1 : 0
  )
  const softIssueCount = (text.match(/轻微|建议|minor|suggestion/gi) || []).length
  return {
    audit_issue_count: issueCount,
    hard_issue_count: hardIssueCount,
    soft_issue_count: softIssueCount
  }
}

async function collectAuditModalSummary(page) {
  const texts = await page.locator('.audit-report-modal, .n-modal, .n-dialog')
    .evaluateAll(nodes => nodes.map(node => node.innerText || node.textContent || '').filter(Boolean))
    .catch(() => [])
  const summary = summarizeAuditTexts(texts)
  return {
    audit_modal_visible: texts.length > 0,
    ...summary
  }
}

async function collectFinalizationDiagnostics(page, chapterNum) {
  const chapter = await findChapter(chapterNum).catch(() => null)
  let versions = []
  if (chapter?.id) {
    versions = await api(`/projects/${report.project.id}/chapters/${chapter.id}/versions`).catch(() => [])
  }
  const finalVersion = Array.isArray(versions)
    ? versions.find(version => version.id === (chapter?.finalVersionId || chapter?.final_version_id)) ||
      versions.find(version => (version.versionType || version.version_type || version.type) === 'final') ||
      null
    : null
  const pendingSettings = await api(`/projects/${report.project.id}/settings/change-events?status=pending_review`).catch(() => [])
  const pendingFacts = ((await api(`/projects/${report.project.id}/canon-facts`).catch(() => [])) || [])
    .filter(fact => fact.status === 'pending_review')
  const blocks = await api(`/projects/${report.project.id}/story-blocks`).catch(() => [])
  const storyBlockReviewCount = (blocks || []).reduce((sum, block) => {
    const history = Array.isArray(block.reviewHistory || block.review_history) ? (block.reviewHistory || block.review_history) : []
    return sum + history.filter(review => Number(review.chapterNum || review.chapter_num) === Number(chapterNum)).length
  }, 0)
  const marker = await readFinalizationMarker(page, chapterNum)
  const visibleDiagnostics = await collectVisibleDiagnostics(page)
  const finalizeApiEvents = liveNetworkEvents.filter(event => {
    const path = event.path || apiPathFromUrl(event.url || '')
    return chapter?.id && path.includes(`/chapters/${chapter.id}/versions/`) && path.includes('/finalize')
  }).slice(-10)
  const recentAiProxy = (report.aiProxy.realRequestStages || []).slice(-10)
  const finalizeButton = exactButton(page, '定稿').last()
  const continueFinalizeButton = exactButton(page, '继续定稿').last()
  const stillFinalizeButton = exactButton(page, '仍然定稿').last()
  const buttonState = async locator => ({
    visible: await locator.isVisible().catch(() => false),
    enabled: await locator.isEnabled().catch(() => false)
  })
  const dialogTexts = await page.locator('.n-dialog, .n-modal, .n-message, .n-notification, .app-message-dialog-content')
    .evaluateAll(nodes => nodes.map(node => node.innerText || node.textContent || '').filter(Boolean).slice(-12))
    .catch(() => [])
  const auditSummary = summarizeAuditTexts(dialogTexts)
  const belowHardMinModalText = dialogTexts.find(isBelowHardMinModalText) || ''
  const chapterEntry = report.chapterReports.find(item => Number(item.chapterNum) === Number(chapterNum)) || null
  const versionDiagnostics = await finalizationVersionDiagnostics(page, chapterNum, belowHardMinModalText).catch(() => null)
  return {
    stage: `chapter_${chapterNum}_finalization`,
    url: page.url(),
    chapterStatus: chapter?.status || '',
    finalVersionId: chapter?.finalVersionId || chapter?.final_version_id || null,
    finalVersionType: finalVersion?.versionType || finalVersion?.version_type || finalVersion?.type || '',
    wordCount: chapter?.wordCount || chapter?.word_count || 0,
    belowHardMinModal: Boolean(belowHardMinModalText),
    modalText: belowHardMinModalText,
    ...(versionDiagnostics || {}),
    appHardMin: chapterEntry?.wordCountPolicy?.appHardMin || chapterEntry?.wordCountPolicy?.hardMin || null,
    liveHardMin: chapterEntry?.wordCountPolicy?.liveHardMin || chapterEntry?.wordCountPolicy?.hardMin || null,
    wordTarget: chapterEntry?.wordTarget || chapterEntry?.wordCountPolicy?.wordTarget || null,
    candidateWordCount: chapterEntry?.wordCount || chapter?.wordCount || chapter?.word_count || 0,
    regenerateAttempted: Boolean(chapterEntry?.flowEvents?.below_hard_min_auto_regenerate_started),
    regenerateSucceeded: Boolean(chapterEntry?.flowEvents?.below_hard_min_auto_regenerate_succeeded),
    versionCount: Array.isArray(versions) ? versions.length : 0,
    candidateVersionCount: Array.isArray(versions)
      ? versions.filter(version => (version.versionType || version.version_type || version.type) === 'ai_candidate').length
      : 0,
    finalVersionCount: Array.isArray(versions)
      ? versions.filter(version => (version.versionType || version.version_type || version.type) === 'final').length
      : 0,
    pendingSettingsCount: Array.isArray(pendingSettings) ? pendingSettings.length : 0,
    pendingFactsCount: pendingFacts.length,
    storyBlockReviewCount,
    markerPresent: Boolean(marker),
    marker,
    postFinalizeFailed: Boolean(marker?.retryablePostprocessFailure || marker?.storyBlockSettlementFailure || marker?.postFinalizeFailed),
    activeAction: visibleDiagnostics.activeAction || [],
    loading: visibleDiagnostics.activeAction || [],
    finalizeApiEvents,
    recentAiProxy,
    finalizeButton: await buttonState(finalizeButton),
    continueFinalizeButton: await buttonState(continueFinalizeButton),
    stillFinalizeButton: await buttonState(stillFinalizeButton),
    ...auditSummary,
    maskCount: await page.locator('.n-modal-mask').count().catch(() => 0),
    dialogTexts,
    consoleErrors: liveConsoleErrors.slice(-12),
    visible: visibleDiagnostics
  }
}

async function collectStoryBlockReviewDiagnostics(page, chapterNum) {
  const chapter = await findChapter(chapterNum).catch(() => null)
  const beat = await api(`/projects/${report.project.id}/chapter-beat-plan/${chapterNum}`).catch(() => null)
  const blocks = await api(`/projects/${report.project.id}/story-blocks`).catch(() => [])
  const block = (blocks || []).find(item => item.id === (beat?.storyBlockId || chapter?.storyBlockId)) || null
  const versions = chapter?.id
    ? await api(`/projects/${report.project.id}/chapters/${chapter.id}/versions`).catch(() => [])
    : []
  const pendingSettings = await api(`/projects/${report.project.id}/settings/change-events?status=pending_review`).catch(() => [])
  const pendingFacts = ((await api(`/projects/${report.project.id}/canon-facts`).catch(() => [])) || [])
    .filter(fact => fact.status === 'pending_review')
  const localStorageMarkers = await page.evaluate(() => {
    const items = []
    for (let i = 0; i < window.localStorage.length; i += 1) {
      const key = window.localStorage.key(i)
      if (/finalization|story.?block|pending/i.test(key || '')) {
        items.push({ key, value: window.localStorage.getItem(key)?.slice(0, 800) || '' })
      }
    }
    return items
  }).catch(() => [])
  return {
    stage: `chapter_${chapterNum}_story_block_review`,
    url: page.url(),
    chapterStatus: chapter?.status || '',
    finalVersionId: chapter?.finalVersionId || chapter?.final_version_id || null,
    wordCount: chapter?.wordCount || chapter?.word_count || 0,
    versionCount: Array.isArray(versions) ? versions.length : 0,
    finalVersionCount: Array.isArray(versions)
      ? versions.filter(version => (version.versionType || version.version_type) === 'final').length
      : 0,
    beat: beat ? {
      storyBlockId: beat.storyBlockId || beat.story_block_id || '',
      blockStageId: beat.blockStageId || beat.block_stage_id || '',
      snapshotStageId: beat.blockStageSnapshot?.stageId || beat.block_stage_snapshot?.stageId || ''
    } : null,
    block: block ? {
      id: block.id,
      status: block.status,
      reviewHistory: block.reviewHistory || block.review_history || [],
      completedStages: block.completedStages || block.completed_stages || [],
      stagePlan: (block.stagePlan || block.stage_plan || []).map(stage => ({
        id: stage.id,
        status: stage.status,
        chapterRefs: stage.chapterRefs || stage.chapter_refs || [],
        completedChapterNum: stage.completedChapterNum || stage.completed_chapter_num || null
      }))
    } : null,
    pendingSettingsCount: Array.isArray(pendingSettings) ? pendingSettings.length : 0,
    pendingCanonFactsCount: pendingFacts.length,
    localStorageMarkers,
    consoleErrors: liveConsoleErrors.slice(-12),
    visible: await collectVisibleDiagnostics(page)
  }
}

async function clickFinalizeContinuationIfPrompted(page, timeout = 5000) {
  const dialogTexts = await collectDialogAndMessageTexts(page)
  if (dialogTexts.some(text => /定稿前审稿发现|确认仍然定稿|请先修订/.test(text))) {
    const closeButton = page.getByRole('button', { name: /^关闭$/ }).last()
    if (await closeButton.isVisible().catch(() => false)) {
      await closeButton.click({ timeout }).catch(() => {})
      await page.waitForTimeout(300)
    }
  }
  for (const label of ['继续定稿', '仍然定稿']) {
    const locator = exactButton(page, label).last()
    if (!await locator.isVisible().catch(() => false)) continue
    const enabled = await waitFor(`finalize continuation ${label} enabled`, async () => locator.isEnabled(), timeout, 500)
      .catch(() => false)
    if (!enabled) continue
    await locator.click({ timeout })
    return label
  }
  return ''
}

async function dismissAppDialogs(page) {
  for (let i = 0; i < 10; i += 1) {
    const maskVisible = await page.locator('.n-modal-mask').last().isVisible().catch(() => false)
    const dialog = page.locator('.n-dialog, .n-modal-container, .n-modal').last()
    const dialogVisible = await dialog.isVisible().catch(() => false)
    if (!maskVisible && !dialogVisible) break
    const scope = dialogVisible ? dialog : page.locator('body')
    const button = scope.getByRole('button', { name: /确认|确定|知道了|关闭|OK/i }).last()
    const closeIcon = scope.locator('.n-base-close, .n-dialog__close, .n-modal-close').last()
    if (await button.isVisible().catch(() => false)) {
      await button.click().catch(() => {})
    } else if (await closeIcon.isVisible().catch(() => false)) {
      await closeIcon.click().catch(() => {})
    } else {
      await page.keyboard.press('Escape').catch(() => {})
    }
    await page.locator('.n-modal-mask').last().waitFor({ state: 'hidden', timeout: 5000 }).catch(() => {})
    await page.waitForTimeout(300).catch(() => {})
  }
}

async function readSettingInitializationProgress(page) {
  return page.evaluate(() => {
    const entries = Object.entries(window.localStorage || {})
    const item = entries.find(([key]) => key.includes('setting-bible-initialization'))
    return item ? JSON.parse(item[1]) : null
  }).catch(() => null)
}

async function readVolumePlanningDiagnostics(page) {
  return page.evaluate(projectId => {
    try {
      const raw = window.localStorage?.getItem(`volume-plan-diagnostics:${projectId}`)
      return raw ? JSON.parse(raw) : null
    } catch {
      return null
    }
  }, report.project.id).catch(() => null)
}

async function readBeatPlanDiagnostics(page, chapterNum) {
  return page.evaluate(({ projectId, chapterNum }) => {
    try {
      const raw = window.localStorage?.getItem(`beat-plan-diagnostics:${projectId}:${chapterNum}`)
      return raw ? JSON.parse(raw) : null
    } catch {
      return null
    }
  }, { projectId: report.project.id, chapterNum }).catch(() => null)
}

async function readWriterHumanityContextDiagnostics(page, chapterNum) {
  return page.evaluate(({ chapterNum }) => {
    try {
      const diagnostics = window.__LONGFORM_WRITER_CONTEXT_DIAGNOSTICS__ || null
      if (!diagnostics || Number(diagnostics.chapterNum || 0) !== Number(chapterNum)) return null
      return diagnostics
    } catch {
      return null
    }
  }, { chapterNum }).catch(() => null)
}

function summarizeBeatPlanPromptDiagnostics(diagnostics = null) {
  if (!diagnostics) {
    return {
      beatPlanPromptDiagnostics: null
    }
  }
  const attempts = Array.isArray(diagnostics.attempts) ? diagnostics.attempts : []
  const attempt1 = attempts.find(item => Number(item.attempt) === 1) || null
  const attempt2 = attempts.find(item => Number(item.attempt) === 2) || null
  const latestAttempt = attempt2 || attempt1 || null
  return {
    beatPlanPromptDiagnostics: diagnostics,
    beatPlanSource: diagnostics.beatPlanSource || '',
    aiAttempts: attempts.length,
    derivedFromStoryBlock: diagnostics.beatPlanSource === 'derived_from_story_block' || Boolean(diagnostics.derivedFromStoryBlock),
    derivedReason: diagnostics.derivedReason || '',
    stageSnapshotFields: diagnostics.stageSnapshotFields || null,
    whetherAllowedToContinue: diagnostics.beatPlanSource === 'derived_from_story_block'
      ? true
      : (diagnostics.whetherAllowedToContinue ?? null),
    promptChars: diagnostics.promptChars ?? diagnostics.promptDiagnostics?.promptChars ?? null,
    promptTokensApprox: diagnostics.promptTokensApprox ?? diagnostics.promptDiagnostics?.promptTokensApprox ?? null,
    rawHead: latestAttempt?.rawHead || '',
    rawTail: latestAttempt?.rawTail || '',
    cleanedLength: latestAttempt?.cleanedLength ?? null,
    attempt1,
    attempt2,
    injectedStoryBlockId: diagnostics.storyBlockId || diagnostics.promptDiagnostics?.storyBlockId || '',
    injectedBlockStageId: diagnostics.blockStageId || diagnostics.promptDiagnostics?.blockStageId || '',
    activeStoryBlockExists: diagnostics.activeStoryBlockExists ?? diagnostics.promptDiagnostics?.activeStoryBlockExists ?? null,
    activeStoryBlockStageCount: diagnostics.activeStoryBlockStageCount ?? diagnostics.promptDiagnostics?.activeStoryBlockStageCount ?? null,
    activeStoryBlockNextStage: diagnostics.activeStoryBlockNextStage || diagnostics.promptDiagnostics?.activeStoryBlockNextStage || '',
    oversizedInputs: diagnostics.oversizedInputs || diagnostics.promptDiagnostics?.oversizedInputs || null,
    retryPromptDiagnostics: diagnostics.retryPromptDiagnostics || null,
    candidateRaw: diagnostics.candidateRaw || '',
    parsedCandidate: diagnostics.parsedCandidate || null,
    qualityGateInput: diagnostics.qualityGateInput || '',
    qualityGateResult: diagnostics.qualityGateResult || null,
    candidateFailureCode: diagnostics.candidateFailureCode || diagnostics.beatPlanQualityDiagnostics?.failureCode || '',
    parseRetryTriggered: Boolean(diagnostics.parseRetryTriggered),
    parseRetrySucceeded: Boolean(diagnostics.parseRetrySucceeded),
    repairTriggered: Boolean(diagnostics.repairTriggered),
    repairSucceeded: Boolean(diagnostics.repairSucceeded),
    derivedFallbackTriggered: Boolean(diagnostics.derivedFallbackTriggered),
    derivedFallbackSucceeded: Boolean(diagnostics.derivedFallbackSucceeded),
    finalFailureAfterRecovery: Boolean(diagnostics.finalFailureAfterRecovery),
    failureStage: diagnostics.failureStage || '',
    localSafetyDraftGenerated: Boolean(diagnostics.localSafetyDraftGenerated),
    localSafetyDraftLength: diagnostics.localSafetyDraftLength || 0
  }
}

async function visibleMessageTexts(page) {
  return page.locator('.n-message, .n-notification, .n-alert, .app-message-dialog-content')
    .evaluateAll(nodes => nodes.map(node => node.innerText || node.textContent || '').filter(Boolean))
    .catch(() => [])
}

function latestAiProxyTimingSince(startedAtMs = 0) {
  const stages = (report.aiProxy.realRequestStages || []).filter(stage => {
    const at = Date.parse(stage.at || '')
    return Number.isFinite(at) && at >= startedAtMs && /\/api\/ai\/chat-completions/.test(stage.url || '')
  })
  const requests = stages.filter(stage => stage.kind === 'request')
  const responses = stages.filter(stage => stage.kind === 'response')
  const streamRequests = requests.filter(stage => /\/stream$/.test(stage.url || ''))
  const streamResponses = responses.filter(stage => /\/stream$/.test(stage.url || ''))
  return {
    lastAiProxyRequestAt: requests.at(-1)?.at || '',
    lastAiProxyResponseAt: responses.at(-1)?.at || '',
    streamStarted: streamRequests.length > 0,
    streamEnded: streamResponses.length > 0,
    streamRequestCount: streamRequests.length,
    streamResponseCount: streamResponses.length
  }
}

function contentHash(value = '') {
  return createHash('sha1').update(String(value || '')).digest('hex').slice(0, 16)
}

function versionTimestampMs(version = {}) {
  const values = [
    version.updatedAt,
    version.updated_at,
    version.createdAt,
    version.created_at
  ]
  for (const value of values) {
    if (typeof value === 'number' && Number.isFinite(value)) return value
    if (typeof value === 'string' && /^\d{10,}$/.test(value.trim())) return Number(value.trim())
    const parsed = Date.parse(value || '')
    if (Number.isFinite(parsed)) return parsed
  }
  return 0
}

function versionFingerprint(version = {}) {
  const content = String(version?.content || '')
  return {
    id: String(version?.id || ''),
    contentHash: contentHash(content),
    contentLength: content.length,
    wordCount: Number(version?.wordCount || version?.word_count || content.length || 0),
    createdAt: version?.createdAt || version?.created_at || '',
    updatedAt: version?.updatedAt || version?.updated_at || '',
    timestampMs: versionTimestampMs(version)
  }
}

function candidateVersionFingerprints(versions = []) {
  return (Array.isArray(versions) ? versions : [])
    .filter(version => String(version?.content || '').length > 500)
    .map(versionFingerprint)
}

function summarizeVersionFingerprint(fingerprint = null) {
  if (!fingerprint) return null
  return {
    id: fingerprint.id,
    contentHash: fingerprint.contentHash,
    contentLength: fingerprint.contentLength,
    wordCount: fingerprint.wordCount,
    createdAt: fingerprint.createdAt,
    updatedAt: fingerprint.updatedAt
  }
}

function latestCandidateFingerprint(versions = []) {
  const fingerprints = candidateVersionFingerprints(versions)
  return fingerprints
    .slice()
    .sort((a, b) => (b.timestampMs || 0) - (a.timestampMs || 0))
    .at(0) || null
}

function latestCandidateVersion(versions = []) {
  return (Array.isArray(versions) ? versions : [])
    .filter(version => String(version?.content || '').length > 500)
    .slice()
    .sort((a, b) => (versionTimestampMs(b) || 0) - (versionTimestampMs(a) || 0))
    .at(0) || null
}

function versionWordCount(version = {}) {
  const content = String(version?.content || '')
  return Number(version?.wordCount || version?.word_count || content.length || 0)
}

function latestHardPassCandidateVersion(versions = [], wordTarget = buildLiveChapterWordTarget()) {
  return (Array.isArray(versions) ? versions : [])
    .filter(version => String(version?.content || '').length > 500)
    .filter(version => wordCountPolicy(versionWordCount(version), wordTarget).hardPass)
    .slice()
    .sort((a, b) => (versionTimestampMs(b) || 0) - (versionTimestampMs(a) || 0))
    .at(0) || null
}

const SHORT_DRAFT_EXPANSION_MIN = 2500
const SHORT_DRAFT_EXPANSION_MAX = 3999
const SHORT_DRAFT_EXPANSION_TARGET = '4500-5200'
const SHORT_DRAFT_TOP_UP_MIN = 3500
const SHORT_DRAFT_TOP_UP_MAX = 3999
const SHORT_DRAFT_TOP_UP_TARGET = '300-900'
const SHORT_DRAFT_REQUIRED_BEAT_SECTIONS = [
  '本章事件',
  '人物目标',
  '核心冲突',
  '外部压力',
  '代价或损失',
  '不可逆变化',
  '结尾交接',
  '主角即时欲望',
  '情绪锚点',
  '误解或恐惧',
  '关系轻微变化',
  '给读者的阶段答案'
]

const SHORT_DRAFT_FACT_GROUPS = [
  { label: 'protagonist', terms: ['陆沉舟'] },
  { label: 'xiaojiu', terms: ['小九'] },
  { label: 'father_thread', terms: ['父亲', '陆沉舟之父'] },
  { label: 'star_account_or_debt', terms: ['星账', '星债'] },
  { label: 'injury_cost', terms: ['左肩', '肩伤', '伤口'] },
  { label: 'secret_room', terms: ['密室', '庚七密室', '庚七'] },
  { label: 'escape_route', terms: ['排水渠', '排水道', '暗渠', '地道', '密道', '秘密通道'] },
  { label: 'inn', terms: ['平安客栈', '客栈'] },
  { label: 'tree_or_back_alley', terms: ['槐树', '后巷'] },
  { label: 'key_or_copper', terms: ['钥匙', '旧铜钥匙', '铜钥匙'] },
  { label: 'token_or_badge', terms: ['令牌', '玉牌', '暗哨令牌'] },
  { label: 'toothpick_man', terms: ['剔牙男人'] },
  { label: 'fingerless_man', terms: ['缺指男人'] },
  { label: 'patrol_office', terms: ['巡天司'] },
  { label: 'zhao_geng', terms: ['赵庚'] },
  { label: 'ma_san', terms: ['马三'] }
]

const SHORT_DRAFT_ENDING_GROUPS = [
  { label: 'star_account_or_debt', terms: ['星账', '星债', '玉牌', '令牌'] },
  { label: 'inn_or_back_alley', terms: ['平安客栈', '客栈', '后巷'] },
  { label: 'tree_or_key', terms: ['槐树', '钥匙', '旧铜钥匙', '铜钥匙'] },
  { label: 'toothpick_or_hidden_affiliation', terms: ['剔牙男人', '暗哨', '巡天司'] },
  { label: 'next_pressure', terms: ['三日', '茶楼', '缺指男人'] }
]

function isCompleteBeatPlanForShortDraftExpansion(beatPlanRecord = null) {
  const content = typeof beatPlanRecord === 'string'
    ? beatPlanRecord
    : String(beatPlanRecord?.content || '')
  const missingSections = SHORT_DRAFT_REQUIRED_BEAT_SECTIONS.filter(label => !content.includes(label))
  return {
    complete: content.trim().length >= 300 && missingSections.length === 0,
    contentLength: content.length,
    missingSections
  }
}

function compactPromptText(text = '', maxLength = 9000) {
  const value = String(text || '').trim()
  if (value.length <= maxLength) return value
  const head = value.slice(0, Math.floor(maxLength * 0.55))
  const tail = value.slice(-Math.floor(maxLength * 0.4))
  return `${head}\n\n[中间内容略去，扩写时不得改变已给短稿的事实顺序]\n\n${tail}`
}

function groupPresentInText(group, text = '') {
  const source = String(text || '')
  return (group.terms || []).some(term => source.includes(term))
}

function buildShortDraftFactDriftCheck({ beatPlanContent = '', originalContent = '', expandedContent = '' } = {}) {
  const source = `${beatPlanContent}\n${originalContent}`
  const requiredGroups = SHORT_DRAFT_FACT_GROUPS
    .filter(group => groupPresentInText(group, source))
    .map(group => ({
      label: group.label,
      terms: group.terms
    }))
  const missingGroups = requiredGroups.filter(group => !groupPresentInText(group, expandedContent))
  return {
    passed: missingGroups.length === 0,
    requiredGroups: requiredGroups.map(group => group.label),
    missingGroups: missingGroups.map(group => group.label)
  }
}

function checkShortDraftEndingPreserved(originalContent = '', expandedContent = '') {
  const originalEnding = String(originalContent || '').slice(-900)
  const expandedEnding = String(expandedContent || '').slice(-1200)
  const requiredGroups = SHORT_DRAFT_ENDING_GROUPS
    .filter(group => groupPresentInText(group, originalEnding))
    .map(group => ({
      label: group.label,
      terms: group.terms
    }))
  const missingGroups = requiredGroups.filter(group => !groupPresentInText(group, expandedEnding))
  return {
    passed: requiredGroups.length === 0 || missingGroups.length === 0,
    requiredGroups: requiredGroups.map(group => group.label),
    missingGroups: missingGroups.map(group => group.label)
  }
}

function buildShortDraftEndingGuard(originalContent = '') {
  const endingExcerpt = String(originalContent || '').slice(-900).trim()
  const requiredGroups = SHORT_DRAFT_ENDING_GROUPS
    .filter(group => groupPresentInText(group, endingExcerpt))
    .map(group => ({
      label: group.label,
      terms: group.terms
    }))
  const requiredSignals = requiredGroups
    .map(group => `${group.label}: ${group.terms.join(' / ')}`)
    .join('\n')
  return {
    endingExcerpt,
    requiredSignals: requiredSignals || '无额外结尾信号，但仍必须保留原短稿最后一个情节落点。'
  }
}

function collectDraftTemplateWordingHits(text = '') {
  const source = String(text || '')
  const patterns = [
    /stage-\d+/ig,
    /stage-x/ig,
    /第\s*\d+\s*章发生一件读者能复述的事/g,
    /本章关系变化落在/g,
    /不能只把配角当线索出口/g,
    /主角要完成[^。\n]{0,60}并把结果接到/g
  ]
  return patterns
    .flatMap(pattern => source.match(pattern) || [])
    .slice(0, 8)
}

function buildShortDraftExpansionMessages({
  chapterNum,
  beatPlanRecord,
  originalContent,
  stageSnapshot
} = {}) {
  const beatPlanContent = String(beatPlanRecord?.content || '')
  const stageText = stageSnapshot ? JSON.stringify(stageSnapshot, null, 2) : ''
  const endingGuard = buildShortDraftEndingGuard(originalContent)
  return [
    {
      role: 'system',
      content: '你负责把低字数章节短稿扩写成同一章正文。只输出小说正文，不输出说明。'
    },
    {
      role: 'user',
      content: [
        `请把第 ${chapterNum} 章短稿扩写到 ${SHORT_DRAFT_EXPANSION_TARGET} 字。`,
        '',
        '要求：',
        '1. 保留原剧情事实、事件顺序、人物选择和结尾落点。',
        '2. 只补足场景行动、人物对话、代价后果、环境阻力、关系反应。',
        '3. 不新增大反转，不提前消耗后续故事块，不改变最后一个情节落点。',
        '4. 用通俗清楚的叙事写正文，不要写分析、清单或小纲字段。',
        '',
        '## 本章小纲',
        compactPromptText(beatPlanContent, 2600),
        '',
        '## 当前故事块 stage snapshot',
        compactPromptText(stageText, 1200),
        '',
        '## 必须保留的结尾交接',
        compactPromptText(endingGuard.endingExcerpt, 1200),
        '',
        '## 结尾必须继续包含的事实信号',
        endingGuard.requiredSignals,
        '',
        '## 原短稿',
        compactPromptText(originalContent, 9000)
      ].join('\n')
    }
  ]
}

function buildShortDraftTopUpMessages({
  chapterNum,
  beatPlanRecord,
  originalContent,
  firstExpandedContent,
  stageSnapshot
} = {}) {
  const beatPlanContent = String(beatPlanRecord?.content || '')
  const stageText = stageSnapshot ? JSON.stringify(stageSnapshot, null, 2) : ''
  const endingGuard = buildShortDraftEndingGuard(originalContent)
  return [
    {
      role: 'system',
      content: '你负责把已经保住事实和结尾、但仍偏短的章节扩写稿做二段补足。只输出补足后的完整小说正文，不输出说明。'
    },
    {
      role: 'user',
      content: [
        `请对第 ${chapterNum} 章扩写稿做二段补足，最终正文控制在 ${SHORT_DRAFT_EXPANSION_TARGET} 字，最低不少于 4000 字。`,
        `本次只补 ${SHORT_DRAFT_TOP_UP_TARGET} 字左右。`,
        '',
        '补足要求：',
        '1. 不改原剧情事实、事件顺序、人物选择和结尾交接。',
        '2. 不新增关键线索，不替换人物选择，不提前消耗后续故事块。',
        '3. 只在动作细节、人物反应、对话缝隙、场景停留、后果反馈处补足。',
        '4. 输出完整正文，不要写分析、清单、标题、JSON 或小纲字段。',
        '',
        '## 本章小纲',
        compactPromptText(beatPlanContent, 2200),
        '',
        '## 当前故事块 stage snapshot',
        compactPromptText(stageText, 1000),
        '',
        '## 必须保留的结尾交接',
        compactPromptText(endingGuard.endingExcerpt, 1200),
        '',
        '## 结尾必须继续包含的事实信号',
        endingGuard.requiredSignals,
        '',
        '## 原短稿事实基底',
        compactPromptText(originalContent, 4200),
        '',
        '## 第一次扩写稿',
        compactPromptText(firstExpandedContent, 11000)
      ].join('\n')
    }
  ]
}

function shouldTopUpShortDraftExpansion({
  expandedWordCount = 0,
  factDriftCheck = null,
  endingPreserved = null,
  templateWordingHits = []
} = {}) {
  return expandedWordCount >= SHORT_DRAFT_TOP_UP_MIN &&
    expandedWordCount <= SHORT_DRAFT_TOP_UP_MAX &&
    factDriftCheck.passed &&
    endingPreserved.passed &&
    templateWordingHits.length === 0
}

function extractChatCompletionContent(result = null) {
  if (typeof result === 'string') return result
  if (result?.content) return result.content
  return result?.choices?.[0]?.message?.content || result?.choices?.[0]?.text || ''
}

async function resolveWritingProviderForRunner() {
  let provider = report.modelBinding.taskProviders?.writing || null
  if (!provider?.id) {
    const resolved = await resolveTaskProvidersForReport(report.project.id)
    report.modelBinding.status = resolved.status
    report.modelBinding.taskProviders = resolved.taskProviders
    report.modelBinding.inheritedProviderMatched = resolved.inheritedProviderMatched
    report.modelBinding.actualProviderModelMatched = resolved.actualProviderModelMatched
    report.modelBinding.usedDeepseekV4ProFallback = resolved.usedDeepseekV4ProFallback
    updateAiProxyProviderFromBinding(resolved.taskProviders)
    provider = resolved.taskProviders?.writing || null
  }
  if (!provider?.id) {
    throw new Error('短稿扩写无法解析 writing 模型供应商。')
  }
  return provider
}

async function runnerChatCompletion(messages, {
  taskName = 'expand_short_draft',
  maxTokens = 9000,
  temperature = 0.46
} = {}) {
  const provider = await resolveWritingProviderForRunner()
  const url = `${API_BASE}/ai/chat-completions`
  const payload = {
    providerId: provider.id,
    projectId: report.project.id,
    model: provider.model || null,
    taskName,
    messages,
    maxTokens,
    temperature,
    stream: false,
    includeUsage: true
  }
  report.aiProxy.aiProxyUsed = true
  report.aiProxy.backendAiRequests += 1
  pushAiProxyStage({ kind: 'request', url, method: 'POST', taskName })
  const startedMs = Date.now()
  const response = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  })
  const text = await response.text()
  pushAiProxyStage({
    kind: 'response',
    url,
    status: response.status,
    taskName,
    elapsedMs: Date.now() - startedMs
  })
  if (!response.ok) {
    throw new Error(`AI proxy ${response.status}: ${text.slice(0, 500)}`)
  }
  return text ? JSON.parse(text) : null
}

async function topUpShortDraftExpansion({
  chapterNum,
  beatPlanRecord,
  originalContent,
  firstExpandedContent
} = {}) {
  const messages = buildShortDraftTopUpMessages({
    chapterNum,
    beatPlanRecord,
    originalContent,
    firstExpandedContent,
    stageSnapshot: beatPlanRecord?.blockStageSnapshot || null
  })
  const result = await runnerChatCompletion(messages, {
    taskName: 'top_up_expand_short_draft',
    maxTokens: 10000,
    temperature: 0.42
  })
  const rawContent = extractChatCompletionContent(result)
  return cleanGeneratedChapterText(rawContent)
}

async function saveExpandedDraftVersion(chapterId, chapterNum, content, provider, {
  title = `第 ${chapterNum} 章 - 短稿扩写候选`,
  promptBrief = `expand_short_draft: 保留短稿事实和结尾扩写至 ${SHORT_DRAFT_EXPANSION_TARGET}`
} = {}) {
  return api(`/projects/${report.project.id}/chapters/${chapterId}/versions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      title,
      content,
      versionType: 'ai_candidate',
      sourceModelId: provider?.id || null,
      promptBrief
    })
  })
}

async function refreshWriterPageForSavedVersion(page, chapterNum) {
  const writerEnteredAtMs = Date.now()
  await page.goto(`${FRONTEND}/writer/${report.project.id}/${chapterNum}`, { waitUntil: 'domcontentloaded' })
  await page.getByText(`第 ${chapterNum} 章`).first().waitFor({ state: 'visible', timeout: 60000 })
  const writerContextDiagnostics = await waitForWriterContextReady(page, chapterNum, {
    timeoutMs: 180000,
    writerEnteredAtMs
  }).catch(error => ({ error: error.message }))
  markChapterFlowEvent(chapterNum, 'writer_page_refreshed_after_short_draft_expansion', {
    contextReadyByEnabledEntry: Boolean(writerContextDiagnostics.contextReadyByEnabledEntry),
    enabledDraftEntryLabels: writerContextDiagnostics.enabledDraftEntryLabels || [],
    disabledDraftEntryLabels: writerContextDiagnostics.disabledDraftEntryLabels || [],
    contextApiFailures: writerContextDiagnostics.contextApiFailures || [],
    error: writerContextDiagnostics.error || ''
  })
}

async function expandShortDraftCandidate({
  page,
  chapterNum,
  chapterId,
  originalCandidate,
  beatPlanRecord,
  wordTarget
} = {}) {
  const provider = await resolveWritingProviderForRunner()
  const originalContent = String(originalCandidate?.content || '')
  const beatPlanContent = String(beatPlanRecord?.content || '')
  const messages = buildShortDraftExpansionMessages({
    chapterNum,
    beatPlanRecord,
    originalContent,
    stageSnapshot: beatPlanRecord?.blockStageSnapshot || null
  })
  const result = await runnerChatCompletion(messages, {
    taskName: 'expand_short_draft',
    maxTokens: 9000,
    temperature: 0.46
  })
  const rawContent = extractChatCompletionContent(result)
  const expandedContent = cleanGeneratedChapterText(rawContent)
  const expandedWordCount = expandedContent.length
  const expandedPolicy = wordCountPolicy(expandedWordCount, wordTarget)
  const factDriftCheck = buildShortDraftFactDriftCheck({
    beatPlanContent,
    originalContent,
    expandedContent
  })
  const endingPreserved = checkShortDraftEndingPreserved(originalContent, expandedContent)
  const templateWordingHits = collectDraftTemplateWordingHits(expandedContent)
  const expansionPasses = [{
    taskName: 'expand_short_draft',
    wordCount: expandedWordCount,
    hardPass: expandedPolicy.hardPass,
    factDriftPassed: factDriftCheck.passed,
    endingPreservedPassed: endingPreserved.passed,
    templateWordingHits
  }]

  let finalContent = expandedContent
  let finalWordCount = expandedWordCount
  let finalPolicy = expandedPolicy
  let finalFactDriftCheck = factDriftCheck
  let finalEndingPreserved = endingPreserved
  let finalTemplateWordingHits = templateWordingHits
  let topUpExpandedWordCount = 0
  let topUpUsed = false
  let expansionRejectedReason = [
    expandedContent.trim() ? '' : 'empty_expansion',
    expandedPolicy.hardPass ? '' : 'expanded_below_hard_min',
    factDriftCheck.passed ? '' : 'fact_drift',
    endingPreserved.passed ? '' : 'ending_changed',
    templateWordingHits.length ? 'template_wording' : ''
  ].filter(Boolean).join('|')

  if (expansionRejectedReason === 'expanded_below_hard_min' && shouldTopUpShortDraftExpansion({
    expandedWordCount,
    factDriftCheck,
    endingPreserved,
    templateWordingHits
  })) {
    markChapterFlowEvent(chapterNum, 'below_hard_min_top_up_expand_short_draft_started', {
      shortDraftStrategy: 'expand_existing',
      firstExpandedWordCount: expandedWordCount,
      topUpTarget: SHORT_DRAFT_TOP_UP_TARGET,
      finalTarget: SHORT_DRAFT_EXPANSION_TARGET
    })
    finalContent = await topUpShortDraftExpansion({
      chapterNum,
      beatPlanRecord,
      originalContent,
      firstExpandedContent: expandedContent
    })
    topUpUsed = true
    topUpExpandedWordCount = finalContent.length
    finalWordCount = topUpExpandedWordCount
    finalPolicy = wordCountPolicy(finalWordCount, wordTarget)
    finalFactDriftCheck = buildShortDraftFactDriftCheck({
      beatPlanContent,
      originalContent,
      expandedContent: finalContent
    })
    finalEndingPreserved = checkShortDraftEndingPreserved(originalContent, finalContent)
    finalTemplateWordingHits = collectDraftTemplateWordingHits(finalContent)
    expansionPasses.push({
      taskName: 'top_up_expand_short_draft',
      wordCount: topUpExpandedWordCount,
      hardPass: finalPolicy.hardPass,
      factDriftPassed: finalFactDriftCheck.passed,
      endingPreservedPassed: finalEndingPreserved.passed,
      templateWordingHits: finalTemplateWordingHits
    })
    expansionRejectedReason = [
      finalContent.trim() ? '' : 'empty_top_up_expansion',
      finalPolicy.hardPass ? '' : 'top_up_below_hard_min',
      finalFactDriftCheck.passed ? '' : 'top_up_fact_drift',
      finalEndingPreserved.passed ? '' : 'top_up_ending_changed',
      finalTemplateWordingHits.length ? 'top_up_template_wording' : ''
    ].filter(Boolean).join('|')
    markChapterFlowEvent(
      chapterNum,
      expansionRejectedReason ? 'below_hard_min_top_up_expand_short_draft_rejected' : 'below_hard_min_top_up_expand_short_draft_done',
      {
        shortDraftStrategy: 'expand_existing',
        firstExpandedWordCount: expandedWordCount,
        topUpExpandedWordCount,
        finalCandidateWordCount: finalWordCount,
        expansionRejectedReason,
        factDriftCheck: finalFactDriftCheck,
        endingPreserved: finalEndingPreserved
      }
    )
  }

  const diagnostics = {
    shortDraftStrategy: 'expand_existing',
    originalWordCount: versionWordCount(originalCandidate),
    firstExpandedWordCount: expandedWordCount,
    topUpExpandedWordCount,
    expandedWordCount: finalWordCount,
    finalCandidateWordCount: finalWordCount,
    expansionPasses,
    topUpUsed,
    expansionAccepted: !expansionRejectedReason,
    expansionRejectedReason,
    factDriftCheck: finalFactDriftCheck,
    endingPreserved: finalEndingPreserved,
    templateWordingHits: finalTemplateWordingHits,
    targetRange: wordTarget?.targetRange || null,
    hardMin: wordTarget?.hardMin || wordTarget?.min || 0
  }

  if (expansionRejectedReason) {
    return {
      accepted: false,
      savedVersion: null,
      expandedContent: finalContent,
      diagnostics
    }
  }

  const savedVersion = await saveExpandedDraftVersion(chapterId, chapterNum, finalContent, provider, topUpUsed
    ? {
        title: `第 ${chapterNum} 章 - 短稿二段补足候选`,
        promptBrief: `top_up_expand_short_draft: 保留短稿事实和结尾补足至 ${SHORT_DRAFT_EXPANSION_TARGET}`
      }
    : {})
  await refreshWriterPageForSavedVersion(page, chapterNum)
  return {
    accepted: true,
    savedVersion,
    expandedContent: finalContent,
    diagnostics: {
      ...diagnostics,
      savedVersionId: savedVersion?.id || '',
      savedContentHash: contentHash(finalContent)
    }
  }
}

function hasNewGeneratedVersionCandidate(versions = [], {
  expectNewVersion = false,
  minVersionCountAfter = 0,
  previousVersionIds = [],
  previousContentHashes = [],
  previousVersionFingerprints = [],
  draftGenerationStartedAt = ''
} = {}) {
  const fingerprints = candidateVersionFingerprints(versions)
  const orderedFingerprints = fingerprints
    .slice()
    .sort((a, b) => (b.timestampMs || 0) - (a.timestampMs || 0))
  if (!fingerprints.length) {
    return { matched: false, reason: 'no_candidate_versions', fingerprints, candidate: null }
  }
  if (!expectNewVersion) {
    return { matched: true, reason: 'existing_candidate_allowed', fingerprints, candidate: orderedFingerprints.at(0) || null }
  }

  const previousIdSet = new Set((previousVersionIds || []).map(String).filter(Boolean))
  const previousHashSet = new Set((previousContentHashes || []).map(String).filter(Boolean))
  const previousFingerprintList = Array.isArray(previousVersionFingerprints) ? previousVersionFingerprints : []
  const previousLengthSet = new Set(previousFingerprintList.map(item => Number(item.contentLength || 0)).filter(Boolean))
  const startedAtMs = Date.parse(draftGenerationStartedAt || '')
  const requiredCount = Number(minVersionCountAfter || 0)
  const countIncreased = requiredCount > 0 && Array.isArray(versions) && versions.length >= requiredCount

  for (const fingerprint of orderedFingerprints) {
    const isNewId = Boolean(fingerprint.id) && !previousIdSet.has(fingerprint.id)
    const isNewHash = Boolean(fingerprint.contentHash) && !previousHashSet.has(fingerprint.contentHash)
    const lengthChanged = previousLengthSet.size > 0 && Boolean(fingerprint.contentLength) && !previousLengthSet.has(fingerprint.contentLength)
    const timestampAfterStart = Number.isFinite(startedAtMs) && startedAtMs > 0 && fingerprint.timestampMs >= startedAtMs
    if (isNewId || isNewHash || lengthChanged || timestampAfterStart) {
      return {
        matched: true,
        reason: isNewId ? 'new_version_id' : (isNewHash ? 'new_content_hash' : (lengthChanged ? 'content_length_changed' : 'version_timestamp_after_start')),
        fingerprints,
        candidate: fingerprint
      }
    }
  }
  if (countIncreased) {
    return { matched: true, reason: 'version_count_increased', fingerprints, candidate: orderedFingerprints.at(0) || null }
  }
  return { matched: false, reason: 'no_new_candidate_detected', fingerprints, candidate: orderedFingerprints.at(0) || null }
}

function visibleDraftErrorMessages(messages = []) {
  return (messages || []).filter(text =>
    /正文候选保存失败|draft_save_failed|按小纲生成失败|生成正文失败|AI 生成正文为空|Failed to fetch|供应商返回失败|后端 AI 代理请求失败/i.test(String(text || ''))
  )
}

function classifyDraftGenerationFailure(diagnostics = {}) {
  const visibleErrors = diagnostics.visibleErrorMessages || []
  if (visibleErrors.some(text => /正文候选保存失败|draft_save_failed/i.test(text))) return 'draft_save_failed'
  if (diagnostics.expectNewVersion && !diagnostics.newVersionDetected) {
    if (diagnostics.draftGenerationStartedAt && !diagnostics.streamStarted && Number(diagnostics.versionCountAfter || 0) <= Number(diagnostics.versionCountBefore || 0)) {
      return 'draft_regeneration_not_started'
    }
    return 'draft_regeneration_no_new_candidate'
  }
  if (diagnostics.draftGenerationStartedAt && !diagnostics.streamStarted && Number(diagnostics.versionCountAfter || 0) <= Number(diagnostics.versionCountBefore || 0)) {
    return 'draft_generation_not_started'
  }
  if (diagnostics.streamStarted && !diagnostics.streamEnded && (diagnostics.activeAction || []).length) return 'draft_stream_stalled'
  return 'draft_generation_timeout'
}

async function collectDraftGenerationWaitDiagnostics(page, chapterNum, chapterId, {
  beatPlanStartedAt = '',
  beatPlanEntryLabel = '',
  beatPlanSavedAt = '',
  draftGenerationStartedAt = '',
  draftGenerationEntryLabel = '',
  draftEntryClickedAfterBeatPlan = false,
  startedAtMs = 0,
  versionCountBefore = 0,
  expectNewVersion = false,
  minVersionCountAfter = 0,
  previousVersionIds = [],
  previousContentHashes = [],
  previousVersionFingerprints = [],
  qualityRebuildRetries = 0,
  beatPlanReviewConfirmations = 0,
  generationEntryLabel = '',
  generationEntryAttempts = 0,
  generationEntryDiagnostics = null,
  draftGenerationEntryDiagnostics = null
} = {}) {
  const chapter = await findChapter(chapterNum).catch(() => null)
  const versions = chapterId
    ? await api(`/projects/${report.project.id}/chapters/${chapterId}/versions`).catch(() => [])
    : []
  const messages = await visibleMessageTexts(page)
  const visible = await collectVisibleDiagnostics(page)
  const previousEntryDiagnostics = draftGenerationEntryDiagnostics || generationEntryDiagnostics || null
  const freshEntryDiagnostics = await collectDraftGenerationEntryDiagnostics(page, chapterNum, chapterId).catch(() => null)
  const entryDiagnostics = freshEntryDiagnostics
    ? {
        ...freshEntryDiagnostics,
        previousGenerationEntryDiagnostics: previousEntryDiagnostics
      }
    : previousEntryDiagnostics
  const aiTiming = latestAiProxyTimingSince(startedAtMs)
  const effectiveDraftGenerationEntryLabel = draftGenerationEntryLabel || generationEntryLabel
  const versionFreshness = hasNewGeneratedVersionCandidate(versions, {
    expectNewVersion,
    minVersionCountAfter,
    previousVersionIds,
    previousContentHashes,
    previousVersionFingerprints,
    draftGenerationStartedAt
  })
  const fingerprints = candidateVersionFingerprints(versions)
  return {
    beatPlanStartedAt,
    beatPlanEntryLabel,
    beatPlanSavedAt,
    draftGenerationStartedAt,
    draftGenerationEntryLabel: effectiveDraftGenerationEntryLabel,
    draftEntryClickedAfterBeatPlan,
    ...aiTiming,
    draftStreamRequestCount: aiTiming.streamRequestCount,
    draftStreamResponseCount: aiTiming.streamResponseCount,
    activeAction: visible.activeAction || [],
    expectNewVersion,
    minVersionCountAfter,
    previousVersionIds,
    previousContentHashes,
    previousVersionFingerprints,
    newVersionDetected: versionFreshness.matched,
    newVersionReason: versionFreshness.reason,
    newVersionCandidate: summarizeVersionFingerprint(versionFreshness.candidate),
    versionCountBefore,
    versionCountAfter: Array.isArray(versions) ? versions.length : 0,
    versionIds: (versions || []).map(version => version.id || '').filter(Boolean),
    contentHashes: fingerprints.map(item => item.contentHash),
    versionFingerprints: fingerprints.map(summarizeVersionFingerprint),
    versionLengths: (versions || []).map(version => String(version.content || '').length),
    chapterStatus: chapter?.status || '',
    visibleErrorMessages: visibleDraftErrorMessages([...messages, ...(visible.messages || [])]),
    messages,
    qualityRebuildRetries,
    beatPlanReviewConfirmations,
    generationEntryLabel: effectiveDraftGenerationEntryLabel,
    generationEntryAttempts,
    generationEntryDiagnostics: entryDiagnostics,
    draftGenerationEntryDiagnostics: entryDiagnostics,
    visibleButtons: entryDiagnostics?.visibleButtons || [],
    enabledButtons: entryDiagnostics?.enabledButtons || [],
    beatPlanModalVisible: Boolean(entryDiagnostics?.beatPlanModalVisible),
    currentUrl: entryDiagnostics?.currentUrl || page.url(),
    hasSavedBeatPlan: Boolean(entryDiagnostics?.hasSavedBeatPlan),
    versions,
    page: visible
  }
}

async function waitForSavedBeatPlan(page, chapterNum, timeoutMs = 300000) {
  const started = Date.now()
  let lastDiagnostics = null
  while (Date.now() - started < timeoutMs) {
    const beatPlanRecord = await api(`/projects/${report.project.id}/chapter-beat-plan/${chapterNum}`).catch(() => null)
    if (beatPlanRecord?.content) {
      return {
        beatPlanRecord,
        beatPlanSavedAt: new Date().toISOString()
      }
    }
    const messages = await visibleMessageTexts(page).catch(() => [])
    const beatPlanFailure = messages.find(text =>
      text.includes('生成章前小纲失败') || text.includes('小纲生成失败') || text.includes('小纲准备失败') || text.includes('小纲生成返回空内容') || text.includes('小纲为空') || text.includes('小纲过短') || text.includes('小纲质量闸未通过')
    )
    lastDiagnostics = {
      messages,
      page: await collectVisibleDiagnostics(page).catch(() => null)
    }
    if (beatPlanFailure) {
      const beatPlanPromptDiagnostics = await readBeatPlanDiagnostics(page, chapterNum)
      const summarizedBeatPlanDiagnostics = summarizeBeatPlanPromptDiagnostics(beatPlanPromptDiagnostics)
      const isSaveFailure = /保存小纲失败|保存章节小纲失败|小纲保存失败/.test(beatPlanFailure)
      const isQualityFailure = /质量闸未通过|占位字段|未填写|待补充|TODO|小纲质量/.test(beatPlanFailure)
      const isEmptyBeatPlanFailure = /小纲为空|空小纲|返回空内容/.test(beatPlanFailure)
      const diagnosticFailureCode = beatPlanPromptDiagnostics?.candidateFailureCode || beatPlanPromptDiagnostics?.beatPlanQualityDiagnostics?.failureCode || ''
      const isRequiresReview = summarizedBeatPlanDiagnostics.beatPlanSource === 'local_safety_requires_review' ||
        beatPlanPromptDiagnostics?.failureStage === 'beat_plan_requires_review' ||
        /beat_plan_requires_review|需人工审阅/.test(beatPlanFailure)
      const code = isSaveFailure
        ? 'beat_plan_saved_failed'
        : (isRequiresReview
            ? 'beat_plan_requires_review'
            : (['beat_plan_parse_failed', 'beat_plan_missing_fields', 'beat_plan_quality_failed'].includes(diagnosticFailureCode)
                ? diagnosticFailureCode
                : (isEmptyBeatPlanFailure ? 'beat_plan_empty_after_quality_cleaning' : (isQualityFailure ? 'beat_plan_quality_failed' : 'beat_plan_generation_failed'))))
      const error = new Error(`${code}: chapter ${chapterNum} beat plan failed before draft: ${beatPlanFailure}`)
      error.code = code
      error.liveDiagnostics = {
        stage: code,
        chapterNum,
        hasSavedBeatPlan: false,
        messages,
        ...summarizedBeatPlanDiagnostics,
        promptChars: summarizedBeatPlanDiagnostics.promptChars,
        promptTokensApprox: summarizedBeatPlanDiagnostics.promptTokensApprox,
        finalFailureAfterRecovery: summarizedBeatPlanDiagnostics.finalFailureAfterRecovery,
        derivedFallbackTriggered: summarizedBeatPlanDiagnostics.derivedFallbackTriggered,
        derivedFallbackSucceeded: summarizedBeatPlanDiagnostics.derivedFallbackSucceeded,
        qualityGateResult: summarizedBeatPlanDiagnostics.qualityGateResult,
        page: lastDiagnostics.page
      }
      throw error
    }
    await page.waitForTimeout(2000)
  }

  const error = new Error(`beat_plan_saved_failed: chapter ${chapterNum} beat plan was not saved after clicking beat plan entry`)
  error.code = 'beat_plan_saved_failed'
  const beatPlanPromptDiagnostics = await readBeatPlanDiagnostics(page, chapterNum)
  const summarizedBeatPlanDiagnostics = summarizeBeatPlanPromptDiagnostics(beatPlanPromptDiagnostics)
  error.liveDiagnostics = {
    stage: 'beat_plan_saved_failed',
    chapterNum,
    hasSavedBeatPlan: false,
    waitDurationMs: Date.now() - started,
    ...summarizedBeatPlanDiagnostics,
    promptChars: summarizedBeatPlanDiagnostics.promptChars,
    promptTokensApprox: summarizedBeatPlanDiagnostics.promptTokensApprox,
    finalFailureAfterRecovery: summarizedBeatPlanDiagnostics.finalFailureAfterRecovery,
    derivedFallbackTriggered: summarizedBeatPlanDiagnostics.derivedFallbackTriggered,
    derivedFallbackSucceeded: summarizedBeatPlanDiagnostics.derivedFallbackSucceeded,
    qualityGateResult: summarizedBeatPlanDiagnostics.qualityGateResult,
    ...lastDiagnostics
  }
  throw error
}

async function waitForGeneratedChapterVersion(page, chapterNum, options = {}) {
  const chapterId = await currentChapterId(chapterNum)
  const timeoutMs = Number(options.timeoutMs || 480000)
  const started = Date.now()
  let beatPlanStartedAt = options.beatPlanStartedAt || ''
  let beatPlanEntryLabel = options.beatPlanEntryLabel || ''
  let beatPlanSavedAt = options.beatPlanSavedAt || ''
  let draftGenerationStartedAt = options.draftGenerationStartedAt || ''
  let draftGenerationEntryLabel = options.draftGenerationEntryLabel || options.generationEntryLabel || ''
  let draftEntryClickedAfterBeatPlan = Boolean(options.draftEntryClickedAfterBeatPlan)
  let generationEntryLabel = draftGenerationEntryLabel
  let generationEntryDiagnostics = options.draftGenerationEntryDiagnostics || options.generationEntryDiagnostics || null
  let generationEntryAttempts = options.generationEntryAttempts || 0
  const initialVersions = await api(`/projects/${report.project.id}/chapters/${chapterId}/versions`).catch(() => [])
  const expectNewVersion = Boolean(options.expectNewVersion)
  const previousVersionFingerprints = Array.isArray(options.previousVersionFingerprints)
    ? options.previousVersionFingerprints
    : candidateVersionFingerprints(initialVersions)
  const previousVersionIds = Array.isArray(options.previousVersionIds)
    ? options.previousVersionIds
    : previousVersionFingerprints.map(item => item.id).filter(Boolean)
  const previousContentHashes = Array.isArray(options.previousContentHashes)
    ? options.previousContentHashes
    : previousVersionFingerprints.map(item => item.contentHash).filter(Boolean)
  const versionCountBefore = Number.isFinite(options.versionCountBefore)
    ? options.versionCountBefore
    : (Array.isArray(initialVersions) ? initialVersions.length : 0)
  const minVersionCountAfter = Number.isFinite(options.minVersionCountAfter)
    ? options.minVersionCountAfter
    : (expectNewVersion ? versionCountBefore + 1 : 0)
  const draftRegenerationNotStartedCode = 'draft_regeneration_not_started'
  const draftRegenerationNoNewCandidateCode = 'draft_regeneration_no_new_candidate'
  let qualityRebuildRetries = 0
  let beatPlanReviewConfirmations = 0
  let lastDiagnostics = null

  while (Date.now() - started < timeoutMs) {
    const versions = await api(`/projects/${report.project.id}/chapters/${chapterId}/versions`).catch(() => [])
    const versionFreshness = hasNewGeneratedVersionCandidate(versions, {
      expectNewVersion,
      minVersionCountAfter,
      previousVersionIds,
      previousContentHashes,
      previousVersionFingerprints,
      draftGenerationStartedAt
    })
    if (versionFreshness.matched) {
      return versions
    }

    const messages = await visibleMessageTexts(page)
    const draftErrors = visibleDraftErrorMessages(messages)
    if (draftErrors.length) {
      const diagnostics = await collectDraftGenerationWaitDiagnostics(page, chapterNum, chapterId, {
        beatPlanStartedAt,
        beatPlanEntryLabel,
        beatPlanSavedAt,
        draftGenerationStartedAt,
        draftGenerationEntryLabel,
        draftEntryClickedAfterBeatPlan,
        startedAtMs: draftGenerationStartedAt ? Date.parse(draftGenerationStartedAt) : started,
        versionCountBefore,
        expectNewVersion,
        minVersionCountAfter,
        previousVersionIds,
        previousContentHashes,
        previousVersionFingerprints,
        qualityRebuildRetries,
        beatPlanReviewConfirmations,
        generationEntryLabel,
        generationEntryAttempts,
        generationEntryDiagnostics,
        draftGenerationEntryDiagnostics: generationEntryDiagnostics
      })
      const code = classifyDraftGenerationFailure(diagnostics)
      const error = new Error(`${code}: chapter ${chapterNum} draft generation failed: ${draftErrors[0]}`)
      error.code = code
      error.liveDiagnostics = {
        stage: code,
        chapterId,
        beatPlanStartedAt: diagnostics.beatPlanStartedAt,
        beatPlanEntryLabel: diagnostics.beatPlanEntryLabel,
        beatPlanSavedAt: diagnostics.beatPlanSavedAt,
        draftGenerationStartedAt: diagnostics.draftGenerationStartedAt,
        draftGenerationEntryLabel: diagnostics.draftGenerationEntryLabel,
        draftEntryClickedAfterBeatPlan: diagnostics.draftEntryClickedAfterBeatPlan,
        lastAiProxyRequestAt: diagnostics.lastAiProxyRequestAt,
        lastAiProxyResponseAt: diagnostics.lastAiProxyResponseAt,
        streamStarted: diagnostics.streamStarted,
        streamEnded: diagnostics.streamEnded,
        draftStreamRequestCount: diagnostics.draftStreamRequestCount,
        draftStreamResponseCount: diagnostics.draftStreamResponseCount,
        activeAction: diagnostics.activeAction,
        versionCountBefore: diagnostics.versionCountBefore,
        versionCountAfter: diagnostics.versionCountAfter,
        chapterStatus: diagnostics.chapterStatus,
        visibleErrorMessages: diagnostics.visibleErrorMessages,
        generationEntryLabel: diagnostics.generationEntryLabel,
        generationEntryAttempts: diagnostics.generationEntryAttempts,
        generationEntryDiagnostics: diagnostics.generationEntryDiagnostics,
        ...diagnostics
      }
      throw error
    }
    const beatPlanFailure = messages.find(text =>
      text.includes('生成章前小纲失败') || text.includes('小纲准备失败') || text.includes('小纲生成返回空内容') || text.includes('小纲过短') || text.includes('小纲质量闸未通过')
    )
    if (beatPlanFailure) {
      const beatPlanRecord = await api(`/projects/${report.project.id}/chapter-beat-plan/${chapterNum}`).catch(() => null)
      const beatPlanPromptDiagnostics = await readBeatPlanDiagnostics(page, chapterNum)
      const summarizedBeatPlanDiagnostics = summarizeBeatPlanPromptDiagnostics(beatPlanPromptDiagnostics)
      const isSaveFailure = /保存小纲失败|保存章节小纲失败|小纲保存失败/.test(beatPlanFailure)
      const isQualityFailure = /质量闸未通过|占位字段|未填写|待补充|TODO|小纲质量/.test(beatPlanFailure)
      const diagnosticFailureCode = beatPlanPromptDiagnostics?.candidateFailureCode || beatPlanPromptDiagnostics?.beatPlanQualityDiagnostics?.failureCode || ''
      const isRequiresReview = summarizedBeatPlanDiagnostics.beatPlanSource === 'local_safety_requires_review' ||
        beatPlanPromptDiagnostics?.failureStage === 'beat_plan_requires_review' ||
        /beat_plan_requires_review|需人工审阅/.test(beatPlanFailure)
      const code = isSaveFailure
        ? 'beat_plan_saved_failed'
        : (isRequiresReview
            ? 'beat_plan_requires_review'
            : (['beat_plan_parse_failed', 'beat_plan_missing_fields', 'beat_plan_quality_failed'].includes(diagnosticFailureCode)
                ? diagnosticFailureCode
                : (isQualityFailure ? 'beat_plan_quality_failed' : 'beat_plan_generation_failed')))
      const error = new Error(`${code}: chapter ${chapterNum} beat plan failed before draft: ${beatPlanFailure}`)
      error.code = code
      error.liveDiagnostics = {
        stage: code,
        chapterId,
        chapterBeatPlan: beatPlanRecord,
        beatPlanQuality: analyzeBeatPlanQualityForReport(beatPlanRecord?.content || ''),
        hasSavedBeatPlan: Boolean(beatPlanRecord?.content),
        versionsCount: versions?.length || 0,
        messages,
        ...summarizedBeatPlanDiagnostics,
        page: await collectVisibleDiagnostics(page)
      }
      throw error
    }
    const needsBeatPlanReviewConfirmation = messages.some(text => text.includes('请先审阅本章小纲'))
    if (needsBeatPlanReviewConfirmation && beatPlanReviewConfirmations < 2) {
      const clickedStartFromReview = await clickDraftEntry(page, chapterNum, { chapterId }).catch(error => {
        if (error.code === 'draft_generation_entry_not_found') return null
        throw error
      })
      if (clickedStartFromReview?.clicked) {
        beatPlanReviewConfirmations += 1
        generationEntryAttempts += 1
        draftGenerationStartedAt = clickedStartFromReview.draftGenerationStartedAt
        draftGenerationEntryLabel = clickedStartFromReview.draftGenerationEntryLabel
        generationEntryLabel = draftGenerationEntryLabel
        generationEntryDiagnostics = clickedStartFromReview.diagnostics
        await dismissAppDialogs(page)
        lastDiagnostics = {
          versions,
          messages,
          qualityRebuildRetries,
          beatPlanReviewConfirmations,
          beatPlanStartedAt,
          beatPlanEntryLabel,
          beatPlanSavedAt,
          draftGenerationStartedAt,
          draftGenerationEntryLabel,
          draftEntryClickedAfterBeatPlan,
          generationEntryLabel,
          generationEntryAttempts,
          generationEntryDiagnostics,
          reviewConfirmation: 'confirmed_start_generation'
        }
        await new Promise(resolve => setTimeout(resolve, 5000))
        continue
      }
      lastDiagnostics = {
        versions,
        messages,
        qualityRebuildRetries,
        beatPlanReviewConfirmations,
        beatPlanStartedAt,
        beatPlanEntryLabel,
        beatPlanSavedAt,
        draftGenerationStartedAt,
        draftGenerationEntryLabel,
        draftEntryClickedAfterBeatPlan,
        generationEntryLabel,
        generationEntryAttempts,
        generationEntryDiagnostics,
        reviewConfirmation: 'start_generation_button_unavailable'
      }
    }
    const hasQualityNotice = messages.some(text => text.includes('AI 小纲质量不足'))
    if (hasQualityNotice && qualityRebuildRetries < 2) {
      const clickedQualityStart = await clickDraftEntry(page, chapterNum, { chapterId }).catch(error => {
        if (error.code === 'draft_generation_entry_not_found') return null
        throw error
      })
      if (clickedQualityStart?.clicked) {
        qualityRebuildRetries += 1
        generationEntryAttempts += 1
        draftGenerationStartedAt = clickedQualityStart.draftGenerationStartedAt
        draftGenerationEntryLabel = clickedQualityStart.draftGenerationEntryLabel
        generationEntryLabel = draftGenerationEntryLabel
        generationEntryDiagnostics = clickedQualityStart.diagnostics
        report.beatPlanQualityRebuilds.push({
          chapterNum,
          retry: qualityRebuildRetries,
          at: new Date().toISOString(),
          message: 'AI 小纲质量不足，已生成安全小纲，脚本按真实流程再次确认生成正文。'
        })
        writeReport()
      } else {
        lastDiagnostics = {
          versions,
          messages,
          qualityRebuildRetries,
          beatPlanReviewConfirmations,
          beatPlanStartedAt,
          beatPlanEntryLabel,
          beatPlanSavedAt,
          draftGenerationStartedAt,
          draftGenerationEntryLabel,
          draftEntryClickedAfterBeatPlan,
          generationEntryLabel,
          generationEntryAttempts,
          generationEntryDiagnostics,
          qualityNotice: 'start_generation_button_unavailable'
        }
      }
    }

    lastDiagnostics = await collectDraftGenerationWaitDiagnostics(page, chapterNum, chapterId, {
      beatPlanStartedAt,
      beatPlanEntryLabel,
      beatPlanSavedAt,
      draftGenerationStartedAt,
      draftGenerationEntryLabel,
      draftEntryClickedAfterBeatPlan,
      startedAtMs: draftGenerationStartedAt ? Date.parse(draftGenerationStartedAt) : started,
      versionCountBefore,
      expectNewVersion,
      minVersionCountAfter,
      previousVersionIds,
      previousContentHashes,
      previousVersionFingerprints,
      qualityRebuildRetries,
      beatPlanReviewConfirmations,
      generationEntryLabel,
      generationEntryAttempts,
      generationEntryDiagnostics,
      draftGenerationEntryDiagnostics: generationEntryDiagnostics
    })
    if (lastDiagnostics.hasSavedBeatPlan && !draftGenerationStartedAt && !lastDiagnostics.activeAction.length && !lastDiagnostics.streamStarted) {
      if (!beatPlanSavedAt) beatPlanSavedAt = new Date().toISOString()
      const clickedEntry = await clickDraftEntry(page, chapterNum, { chapterId })
      generationEntryAttempts += 1
      draftGenerationStartedAt = clickedEntry.draftGenerationStartedAt
      draftGenerationEntryLabel = clickedEntry.draftGenerationEntryLabel
      generationEntryLabel = draftGenerationEntryLabel
      generationEntryDiagnostics = clickedEntry.diagnostics
      draftEntryClickedAfterBeatPlan = Boolean(beatPlanEntryLabel || beatPlanStartedAt)
      lastDiagnostics = {
        ...lastDiagnostics,
        beatPlanStartedAt,
        beatPlanEntryLabel,
        beatPlanSavedAt,
        draftGenerationStartedAt,
        draftGenerationEntryLabel,
        draftEntryClickedAfterBeatPlan,
        generationEntryLabel,
        generationEntryAttempts,
        generationEntryDiagnostics,
        generationEntryClicked: true
      }
      await new Promise(resolve => setTimeout(resolve, 5000))
      continue
    }
    await new Promise(resolve => setTimeout(resolve, 5000))
  }

  const beatPlanRecord = await api(`/projects/${report.project.id}/chapter-beat-plan/${chapterNum}`).catch(() => null)
  const beatPlanPromptDiagnostics = await readBeatPlanDiagnostics(page, chapterNum)
  const summarizedBeatPlanDiagnostics = summarizeBeatPlanPromptDiagnostics(beatPlanPromptDiagnostics)
  const missingBeatPlan = !beatPlanRecord?.content
  const generatedButUnsaved = (lastDiagnostics?.messages || []).some(text => /保存小纲失败|保存章节小纲失败|小纲保存失败|本章小纲已生成/.test(text))
  const missingBeatPlanCode = generatedButUnsaved
    ? 'beat_plan_saved_failed'
    : (['beat_plan_parse_failed', 'beat_plan_missing_fields', 'beat_plan_quality_failed'].includes(beatPlanPromptDiagnostics?.candidateFailureCode || beatPlanPromptDiagnostics?.beatPlanQualityDiagnostics?.failureCode || '')
      ? (beatPlanPromptDiagnostics?.candidateFailureCode || beatPlanPromptDiagnostics?.beatPlanQualityDiagnostics?.failureCode)
      : (summarizedBeatPlanDiagnostics.beatPlanSource === 'local_safety_requires_review' ||
      beatPlanPromptDiagnostics?.failureStage === 'beat_plan_requires_review'
        ? 'beat_plan_requires_review'
        : 'beat_plan_generation_failed'))
  const finalDiagnostics = await collectDraftGenerationWaitDiagnostics(page, chapterNum, chapterId, {
    beatPlanStartedAt,
    beatPlanEntryLabel,
    beatPlanSavedAt,
    draftGenerationStartedAt,
    draftGenerationEntryLabel,
    draftEntryClickedAfterBeatPlan,
    startedAtMs: draftGenerationStartedAt ? Date.parse(draftGenerationStartedAt) : started,
    versionCountBefore,
    expectNewVersion,
    minVersionCountAfter,
    previousVersionIds,
    previousContentHashes,
    previousVersionFingerprints,
    qualityRebuildRetries,
    beatPlanReviewConfirmations,
    generationEntryLabel,
    generationEntryAttempts,
    generationEntryDiagnostics,
    draftGenerationEntryDiagnostics: generationEntryDiagnostics
  })
  const draftFailureCode = expectNewVersion && !finalDiagnostics.newVersionDetected
    ? (classifyDraftGenerationFailure(finalDiagnostics) ||
        (finalDiagnostics.draftGenerationStartedAt ? draftRegenerationNoNewCandidateCode : draftRegenerationNotStartedCode))
    : (!draftGenerationStartedAt && finalDiagnostics.hasSavedBeatPlan
        ? 'draft_generation_entry_not_found'
        : classifyDraftGenerationFailure(finalDiagnostics))
  const error = new Error(missingBeatPlan
    ? `${missingBeatPlanCode}: chapter ${chapterNum} beat plan was not generated or saved`
    : (draftFailureCode === 'draft_generation_entry_not_found'
        ? `${draftFailureCode}: chapter ${chapterNum} saved beat plan exists but no draft generation entry was found`
        : `${draftFailureCode}: chapter ${chapterNum} draft generation did not produce a saved candidate before timeout`)
  )
  error.code = missingBeatPlan ? missingBeatPlanCode : draftFailureCode
  error.liveDiagnostics = {
    stage: missingBeatPlan ? missingBeatPlanCode : draftFailureCode,
    chapterId,
    chapterBeatPlan: beatPlanRecord,
    hasSavedBeatPlan: Boolean(beatPlanRecord?.content),
    beatPlanStartedAt: finalDiagnostics.beatPlanStartedAt,
    beatPlanEntryLabel: finalDiagnostics.beatPlanEntryLabel,
    beatPlanSavedAt: finalDiagnostics.beatPlanSavedAt,
    draftGenerationStartedAt: finalDiagnostics.draftGenerationStartedAt,
    draftGenerationEntryLabel: finalDiagnostics.draftGenerationEntryLabel,
    draftEntryClickedAfterBeatPlan: finalDiagnostics.draftEntryClickedAfterBeatPlan,
    lastAiProxyRequestAt: finalDiagnostics.lastAiProxyRequestAt,
    lastAiProxyResponseAt: finalDiagnostics.lastAiProxyResponseAt,
    streamStarted: finalDiagnostics.streamStarted,
    streamEnded: finalDiagnostics.streamEnded,
    draftStreamRequestCount: finalDiagnostics.draftStreamRequestCount,
    draftStreamResponseCount: finalDiagnostics.draftStreamResponseCount,
    activeAction: finalDiagnostics.activeAction,
    versionCountBefore: finalDiagnostics.versionCountBefore,
    versionCountAfter: finalDiagnostics.versionCountAfter,
    chapterStatus: finalDiagnostics.chapterStatus,
    visibleErrorMessages: finalDiagnostics.visibleErrorMessages,
    generationEntryLabel: finalDiagnostics.generationEntryLabel,
    draftGenerationEntryLabel: finalDiagnostics.draftGenerationEntryLabel,
    generationEntryAttempts: finalDiagnostics.generationEntryAttempts,
    visibleButtons: finalDiagnostics.visibleButtons,
    enabledButtons: finalDiagnostics.enabledButtons,
    beatPlanModalVisible: finalDiagnostics.beatPlanModalVisible,
    currentUrl: finalDiagnostics.currentUrl,
    generationEntryDiagnostics: finalDiagnostics.generationEntryDiagnostics,
    ...(lastDiagnostics || {}),
    ...finalDiagnostics,
    versionsCount: finalDiagnostics.versionCountAfter,
    qualityRebuildRetries,
    beatPlanReviewConfirmations,
    ...summarizedBeatPlanDiagnostics,
    pendingSettings: await api(`/projects/${report.project.id}/settings/change-events?status=pending_review`).catch(() => []),
    pendingCanonFacts: (await api(`/projects/${report.project.id}/canon-facts`).catch(() => [])).filter(fact => fact.status === 'pending_review'),
    page: await collectVisibleDiagnostics(page)
  }
  throw error
}

async function waitForStoryBlockReviewSaved(chapterNum, timeoutMs = 600000) {
  return waitFor(`chapter ${chapterNum} story block review saved`, async () => {
    const beat = await api(`/projects/${report.project.id}/chapter-beat-plan/${chapterNum}`).catch(() => null)
    if (!beat?.storyBlockId) return false
    const blocks = await api(`/projects/${report.project.id}/story-blocks`).catch(() => [])
    const block = (blocks || []).find(item => item.id === beat.storyBlockId)
    if (!block) return false
    const reviews = block.reviewHistory || block.review_history || []
    return Array.isArray(reviews) && reviews.some(review =>
      review?.decision && Number(review.chapterNum || review.chapter_num || chapterNum) === Number(chapterNum)
    )
  }, timeoutMs, 5000)
}

async function getStoryBlockReviewContextForChapter(chapterNum) {
  const beat = await api(`/projects/${report.project.id}/chapter-beat-plan/${chapterNum}`).catch(() => null)
  if (!beat?.storyBlockId) return { beat, block: null, latestReview: null }
  const blocks = await api(`/projects/${report.project.id}/story-blocks`).catch(() => [])
  const block = (blocks || []).find(item => item.id === beat.storyBlockId) || null
  const reviews = block?.reviewHistory || block?.review_history || []
  const chapterReviews = Array.isArray(reviews)
    ? reviews.filter(review => Number(review?.chapterNum || review?.chapter_num || 0) === Number(chapterNum))
    : []
  return {
    beat,
    block,
    latestReview: chapterReviews.at(-1) || null
  }
}

function storyBlockStageContinueReason(review = {}) {
  return String(review?.stageContinueReason || review?.stage_continue_reason || review?.reason || '').trim()
}

async function validateStoryBlockReviewContinuation(chapterNum) {
  const context = await getStoryBlockReviewContextForChapter(chapterNum)
  const review = context.latestReview || {}
  if (review.stageContinues === true || review.stage_continues === true) {
    const reason = storyBlockStageContinueReason(review)
    if (!reason) throw storyBlockReviewInvalidError(chapterNum, context)
  }
  return context
}

function storyBlockReviewInvalidError(chapterNum, context = {}) {
  const review = context.latestReview || {}
  const error = new Error(`story_block_review_invalid: 第 ${chapterNum} 章 stageContinues=true 但缺少 stageContinueReason`)
  error.code = 'story_block_review_invalid'
  error.liveDiagnostics = {
    chapterNum,
    storyBlockId: context.beat?.storyBlockId || context.block?.id || '',
    blockStageId: context.beat?.blockStageId || '',
    previousStageContinues: Boolean(review.stageContinues || review.stage_continues),
    previousStageContinueReason: storyBlockStageContinueReason(review),
    review,
    blockStageSnapshot: context.beat?.blockStageSnapshot || null
  }
  return error
}

async function readFinalizationMarker(page, chapterNum) {
  return page.evaluate(({ projectId, chapterNum }) => {
    const raw = window.localStorage?.getItem(`novel_creator.chapter_finalization.${projectId}.${Number(chapterNum) || 0}`)
    if (!raw) return null
    try {
      return JSON.parse(raw)
    } catch {
      return { raw, parseError: true }
    }
  }, { projectId: report.project.id, chapterNum }).catch(error => ({ readError: error.message }))
}

async function isFinalizationMaskVisible(page) {
  return page.locator('.finalization-processing-mask').isVisible().catch(() => false)
}

async function throwIfPostFinalizeAiProxyFailure(page, chapterNum, stage = 'post_finalize_ai_proxy_failed') {
  const marker = await readFinalizationMarker(page, chapterNum)
  const failure = classifyPostFinalizeMarkerFailure(marker, latestPostFinalizeAiProxyFailureText())
  if (!failure) return
  const error = new Error(`${failure.code}: ${failure.message}`)
  error.code = failure.code
  error.liveDiagnostics = {
    stage: failure.stage || stage,
    marker,
    postFinalizeFailure: failure,
    consoleErrors: liveConsoleErrors.slice(-12),
    page: await collectVisibleDiagnostics(page)
  }
  throw error
}

async function readPostFinalizePersistenceState(chapterNum) {
  const beat = await api(`/projects/${report.project.id}/chapter-beat-plan/${chapterNum}`).catch(() => null)
  const blocks = await api(`/projects/${report.project.id}/story-blocks`).catch(() => [])
  const block = (blocks || []).find(item => item.id === beat?.storyBlockId)
  const reviews = block?.reviewHistory || block?.review_history || []
  const storyBlockReviewSaved = Array.isArray(reviews) && reviews.some(review =>
    review?.decision && Number(review.chapterNum || review.chapter_num || chapterNum) === Number(chapterNum)
  )
  const pendingSettings = await api(`/projects/${report.project.id}/settings/change-events?status=pending_review`).catch(error => ({ error: error.message }))
  const facts = await api(`/projects/${report.project.id}/canon-facts`).catch(error => ({ error: error.message }))
  const pendingCanonFacts = Array.isArray(facts)
    ? facts.filter(fact => fact.status === 'pending_review')
    : facts
  return {
    storyBlockReviewSaved,
    pendingSettingsReadable: Array.isArray(pendingSettings),
    pendingCanonFactsReadable: Array.isArray(pendingCanonFacts),
    pendingSettingsCount: Array.isArray(pendingSettings) ? pendingSettings.length : null,
    pendingCanonFactsCount: Array.isArray(pendingCanonFacts) ? pendingCanonFacts.length : null
  }
}

async function waitForPostFinalizeSettlement(page, chapterNum, timeoutMs = 600000) {
  const started = Date.now()
  const finalizationMarkerBeforeNextChapter = await readFinalizationMarker(page, chapterNum)
  let finalizationMarkerClearedAt = ''
  let lastSnapshot = {
    finalizationMarkerBeforeNextChapter,
    finalizationMarkerClearedAt,
    finalizationMaskVisible: false,
    postFinalizeWaitReason: 'waiting',
    postFinalizeWaitPassed: false,
    navigatedToSettingsAfterMarkerCleared: false
  }

  while (Date.now() - started < timeoutMs) {
    const marker = await readFinalizationMarker(page, chapterNum)
    const finalizationMaskVisible = await isFinalizationMaskVisible(page)
    const state = await readPostFinalizePersistenceState(chapterNum)
    if (!marker && !finalizationMarkerClearedAt) finalizationMarkerClearedAt = new Date().toISOString()

    const reasons = []
    if (marker) reasons.push('finalization_marker_present')
    const markerFailure = classifyPostFinalizeMarkerFailure(marker)
    if (markerFailure) reasons.push(markerFailure.reasonKey)
    if (finalizationMaskVisible) reasons.push('finalization_mask_visible')
    if (!state.storyBlockReviewSaved) reasons.push('story_block_review_not_saved')
    if (!state.pendingSettingsReadable) reasons.push('pending_settings_unreadable')
    if (!state.pendingCanonFactsReadable) reasons.push('pending_canon_facts_unreadable')

    lastSnapshot = {
      finalizationMarkerBeforeNextChapter,
      finalizationMarkerClearedAt,
      finalizationMaskVisible,
      postFinalizeFailed: Boolean(marker?.retryablePostprocessFailure || marker?.storyBlockSettlementFailure || marker?.postFinalizeFailed),
      retryablePostprocessFailure: marker?.retryablePostprocessFailure || null,
      storyBlockSettlementFailure: marker?.storyBlockSettlementFailure || null,
      postFinalizeFailureCode: markerFailure?.code || '',
      postFinalizeWaitReason: reasons.join(', ') || 'settled',
      postFinalizeWaitPassed: reasons.length === 0,
      navigatedToSettingsAfterMarkerCleared: false,
      pendingSettingsCount: state.pendingSettingsCount,
      pendingCanonFactsCount: state.pendingCanonFactsCount
    }
    postFinalizeSettlementByChapter.set(Number(chapterNum), lastSnapshot)
    upsertChapterReport({ chapterNum, ...lastSnapshot })
    writeReport()

    if (lastSnapshot.postFinalizeFailed) {
      const failure = classifyPostFinalizeMarkerFailure(marker, latestPostFinalizeAiProxyFailureText())
      const error = new Error(`${failure?.code || 'post_finalize_failed'}: ${failure?.message || '定稿后处理失败。'}`)
      error.code = failure?.code || 'post_finalize_failed'
      error.liveDiagnostics = {
        stage: failure?.stage || 'post_finalize_failed',
        marker,
        postFinalizeFailure: failure,
        ...lastSnapshot,
        consoleErrors: liveConsoleErrors.slice(-12)
      }
      throw error
    }

    if (lastSnapshot.postFinalizeWaitPassed) return lastSnapshot
    await page.waitForTimeout(3000)
  }

  const error = new Error(`finalize_postprocess_timed_out: chapter ${chapterNum} finalization marker did not settle`)
  error.code = 'finalize_postprocess_timed_out'
  error.liveDiagnostics = {
    stage: 'finalize_postprocess_timed_out',
    ...lastSnapshot,
    page: await collectVisibleDiagnostics(page)
  }
  throw error
}

async function clickStartGenerationIfPrompted(page, chapterNum, timeoutMs = 20000) {
  const started = Date.now()
  while (Date.now() - started < timeoutMs) {
    const active = await page.getByText(/正在生成本章|AI 正在处理正文/).isVisible().catch(() => false)
    if (active) return 'already_generating'
    const modalVisible = await isBeatPlanModalVisible(page)
    if (modalVisible) {
      await clickDraftEntry(page, chapterNum, { clickTimeoutMs: 5000 })
      return 'confirmed_prompt'
    }
    const generateButton = exactButton(page, '生成本章').last()
    const generateDisabled = await generateButton.isVisible().catch(() => false)
      && !await generateButton.isEnabled().catch(() => true)
    if (generateDisabled) return 'already_generating'
    await page.waitForTimeout(500)
  }
  return 'no_prompt_detected'
}

async function fillField(page, label, value) {
  const item = page.locator('.n-form-item').filter({
    has: page.getByText(label, { exact: true })
  }).last()
  const input = item.locator('textarea, input').first()
  await input.waitFor({ state: 'visible', timeout: 30000 })
  await input.fill(String(value))
}

async function clickTab(page, text) {
  await page.getByText(text, { exact: true }).click({ timeout: 30000 })
}

async function createProject(page) {
  await page.goto(FRONTEND, { waitUntil: 'domcontentloaded' })
  await clickButton(page, '新建项目')
  await fillField(page, '项目名称', projectName)
  await fillField(page, '题材', '长篇网文')
  await fillField(page, '简介', '240 万字长篇真实浏览器流程验收项目，验证故事块驱动生成链路。')
  await fillField(page, '目标字数（万字）', '240')
  await fillField(page, '目标章节数', '480')
  await clickButton(page, '创建')
  await page.waitForURL(/\/project\/[0-9a-f-]+/, { timeout: 60000 })
  report.project.id = page.url().match(/\/project\/([^/?#]+)/)?.[1] || ''
  await page.goto(`${FRONTEND}/project/${report.project.id}`, { waitUntil: 'domcontentloaded' })
  await page.locator('.n-modal-mask').waitFor({ state: 'hidden', timeout: 10000 }).catch(() => {})
  mark('created_clean_project_in_browser')
}

async function openExistingProject(page) {
  if (!EXISTING_PROJECT_ID) return
  report.project.id = EXISTING_PROJECT_ID
  report.project.name = EXISTING_PROJECT_NAME || report.project.name || EXISTING_PROJECT_ID
  await page.goto(`${FRONTEND}/project/${EXISTING_PROJECT_ID}`, { waitUntil: 'domcontentloaded' })
  await page.locator('.n-modal-mask').waitFor({ state: 'hidden', timeout: 10000 }).catch(() => {})
  await waitFor('existing project reachable', async () => {
    const chapters = await api(`/projects/${EXISTING_PROJECT_ID}/chapters`).catch(() => null)
    return Array.isArray(chapters)
  }, 60000, 2000)
  mark('opened_existing_project_in_browser')
}

async function createAndSelectSeed(page) {
  await page.goto(`${FRONTEND}/project/${report.project.id}`, { waitUntil: 'domcontentloaded' })
  await clickTab(page, '2 种子')
  await clickButton(page, '手动创建种子')
  await fillField(page, '标题', '尘星账本')
  await fillField(page, '题材', '长篇网文')
  await fillField(page, '一句话故事', '被逐出巡天司的少年，用一本会记债的星账追查诸天灵脉衰竭真相。')
  await fillField(page, '主角', '陆沉舟，十八岁，前巡天司见习星吏，擅长从账目和旧案里发现漏洞。')
  await fillField(page, '主角欲望', '洗清父亲旧案，找回被封存的巡天司名籍，同时弄清星账为什么只记录活人的代价。')
  await fillField(page, '核心矛盾', '巡天司、商盟和隐秘星债会都想控制星账；每次使用星账都要付出现实代价。')
  await fillField(page, '世界压力', '九州灵脉逐年枯竭，修士寿元、粮价和城防都被灵脉账目绑定，底层百姓最先承压。')
  await fillField(page, '开局钩子', '陆沉舟在雨夜当铺清账时，发现死去三年的父亲名字出现在当天新账上。')
  await fillField(page, '情绪价值', '悬念推进、底层逆袭、聪明人破局、每次选择都带代价。')
  await fillField(page, '差异化', '用账本、债务和灵脉账目推动长线剧情，不靠规则表解释世界。')
  await fillField(page, '风格目标', '通俗顺畅，行动推进强，少解释，多场景。')
  await fillField(page, '风险提示', '不要写成设定百科，不要让神秘人长篇交底，不要机械按长度切分正文。')
  await fillField(page, '结局锚点', '陆沉舟最终公开诸天总账，让修行代价回到每个选择者自己身上。')
  await clickButton(page, '创建')
  await waitFor('seed created', async () => (await api(`/projects/${report.project.id}/seeds`)).length > 0)
  await page.goto(`${FRONTEND}/project/${report.project.id}?tab=seed`, { waitUntil: 'domcontentloaded' })
  await page.locator('.n-modal-mask').waitFor({ state: 'hidden', timeout: 10000 }).catch(() => {})
  const alreadySelected = await waitFor('seed created or selected', async () => {
    const seeds = await api(`/projects/${report.project.id}/seeds`)
    return seeds.some(seed => seed.status === 'selected') ? 'selected' : 'created'
  })
  if (alreadySelected !== 'selected') {
    await clickButton(page, '选择')
    await waitFor('seed selected', async () => (await api(`/projects/${report.project.id}/seeds`)).some(seed => seed.status === 'selected'))
  }
  mark('created_seed_in_browser')
  mark('selected_seed_in_browser')
}

async function createBibleAndSettings(page) {
  await clickButton(page, '以此创建创作圣经', 30000)
  await waitFor('bible generated', async () => {
    const bible = await api(`/projects/${report.project.id}/bible`)
    return bible && (bible.premise || bible.worldRules || bible.themeBible)
  }, 240000, 3000)
  mark('generated_bible_from_selected_seed_in_browser')

  await page.goto(`${FRONTEND}/project/${report.project.id}?tab=bible`, { waitUntil: 'domcontentloaded' })
  await page.getByText('提取到设定库', { exact: true }).waitFor({ state: 'visible', timeout: 60000 })
  await clickButton(page, '提取到设定库')
  await waitFor('setting grouped progress visible', async () => {
    report.settingInitialization.groupedProgressVisible = await page.getByText(/正在提取设定库/).isVisible().catch(() => false)
    return report.settingInitialization.groupedProgressVisible
  }, 45000, 1000)

  let stableBackendCandidateCount = -1
  let stableBackendCandidatePolls = 0
  await waitFor('bible settings extraction groups settled', async () => {
    const events = await api(`/projects/${report.project.id}/settings/change-events`)
    const progress = await readSettingInitializationProgress(page)
    if (progress) {
      report.settingInitialization.failedGroups = progress.failedGroups || []
      report.settingInitialization.diagnostics = Object.values(progress.groups || {}).map(group => group.diagnostics).filter(Boolean)
      report.settingInitialization.pendingCandidatesCreated = (events || []).filter(event => event.status === 'pending_review').length
      return ['completed', 'partial_failed'].includes(progress.status)
    }
    const pendingCount = (events || []).filter(event => event.status === 'pending_review').length
    report.settingInitialization.pendingCandidatesCreated = pendingCount
    if (pendingCount > 0) {
      if (pendingCount === stableBackendCandidateCount) {
        stableBackendCandidatePolls += 1
      } else {
        stableBackendCandidateCount = pendingCount
        stableBackendCandidatePolls = 1
      }
      if (stableBackendCandidatePolls >= 5) {
        report.settingInitialization.failedGroups = []
        report.settingInitialization.diagnostics = [
          {
            source: 'backend_candidate_stability_fallback',
            message: '页面 localStorage 未暴露设定初始化进度，但后端待确认候选数量已稳定，转入确认链路。',
            pendingCandidatesCreated: pendingCount
          }
        ]
        return true
      }
    }
    return false
  }, 900000, 4000)

  for (let attempt = 0; attempt < 2 && report.settingInitialization.failedGroups.length; attempt += 1) {
    await dismissAppDialogs(page)
    await page.goto(`${FRONTEND}/project/${report.project.id}?tab=bible`, { waitUntil: 'domcontentloaded' })
    await page.locator('.n-modal-mask').waitFor({ state: 'hidden', timeout: 10000 }).catch(() => {})
    await page.getByText('继续提取/重试失败分组', { exact: true }).waitFor({ state: 'visible', timeout: 60000 })
    await clickButton(page, '继续提取/重试失败分组', 60000)
    await waitFor(`bible settings failed groups retry ${attempt + 1}`, async () => {
      const progress = await readSettingInitializationProgress(page)
      const events = await api(`/projects/${report.project.id}/settings/change-events`)
      if (!progress) return false
      report.settingInitialization.failedGroups = progress.failedGroups || []
      report.settingInitialization.diagnostics = Object.values(progress.groups || {}).map(group => group.diagnostics).filter(Boolean)
      report.settingInitialization.pendingCandidatesCreated = (events || []).filter(event => event.status === 'pending_review').length
      return ['completed', 'partial_failed'].includes(progress.status)
    }, 600000, 4000)
  }

  if (report.settingInitialization.failedGroups.length) {
    throw new Error(`设定初始化仍有失败分组：${report.settingInitialization.failedGroups.join(', ')}`)
  }
  mark('extracted_bible_settings_in_browser')

  await page.goto(`${FRONTEND}/project/${report.project.id}?tab=settingsLibrary`, { waitUntil: 'domcontentloaded' })
  await confirmAllSettings(page)
  mark('confirmed_initial_settings_in_browser')
}

async function confirmAllSettings(page) {
  for (let i = 0; i < 6; i += 1) {
    const pending = sortSettingEventsForConfirmation(
      (await api(`/projects/${report.project.id}/settings/change-events?status=pending_review`)) || []
    )
    if (!pending.length) {
      const accepted = (await api(`/projects/${report.project.id}/settings/change-events?status=accepted`)) || []
      report.settingInitialization.acceptedCandidates = accepted.length
      return
    }
    const settingEntities = await api(`/projects/${report.project.id}/settings/entities`).catch(() => [])
    sortSettingEventsForConfirmation(pending)
    const split = splitSettingEventsByRisk(pending, settingEntities)
    await page.getByText(/待确认设定变更/).first().click().catch(() => {})
    await page.waitForTimeout(500)
    if (split.hardConflicts.length && split.batchAcceptable.length) {
      if (await exactButton(page, '批量确认').last().isVisible().catch(() => false)) {
        await clickButton(page, '批量确认')
        await page.waitForTimeout(2500)
      }
    } else if (split.hardConflicts.length) {
      await resolveHardConflictSettingsIfConfigured(pending, settingEntities)
      const afterResolution = (await api(`/projects/${report.project.id}/settings/change-events?status=pending_review`).catch(() => [])) || []
      const refreshedEntities = await api(`/projects/${report.project.id}/settings/entities`).catch(() => [])
      const remainingHard = splitSettingEventsByRisk(afterResolution, refreshedEntities).hardConflicts
      if (remainingHard.length) throw createSettingReviewRequiredError('hard_conflict_setting_review_required', afterResolution, refreshedEntities)
    } else if (await exactButton(page, '批量确认').last().isVisible().catch(() => false)) {
      await clickButton(page, '批量确认')
      await page.waitForTimeout(2500)
    } else {
      const confirm = exactButton(page, '确认').last()
      await confirm.waitFor({ state: 'visible', timeout: 10000 })
      await confirm.click()
      await page.waitForTimeout(1000)
    }
    const stillPending = (await api(`/projects/${report.project.id}/settings/change-events?status=pending_review`).catch(() => [])) || []
    const refreshedSettingEntities = await api(`/projects/${report.project.id}/settings/entities`).catch(() => [])
    const stillHard = splitSettingEventsByRisk(stillPending, refreshedSettingEntities).hardConflicts
    if (stillHard.length) {
      await resolveHardConflictSettingsIfConfigured(stillPending, refreshedSettingEntities)
      const afterResolution = (await api(`/projects/${report.project.id}/settings/change-events?status=pending_review`).catch(() => [])) || []
      const refreshedEntities = await api(`/projects/${report.project.id}/settings/entities`).catch(() => [])
      const remainingHard = splitSettingEventsByRisk(afterResolution, refreshedEntities).hardConflicts
      if (remainingHard.length) throw createSettingReviewRequiredError('hard_conflict_setting_review_required', afterResolution, refreshedEntities)
    }
  }
  const pending = (await api(`/projects/${report.project.id}/settings/change-events?status=pending_review`).catch(() => [])) || []
  const settingEntities = await api(`/projects/${report.project.id}/settings/entities`).catch(() => [])
  const relationshipAutoFailure = detectUnconfirmedAutoAcceptableRelationshipSettings(pending, settingEntities)
  if (relationshipAutoFailure) {
    throw createSettingReviewRequiredError(relationshipAutoFailure.code, pending, settingEntities)
  }
  throw createSettingReviewRequiredError('manual_setting_review_required', pending, settingEntities)
}

async function resolveHardConflictSettingsIfConfigured(events = [], settingEntities = []) {
  const mode = String(process.env.AUTO_RESOLVE_HARD_CONFLICT_SETTINGS || '').trim().toLowerCase()
  if (!['accept', 'reject'].includes(mode)) return
  const { hardConflicts } = splitSettingEventsByRisk(events, settingEntities)
  for (const event of hardConflicts) {
    const endpoint = mode === 'accept' ? 'accept' : 'reject'
    await api(`/projects/${report.project.id}/settings/change-events/${event.id}/${endpoint}`, { method: 'POST' })
  }
}

function createSettingReviewRequiredError(code, pending = [], settingEntities = []) {
  const details = classifySettingEvents(pending, settingEntities)
  const pendingHardConflicts = pendingHardConflictDiagnostics(pending, settingEntities)
  const message = code === 'hard_conflict_setting_review_required'
    ? '仍有硬冲突设定需要逐条确认，处理后才能进入下一章。'
    : code === 'relationship_auto_confirm_failed'
      ? '低风险关系设定未能自动确认，请检查关系归位或批量确认流程。'
      : '仍有待确认设定需要人工处理，处理后才能进入下一章。'
  const error = new Error(message)
  error.code = code
  error.settingReview = {
    stage: code,
    pendingSettingIds: details.map(item => item.id).filter(Boolean),
    pendingSettings: details,
    pendingHardConflicts,
    hasHardConflict: details.some(item => item.classification === SETTING_CHANGE_CLASSIFICATIONS.hardConflict)
  }
  return error
}

async function generateVolumes(page) {
  await page.goto(`${FRONTEND}/project/${report.project.id}?tab=chapters`, { waitUntil: 'domcontentloaded' })
  await clickButton(page, 'AI 生成分卷规划')
  await waitForVolumePlanGenerated(page, 420000)
  const volumes = await api(`/projects/${report.project.id}/volumes`)
  report.volumePlanning.generated = true
  report.volumePlanning.placeholderWarnings = detectVolumePlaceholders(volumes)
  report.volumePlanning.diagnostics = await readVolumePlanningDiagnostics(page)
  mark('generated_volume_plan_in_browser')
}

async function waitForVolumePlanGenerated(page, timeoutMs = 420000) {
  const started = Date.now()
  while (Date.now() - started < timeoutMs) {
    const volumes = await api(`/projects/${report.project.id}/volumes`).catch(() => [])
    if (volumes.length > 0) return volumes

    const dialogs = await page.locator('.n-dialog, .n-message, .n-notification, .n-alert')
      .evaluateAll(nodes => nodes.map(node => node.innerText || node.textContent || '').filter(Boolean))
      .catch(() => [])
    const failureDialog = dialogs.find(text =>
      text.includes('AI 分卷规划失败') || text.includes('分卷规划失败')
    )
    if (failureDialog) {
      const diagnostics = await readVolumePlanningDiagnostics(page)
      report.volumePlanning.diagnostics = diagnostics
      writeReport()
      const error = new Error(`volume plan failure dialog: ${failureDialog.slice(0, 500)}`)
      error.code = classifyVolumePlanningFailureCode(diagnostics, 'volume_plan_ui_wait_failed')
      error.liveDiagnostics = {
        stage: error.code,
        dialog: failureDialog,
        diagnostics,
        page: await collectVisibleDiagnostics(page)
      }
      throw error
    }
    await page.waitForTimeout(4000)
  }

  const diagnostics = await readVolumePlanningDiagnostics(page)
  report.volumePlanning.diagnostics = diagnostics
  writeReport()
  const error = new Error('volume plan generated timed out')
  error.code = classifyVolumePlanningFailureCode(diagnostics, 'volume_plan_ui_wait_failed')
  error.liveDiagnostics = {
    stage: error.code,
    diagnostics,
    page: await collectVisibleDiagnostics(page)
  }
  throw error
}

function classifyVolumePlanningFailureCode(diagnostics = null, fallback = 'volume_plan_ui_wait_failed') {
  const failureStage = String(diagnostics?.failureStage || '').trim()
  if (failureStage === 'empty_response' || failureStage === 'parse_failed') return 'volume_plan_parse_failed'
  if (failureStage === 'normalize_empty') return 'volume_plan_normalize_empty'
  if (failureStage === 'save_failed') return 'volume_plan_save_failed'
  if (Array.isArray(diagnostics?.saveErrors) && diagnostics.saveErrors.length) return 'volume_plan_save_failed'
  if (diagnostics?.normalizedVolumeCount === 0 && Array.isArray(diagnostics?.droppedVolumes) && diagnostics.droppedVolumes.length) return 'volume_plan_normalize_empty'
  return fallback
}

function detectVolumePlaceholders(volumes = []) {
  const pattern = /摘要不完整|TODO|待补充|略/
  return (volumes || []).flatMap(volume =>
    ['title', 'summary', 'coreGoal', 'mainConflict', 'handoffPoint']
      .filter(key => pattern.test(String(volume[key] || '')))
      .map(key => ({ volumeId: volume.id, volumeNum: volume.volumeNum, field: key, value: volume[key] }))
  )
}

function summarizeStoryBlocks(blocks = []) {
  return toList(blocks).map(block => {
    const stagePlan = toList(block.stagePlan || block.stage_plan)
    const completedStages = toList(block.completedStages || block.completed_stages)
    const lockState = block.lockState || block.lock_state || {}
    const chapterRefs = new Set(toList(block.chapterRefs || block.chapter_refs).map(String))
    const closedUnexecutedIds = new Set(toList(lockState.closedUnexecutedStageIds || lockState.closed_unexecuted_stage_ids).map(String).filter(Boolean))
    const invalidatedIds = new Set(toList(lockState.invalidatedStageIds || lockState.invalidated_stage_ids).map(String).filter(Boolean))
    const executedIds = new Set()
    for (const stage of stagePlan) {
      const stageId = String(stage.id || stage.stageId || stage.stage_id || '')
      for (const ref of toList(stage.chapterRefs || stage.chapter_refs)) {
        chapterRefs.add(String(ref))
        if (stageId) executedIds.add(stageId)
      }
      if (stage.completedChapterNum || stage.completed_chapter_num) {
        chapterRefs.add(String(stage.completedChapterNum || stage.completed_chapter_num))
        if (stageId) executedIds.add(stageId)
      }
      if (stage.lockedByBeatPlan || stage.locked_by_beat_plan || stage.lockedByFinalChapter || stage.locked_by_final_chapter) {
        if (stageId) executedIds.add(stageId)
      }
    }
    const completedIds = new Set(completedStages.map(stage => String(stage.id || stage.stageId || stage.stage_id || '')))
    for (const stage of stagePlan) {
      const stageId = String(stage.id || stage.stageId || stage.stage_id || '')
      const status = String(stage.status || '')
      if (status === 'completed') {
        completedIds.add(stageId)
        if (stageId) executedIds.add(stageId)
      } else if (['closed_unexecuted', 'skipped_by_block_close', 'closed', 'skipped'].includes(status) || stage.closeStatus === 'skipped_by_block_close') {
        if (stageId) closedUnexecutedIds.add(stageId)
      } else if (status === 'invalidated') {
        if (stageId) invalidatedIds.add(stageId)
      }
    }
    const coveredChapterCount = [...chapterRefs].filter(Boolean).length
    const remainingStages = stagePlan.filter(stage => {
      const stageId = String(stage.id || stage.stageId || stage.stage_id || '')
      if (!stageId || completedIds.has(stageId)) return false
      if (closedUnexecutedIds.has(stageId) || invalidatedIds.has(stageId)) return false
      if (['completed', 'closed', 'skipped', 'closed_unexecuted', 'skipped_by_block_close', 'invalidated'].includes(String(stage.status || ''))) return false
      if (toList(stage.chapterRefs || stage.chapter_refs).length) return false
      return true
    })
    const completedStageCount = [...completedIds].filter(Boolean).length
    const closedUnexecutedStageCount = [...closedUnexecutedIds].filter(Boolean).length
    const invalidatedStageCount = [...invalidatedIds].filter(Boolean).length
    const evidenceAudit = normalizeCompletionEvidenceForStageSplit({
      completionEvidence: lockState.completionEvidence || '',
      stageCount: stagePlan.length,
      completedStageCount,
      closedUnexecutedStageCount
    })
    return {
      id: block.id || '',
      title: block.title || '',
      status: block.status || '',
      coveredChapterRefs: [...chapterRefs].filter(Boolean),
      coveredChapterCount,
      stageCount: stagePlan.length,
      executedStageCount: [...executedIds].filter(Boolean).length,
      completedStageCount,
      closedUnexecutedStageCount,
      invalidatedStageCount,
      remainingStageCount: remainingStages.length,
      activeBlockRemainingStages: block.status === 'active'
        ? remainingStages.map(stage => ({
            id: stage.id || stage.stageId || stage.stage_id || '',
            purpose: stage.purpose || stage.stagePurpose || stage.goal || ''
          }))
        : [],
      completionEvidence: evidenceAudit.completionEvidence,
      completionEvidenceWarning: evidenceAudit.warning,
      singleChapterBlockReason: lockState.singleChapterBlockReason || lockState.shortBlockReason || '',
      closedBy: lockState.closedBy || '',
      blockCloseReasonType: lockState.blockCloseReasonType || '',
      earlyCloseAllowed: lockState.earlyCloseAllowed,
      earlyCloseEvidence: lockState.earlyCloseEvidence || lockState.completionEvidence || '',
      singleChapterCompletedWholeBlock: ['completed', 'closed'].includes(block.status)
        && coveredChapterCount === 1
        && stagePlan.length > 0
        && completedStageCount >= stagePlan.length
        && closedUnexecutedStageCount === 0
        && invalidatedStageCount === 0
    }
  })
}

function normalizeCompletionEvidenceForStageSplit({
  completionEvidence = '',
  stageCount = 0,
  completedStageCount = 0,
  closedUnexecutedStageCount = 0
} = {}) {
  const text = String(completionEvidence || '')
  const contradictsStageSplit = completedStageCount < stageCount &&
    closedUnexecutedStageCount > 0 &&
    /所有阶段完成|所有阶段已完成|阶段全部完成|阶段均已完成/.test(text)
  if (!contradictsStageSplit) {
    return { completionEvidence: text, warning: '' }
  }
  return {
    completionEvidence: text.replace(/所有阶段完成|所有阶段已完成|阶段全部完成|阶段均已完成/g, '块目标达成，剩余阶段随块关闭'),
    warning: 'evidence_contradiction'
  }
}

async function refreshStoryBlockSummaries() {
  const blocks = await api(`/projects/${report.project.id}/story-blocks`).catch(() => [])
  report.storyBlockSummaries = summarizeStoryBlocks(blocks)
  updateStoryBlockGranularityMetrics()
  const shortBlocks = report.storyBlockSummaries.filter(block =>
    ['completed', 'closed'].includes(block.status) && block.coveredChapterCount <= 1
  )
  for (const block of shortBlocks) {
    const code = `story_block_too_short:${block.id}`
    if (report.qualityWarnings.some(item => item.code === code)) continue
    report.qualityWarnings.push({
      code,
      message: `故事块 ${block.title || block.id} 覆盖章节数为 ${block.coveredChapterCount}，需要产品复审是否过短。`
    })
  }
  for (const block of report.storyBlockSummaries.filter(item => item.completionEvidenceWarning === 'evidence_contradiction')) {
    const code = `evidence_contradiction:${block.id}`
    if (report.qualityWarnings.some(item => item.code === code)) continue
    report.qualityWarnings.push({
      code,
      message: `故事块 ${block.title || block.id} completionEvidence 曾声称所有阶段完成，但 completed=${block.completedStageCount}/${block.stageCount} 且 closedUnexecuted=${block.closedUnexecutedStageCount}，已按“块目标达成，剩余阶段随块关闭”口径修正。`
    })
  }
}

function updateStoryBlockGranularityMetrics() {
  const summaries = report.storyBlockSummaries || []
  const closedOrCompleted = summaries.filter(block => ['completed', 'closed'].includes(block.status))
  const singleChapterBlocks = closedOrCompleted.filter(block => block.coveredChapterCount === 1)
  const chaptersPerBlock = summaries.map(block => ({
    id: block.id,
    title: block.title,
    status: block.status,
    chapters: block.coveredChapterCount,
    chapterRefs: block.coveredChapterRefs
  }))
  const totalCovered = summaries.reduce((sum, block) => sum + Number(block.coveredChapterCount || 0), 0)
  const consecutiveSingleChapterBlocks = maxConsecutiveSingleChapterBlocks(summaries)
  const stalledBlocks = summaries.filter(block =>
    block.coveredChapterCount >= 3 &&
    block.completedStageCount <= 1 &&
    block.status !== 'completed'
  )
  const fragmentedBlocks = consecutiveSingleChapterBlocks >= 2
  const averageChaptersPerBlock = summaries.length ? Number((totalCovered / summaries.length).toFixed(2)) : 0
  const weakSingleChapterBlocks = singleChapterBlocks.filter(block =>
    block.earlyCloseAllowed !== true ||
    !block.blockCloseReasonType ||
    block.blockCloseReasonType === 'weak_or_generic'
  )
  const qualityHold = averageChaptersPerBlock < 1.5 && consecutiveSingleChapterBlocks >= 2
    ? 'story_block_fragmentation_quality_hold'
    : null
  report.storyBlockGranularity = {
    blocksCreated: summaries.length,
    chaptersPerBlock,
    averageChaptersPerBlock,
    singleChapterBlockCount: singleChapterBlocks.length,
    consecutiveSingleChapterBlocks,
    weakSingleChapterBlockCount: weakSingleChapterBlocks.length,
    blockCompletionEvidence: closedOrCompleted.map(block => ({
      id: block.id,
      title: block.title,
      status: block.status,
      completionEvidence: block.completionEvidence,
      singleChapterBlockReason: block.singleChapterBlockReason,
      closedBy: block.closedBy,
      blockCloseReasonType: block.blockCloseReasonType,
      earlyCloseAllowed: block.earlyCloseAllowed,
      earlyCloseEvidence: block.earlyCloseEvidence
    })),
    storyBlockGranularityWarning: fragmentedBlocks ? 'story_block_too_fragmented' : null,
    storyBlockStalledWarning: stalledBlocks.length ? 'story_block_stalled' : null,
    storyBlockGranularityQualityHold: qualityHold,
    stageCountPerBlock: summaries.map(block => ({ id: block.id, stageCount: block.stageCount })),
    executedStageCountPerBlock: summaries.map(block => ({ id: block.id, executedStageCount: block.executedStageCount })),
    completedStageCountPerBlock: summaries.map(block => ({ id: block.id, completedStageCount: block.completedStageCount })),
    closedUnexecutedStageCountPerBlock: summaries.map(block => ({ id: block.id, closedUnexecutedStageCount: block.closedUnexecutedStageCount })),
    invalidatedStageCountPerBlock: summaries.map(block => ({ id: block.id, invalidatedStageCount: block.invalidatedStageCount })),
    activeBlockRemainingStages: summaries
      .filter(block => block.status === 'active')
      .flatMap(block => block.activeBlockRemainingStages.map(stage => ({ blockId: block.id, ...stage })))
  }
  if (fragmentedBlocks && !report.qualityWarnings.some(item => item.code === 'story_block_too_fragmented')) {
    report.qualityWarnings.push({
      code: 'story_block_too_fragmented',
      message: `连续 ${consecutiveSingleChapterBlocks} 个故事块只覆盖单章，需要复核是否把故事块退化成章节小纲。`
    })
  }
  if (qualityHold && !report.qualityWarnings.some(item => item.code === qualityHold)) {
    report.qualityWarnings.push({
      code: qualityHold,
      message: `故事块平均覆盖 ${averageChaptersPerBlock} 章且连续单章块达到 ${consecutiveSingleChapterBlocks}，不建议扩大到 PHASE_TARGET=10/20。`
    })
  }
  if (stalledBlocks.length && !report.qualityWarnings.some(item => item.code === 'story_block_stalled')) {
    report.qualityWarnings.push({
      code: 'story_block_stalled',
      message: `发现 ${stalledBlocks.length} 个长故事块多章推进但阶段完成过少，需要复核是否停滞。`
    })
  }
}

function maxConsecutiveSingleChapterBlocks(summaries = []) {
  let max = 0
  let current = 0
  for (const block of summaries) {
    if (['completed', 'closed'].includes(block.status) && block.coveredChapterCount === 1) {
      current += 1
      max = Math.max(max, current)
    } else {
      current = 0
    }
  }
  return max
}

function upsertChapterReport(entry) {
  const index = report.chapterReports.findIndex(item => Number(item.chapterNum) === Number(entry.chapterNum))
  if (index >= 0) {
    report.chapterReports[index] = {
      ...report.chapterReports[index],
      ...entry,
      flowEvents: {
        ...(report.chapterReports[index].flowEvents || {}),
        ...(entry.flowEvents || {})
      }
    }
  } else {
    report.chapterReports.push(entry)
  }
}

function countCjkChars(text = '') {
  return (String(text || '').match(/[\u3400-\u9fff]/g) || []).length
}

function wordCountPolicyStatus(wordCount, wordTarget = buildLiveChapterWordTarget()) {
  return wordCountPolicy(wordCount, wordTarget).status
}

function buildLiveChapterWordTarget(volumeStage = null) {
  return buildChapterWordTarget({
    targetWords: report.target.targetWords,
    targetChapters: report.target.targetChapters
  }, volumeStage) || {
    target: 5000,
    min: 4500,
    max: 6500,
    hardMin: 4000,
    hardMax: 7000
  }
}

function wordCountPolicy(wordCount, wordTarget = buildLiveChapterWordTarget()) {
  const count = Number(wordCount || 0)
  const target = wordTarget?.target ? wordTarget : buildLiveChapterWordTarget()
  const hardMin = Number(target.hardMin || 0)
  const softMin = Number(target.min || 0)
  const targetMin = Number(target.min || 0)
  const targetMax = Number(target.max || 0)
  const assessment = assessChapterWordCount('字'.repeat(Math.max(0, count)), target)
  const base = {
    hardMin,
    liveHardMin: hardMin,
    appHardMin: hardMin,
    softMin,
    wordTarget: target,
    targetRange: { min: targetMin, max: targetMax }
  }
  if (!count) {
    return { status: 'missing', hardPass: false, ...base }
  }
  if (assessment.level === 'hard_under') {
    return { status: 'below_hard_min', hardPass: false, ...base }
  }
  if (assessment.level === 'under') {
    return { status: 'soft_floor_warning', hardPass: true, ...base }
  }
  if (assessment.level === 'over' || assessment.level === 'hard_over') {
    return { status: 'above_target_warning', hardPass: true, ...base }
  }
  return { status: 'within_target', hardPass: true, ...base }
}

function analyzeBeatPlanQualityForReport(content = '') {
  const labels = [
    ['chapterEvent', '\u672c\u7ae0\u4e8b\u4ef6'],
    ['characterGoal', '\u4eba\u7269\u76ee\u6807'],
    ['coreConflict', '\u6838\u5fc3\u51b2\u7a81'],
    ['externalPressure', '\u5916\u90e8\u538b\u529b'],
    ['costOrLoss', '\u4ee3\u4ef7\u6216\u635f\u5931'],
    ['irreversibleChange', '\u4e0d\u53ef\u9006\u53d8\u5316'],
    ['endingHandoff', '\u7ed3\u5c3e\u4ea4\u63a5']
  ]
  const placeholderPattern = /^(?:\u672a\u586b\u5199|\u7a7a|\u5f85\u8865\u5145|TODO|TBD|\u7565|\u6682\u65e0|\u65e0|\u4e0d\u8be6|\u5f85\u5b9a|N\/A|NA|null|none)[\u3002.!！?？\s]*$/i
  const missingFields = []
  const placeholderFields = []
  for (const [field, label] of labels) {
    const match = String(content || '').match(new RegExp(`###\\s*${label}\\s*\\n([\\s\\S]*?)(?=\\n###\\s|$)`))
    const value = String(match?.[1] || '').trim()
    if (!value) missingFields.push(field)
    else if (placeholderPattern.test(value)) placeholderFields.push(field)
  }
  return {
    missingFields,
    placeholderFields,
    repaired: false,
    repairSucceeded: false,
    finalBeatPlanLength: String(content || '').length
  }
}

function markChapterFlowEvent(chapterNum, event, details = {}) {
  const existing = report.chapterReports.find(item => Number(item.chapterNum) === Number(chapterNum)) || { chapterNum }
  upsertChapterReport({
    ...existing,
    chapterNum,
    progressStage: event,
    flowEvents: {
      ...(existing.flowEvents || {}),
      [event]: {
        at: new Date().toISOString(),
        ...details
      }
    }
  })
  writeReport()
}

async function recordChapterDraftProgress(page, chapterNum, stage = 'draft_generated') {
  const existingReport = report.chapterReports.find(item => Number(item.chapterNum) === Number(chapterNum)) || {}
  const chapter = await findChapter(chapterNum).catch(() => null)
  const beat = await api(`/projects/${report.project.id}/chapter-beat-plan/${chapterNum}`).catch(() => null)
  const versions = chapter?.id
    ? await api(`/projects/${report.project.id}/chapters/${chapter.id}/versions`).catch(() => [])
    : []
  const candidateVersions = Array.isArray(versions)
    ? versions.filter(version => String(version.content || '').length > 500)
    : []
  const latestCandidate = latestCandidateVersion(candidateVersions)
  const candidateContent = String(latestCandidate?.content || '')
  const rawContentLength = candidateContent.length
  const effectiveCjkCharCount = countCjkChars(candidateContent)
  const reportedWordCount = Number(rawContentLength || effectiveCjkCharCount || chapter?.wordCount || 0)
  const wordTarget = buildLiveChapterWordTarget()
  const targetRange = { min: wordTarget.min, max: wordTarget.max }
  const wordPolicy = wordCountPolicy(reportedWordCount, wordTarget)
  const titleQuality = getChapterTitleQuality(chapter?.title || '', {
    chapterNum,
    content: candidateContent,
    titleSource: 'metadata',
    fallbackUsed: false
  })
  const beatPlanQuality = analyzeBeatPlanQualityForReport(beat?.content || '')
  const beatPlanPromptDiagnostics = page ? await readBeatPlanDiagnostics(page, chapterNum) : null
  const summarizedBeatPlanDiagnostics = summarizeBeatPlanPromptDiagnostics(beatPlanPromptDiagnostics)
  const writerHumanityContextDiagnostics = page ? await readWriterHumanityContextDiagnostics(page, chapterNum) : null
  const sampleCardInjected = writerHumanityContextDiagnostics?.sampleCardInjected === true || existingReport.sampleCardInjected === true
  const sampleSource = writerHumanityContextDiagnostics?.sampleCardInjected === true
    ? writerHumanityContextDiagnostics
    : existingReport
  upsertChapterReport({
    chapterNum,
    title: chapter?.title || '',
    wordCount: reportedWordCount,
    cjkCharCount: effectiveCjkCharCount,
    rawContentLength,
    targetRange,
    wordTarget,
    wordCountPolicy: wordPolicy,
    wordCountPolicyStatus: wordPolicy.status,
    wordCountPolicyBasis: candidateContent ? 'latest_candidate_content' : 'chapter.wordCount',
    titleQuality,
    storyBlockId: beat?.storyBlockId || chapter?.storyBlockId || '',
    blockStageId: beat?.blockStageId || '',
    blockStageSnapshot: beat?.blockStageSnapshot || null,
    beatPlanQuality,
    beatPlanSource: beat?.beatPlanSource || summarizedBeatPlanDiagnostics.beatPlanSource || '',
    aiAttempts: summarizedBeatPlanDiagnostics.aiAttempts,
    derivedFromStoryBlock: Boolean(beat?.derivedFromStoryBlock || summarizedBeatPlanDiagnostics.derivedFromStoryBlock),
    derivedReason: beat?.derivedReason || summarizedBeatPlanDiagnostics.derivedReason || '',
    stageSnapshotFields: summarizedBeatPlanDiagnostics.stageSnapshotFields,
    whetherAllowedToContinue: summarizedBeatPlanDiagnostics.whetherAllowedToContinue,
    writerContextDiagnostics: writerHumanityContextDiagnostics,
    companionVoiceCardsInjected: writerHumanityContextDiagnostics?.companionVoiceCardsInjected ?? null,
    companionVoiceCardNames: writerHumanityContextDiagnostics?.companionVoiceCardNames || [],
    companionVoiceCardsLength: writerHumanityContextDiagnostics?.companionVoiceCardsLength || 0,
    sampleCardInjected,
    sampleCardId: sampleCardInjected ? (sampleSource.sampleCardId || '') : '',
    sampleCardTitle: sampleCardInjected ? (sampleSource.sampleCardTitle || '') : '',
    sampleCardType: sampleCardInjected ? (sampleSource.sampleCardType || '') : '',
    sampleInjectionReason: sampleCardInjected ? (sampleSource.sampleInjectionReason || '') : '',
    microDemoChars: sampleCardInjected ? (sampleSource.microDemoChars || 0) : 0,
    sourceFieldsStripped: sampleSource.sourceFieldsStripped ?? true,
    sampleLeakageDetected: Boolean(sampleSource.sampleLeakageDetected),
    outlineFromActiveStoryBlock: Boolean(beat?.storyBlockId),
    draftReadSnapshotBoundary: Boolean(beat?.blockStageSnapshot),
    draftGenerated: candidateVersions.length > 0,
    candidateVersionCount: candidateVersions.length,
    finalized: chapter?.status === 'final',
    progressStage: stage,
    taskProviders: report.modelBinding.taskProviders
  })
  const titleWarningCode = `chapter_title_invalid:${chapterNum}`
  const titleSoftWarningCode = `chapter_title_warning:${chapterNum}`
  report.qualityWarnings = report.qualityWarnings.filter(item => item.code !== titleWarningCode)
  report.qualityWarnings = report.qualityWarnings.filter(item => item.code !== titleSoftWarningCode)
  if (!titleQuality.titleValid) {
    report.qualityWarnings.push({
      code: titleWarningCode,
      message: `第 ${chapterNum} 章标题《${chapter?.title || ''}》不合法：${titleQuality.titleInvalidReason || '非法标题'}。`
    })
  } else if (titleQuality.status === 'warning') {
    report.qualityWarnings.push({
      code: titleSoftWarningCode,
      message: `第 ${chapterNum} 章标题《${chapter?.title || ''}》偏弱：${titleQuality.reason || 'weak_title'}。`
    })
  }
  const wordWarningCode = `chapter_word_count_policy:${chapterNum}`
  report.qualityWarnings = report.qualityWarnings.filter(item => item.code !== wordWarningCode)
  if (wordPolicy.status !== 'within_target') {
    report.qualityWarnings.push({
      code: wordWarningCode,
      message: `第 ${chapterNum} 章字数策略=${wordPolicy.status}，wordCount=${reportedWordCount}，CJK=${effectiveCjkCharCount}，硬下限=${wordPolicy.hardMin}，软线=${wordPolicy.softMin}，目标=${wordPolicy.targetRange.min}-${wordPolicy.targetRange.max}。`
    })
  }
  report.acceptance.completedChapters = report.chapterReports.filter(item => item.finalized).length
  writeReport()
}

function throwIfChapterTitleInvalid(chapterNum, stage = 'chapter_title_quality_gate') {
  const entry = report.chapterReports.find(item => Number(item.chapterNum) === Number(chapterNum))
  if (!entry?.titleQuality || entry.titleQuality.titleValid !== false) return
  const error = new Error(`chapter_title_invalid: 第 ${entry.chapterNum} 章标题《${entry.title || ''}》不合法，未继续小跑。`)
  error.code = 'chapter_title_invalid'
  error.liveDiagnostics = {
    stage,
    chapterNum: entry.chapterNum,
    title: entry.title || '',
    titleInvalidReason: entry.titleQuality.titleInvalidReason || entry.titleQuality.reason || '非法标题',
    titleQuality: entry.titleQuality,
    message: '章节标题命中硬门：纯英文/内部字段/JSON 或代码残片不得进入最终标题。'
  }
  report.blocker = {
    blocked: true,
    stage,
    code: 'chapter_title_invalid',
    chapterNum: entry.chapterNum,
    title: entry.title || '',
    titleInvalidReason: error.liveDiagnostics.titleInvalidReason,
    message: error.message
  }
  report.acceptance.passed = false
  report.acceptance.reason = error.message
  markChapterFlowEvent(chapterNum, 'chapter_title_invalid', error.liveDiagnostics)
  writeReport()
  throw error
}

function throwIfChapterBelowHardMin(chapterNum, stage = 'word_count_quality_gate', details = {}) {
  const entry = report.chapterReports.find(item => Number(item.chapterNum) === Number(chapterNum))
  if (!entry?.wordCountPolicy || entry.wordCountPolicy.hardPass !== false) return
  const wordTarget = entry.wordTarget || entry.wordCountPolicy.wordTarget || buildLiveChapterWordTarget()
  const hardFailWordCountChapters = [{
    chapterNum: entry.chapterNum,
    title: entry.title || '',
    wordCount: entry.wordCount || 0,
    cjkCharCount: entry.cjkCharCount || 0,
    status: entry.wordCountPolicy.status,
    hardMin: entry.wordCountPolicy.hardMin,
    softMin: entry.wordCountPolicy.softMin,
    targetRange: entry.wordCountPolicy.targetRange
  }]
  report.hardFailWordCountChapters = hardFailWordCountChapters
  const error = new Error(`chapter_below_hard_min: 第 ${entry.chapterNum} 章低于硬下限，未进入定稿。`)
  error.code = 'chapter_below_hard_min'
  error.liveDiagnostics = {
    stage,
    hardFailWordCountChapters,
    appHardMin: entry.wordCountPolicy.appHardMin || entry.wordCountPolicy.hardMin,
    liveHardMin: entry.wordCountPolicy.liveHardMin || entry.wordCountPolicy.hardMin,
    wordTarget,
    candidateWordCount: entry.wordCount || 0,
    modalText: details.modalText || '',
    regenerateAttempted: Boolean(details.regenerateAttempted ?? entry.flowEvents?.below_hard_min_auto_regenerate_started),
    regenerateSucceeded: Boolean(details.regenerateSucceeded ?? entry.flowEvents?.below_hard_min_auto_regenerate_succeeded),
    finalizeApiEvents: details.finalizeApiEvents || [],
    message: '正文低于硬下限，请扩写或重新生成',
    ...details
  }
  markChapterFlowEvent(chapterNum, 'chapter_below_hard_min', error.liveDiagnostics)
  report.blocker = {
    blocked: true,
    stage: 'word_count_quality_gate',
    code: 'chapter_below_hard_min',
    chapterNum: entry.chapterNum,
    message: `第 ${entry.chapterNum} 章低于硬下限，未进入定稿。`,
    hardFailWordCountChapters,
    appHardMin: error.liveDiagnostics.appHardMin,
    liveHardMin: error.liveDiagnostics.liveHardMin,
    wordTarget,
    candidateWordCount: error.liveDiagnostics.candidateWordCount,
    modalText: error.liveDiagnostics.modalText,
    regenerateAttempted: error.liveDiagnostics.regenerateAttempted,
    regenerateSucceeded: error.liveDiagnostics.regenerateSucceeded,
    shortDraftStrategy: error.liveDiagnostics.shortDraftStrategy || '',
    originalWordCount: error.liveDiagnostics.originalWordCount || 0,
    expandedWordCount: error.liveDiagnostics.expandedWordCount || 0,
    finalCandidateWordCount: error.liveDiagnostics.finalCandidateWordCount || error.liveDiagnostics.candidateWordCount || 0,
    expansionAccepted: Boolean(error.liveDiagnostics.expansionAccepted),
    expansionRejectedReason: error.liveDiagnostics.expansionRejectedReason || '',
    factDriftCheck: error.liveDiagnostics.factDriftCheck || null,
    endingPreserved: error.liveDiagnostics.endingPreserved || null
  }
  report.acceptance.passed = false
  report.acceptance.reason = report.blocker.message
  writeReport()
  throw error
}

async function throwIfBelowHardMinModalVisible(page, chapterNum, stage = 'word_count_quality_gate', details = {}) {
  const modalText = await findBelowHardMinModalText(page)
  if (!modalText) return false
  const staleResolution = await dismissStaleBelowHardMinModalIfSafe(page, chapterNum, stage, details)
  if (staleResolution.modalStale && staleResolution.closeBelowHardMinModalSucceeded) {
    return false
  }
  await recordChapterDraftProgress(page, chapterNum, stage)
  const finalizeDiagnostics = await collectFinalizationDiagnostics(page, chapterNum).catch(() => null)
  const entry = report.chapterReports.find(item => Number(item.chapterNum) === Number(chapterNum))
  const versionDiagnostics = await finalizationVersionDiagnostics(page, chapterNum, modalText).catch(() => null)
  if (versionDiagnostics?.selectedVersionStale && versionDiagnostics?.latestCandidateHardPass) {
    throwSelectedVersionStale(chapterNum, {
      ...(finalizeDiagnostics || {}),
      ...(versionDiagnostics || {}),
      ...details,
      modalText,
      belowHardMinModal: true
    })
  }
  if (entry?.wordCountPolicy?.hardPass === false) {
    throwIfChapterBelowHardMin(chapterNum, stage, {
      ...(finalizeDiagnostics || {}),
      ...(versionDiagnostics || {}),
      ...details,
      belowHardMinModal: true,
      modalText,
      blockerSource: versionDiagnostics?.blockerSource || 'current_candidate',
      regenerateAttempted: Boolean(details.regenerateAttempted ?? entry.flowEvents?.below_hard_min_auto_regenerate_started),
      regenerateSucceeded: Boolean(details.regenerateSucceeded ?? entry.flowEvents?.below_hard_min_auto_regenerate_succeeded),
      finalizeApiEvents: finalizeDiagnostics?.finalizeApiEvents || []
    })
  }
  return false
}

async function ensureDraftAboveHardMinOrRegenerate(page, chapterNum) {
  await recordChapterDraftProgress(page, chapterNum, 'draft_generated')
  let entry = report.chapterReports.find(item => Number(item.chapterNum) === Number(chapterNum))
  if (!entry?.wordCountPolicy || entry.wordCountPolicy.hardPass !== false) return entry

  const chapterId = await currentChapterId(chapterNum)
  const originalVersions = await api(`/projects/${report.project.id}/chapters/${chapterId}/versions`).catch(() => [])
  const originalFingerprints = candidateVersionFingerprints(originalVersions)
  const originalFingerprint = latestCandidateFingerprint(originalVersions)
  const originalVersionIds = originalFingerprints.map(item => item.id).filter(Boolean)
  const originalContentHashes = originalFingerprints.map(item => item.contentHash).filter(Boolean)
  const originalVersionCount = Array.isArray(originalVersions) ? originalVersions.length : 0
  const originalWordCount = entry.wordCount || originalFingerprint?.wordCount || 0
  const originalContentHash = originalFingerprint?.contentHash || ''
  const originalCandidate = latestCandidateVersion(originalVersions)
  const beatPlanRecord = await api(`/projects/${report.project.id}/chapter-beat-plan/${chapterNum}`).catch(() => null)
  const beatPlanExpansionReadiness = isCompleteBeatPlanForShortDraftExpansion(beatPlanRecord)
  let shortDraftExpansionDiagnostics = {
    shortDraftStrategy: '',
    originalWordCount,
    expandedWordCount: 0,
    finalCandidateWordCount: originalWordCount,
    expansionAccepted: false,
    expansionRejectedReason: '',
    factDriftCheck: null,
    endingPreserved: null
  }

  const shortDraftExpansionEligible = Boolean(
    originalWordCount >= SHORT_DRAFT_EXPANSION_MIN &&
    originalWordCount < 4000 &&
    originalWordCount < SHORT_DRAFT_EXPANSION_MAX + 1 &&
    originalCandidate?.content &&
    beatPlanExpansionReadiness.complete
  )

  if (shortDraftExpansionEligible) {
    markChapterFlowEvent(chapterNum, 'below_hard_min_expand_short_draft_started', {
      shortDraftStrategy: 'expand_existing',
      originalWordCount,
      wordCountPolicy: entry.wordCountPolicy,
      originalVersionCount,
      originalVersionIds,
      originalContentHash,
      originalContentHashes,
      originalVersionFingerprints: originalFingerprints.map(summarizeVersionFingerprint),
      beatPlanExpansionReadiness
    })
    try {
      const expansion = await expandShortDraftCandidate({
        page,
        chapterNum,
        chapterId,
        originalCandidate,
        beatPlanRecord,
        wordTarget: entry.wordTarget || buildLiveChapterWordTarget()
      })
      shortDraftExpansionDiagnostics = {
        ...shortDraftExpansionDiagnostics,
        ...expansion.diagnostics
      }
      markChapterFlowEvent(
        chapterNum,
        expansion.accepted ? 'below_hard_min_expand_short_draft_done' : 'below_hard_min_expand_short_draft_rejected',
        {
          ...shortDraftExpansionDiagnostics,
          originalVersionCount,
          originalVersionIds,
          originalContentHash,
          originalContentHashes,
          savedVersionId: expansion.savedVersion?.id || ''
        }
      )
      if (expansion.accepted) {
        await recordChapterDraftProgress(page, chapterNum, 'below_hard_min_expand_short_draft_done')
        entry = report.chapterReports.find(item => Number(item.chapterNum) === Number(chapterNum))
        shortDraftExpansionDiagnostics.finalCandidateWordCount = entry?.wordCount || shortDraftExpansionDiagnostics.expandedWordCount || 0
        if (entry?.wordCountPolicy?.hardPass !== false) {
          markChapterFlowEvent(chapterNum, 'below_hard_min_expand_short_draft_succeeded', {
            ...shortDraftExpansionDiagnostics,
            wordCount: entry?.wordCount || 0,
            wordCountPolicy: entry?.wordCountPolicy || null,
            regenerateAttempted: false,
            regenerateSucceeded: false
          })
          return entry
        }
        shortDraftExpansionDiagnostics = {
          ...shortDraftExpansionDiagnostics,
          expansionAccepted: false,
          expansionRejectedReason: shortDraftExpansionDiagnostics.expansionRejectedReason || 'saved_expansion_still_below_hard_min'
        }
      }
    } catch (error) {
      shortDraftExpansionDiagnostics = {
        ...shortDraftExpansionDiagnostics,
        shortDraftStrategy: 'expand_existing',
        expansionAccepted: false,
        expansionRejectedReason: `expand_short_draft_failed: ${error.message}`,
        finalCandidateWordCount: originalWordCount
      }
      markChapterFlowEvent(chapterNum, 'below_hard_min_expand_short_draft_failed', {
        ...shortDraftExpansionDiagnostics,
        originalVersionCount,
        originalVersionIds,
        originalContentHash,
        originalContentHashes,
        beatPlanExpansionReadiness
      })
    }
    throwIfChapterBelowHardMin(chapterNum, 'below_hard_min_expand_short_draft_failed', {
      ...shortDraftExpansionDiagnostics,
      shortDraftStrategy: 'expand_existing',
      regenerateAttempted: false,
      regenerateSucceeded: false,
      originalVersionCount,
      originalVersionIds,
      originalWordCount,
      originalContentHash,
      originalContentHashes,
      finalCandidateWordCount: shortDraftExpansionDiagnostics.finalCandidateWordCount || originalWordCount,
      beatPlanExpansionReadiness
    })
  } else {
    shortDraftExpansionDiagnostics = {
      ...shortDraftExpansionDiagnostics,
      shortDraftStrategy: 'full_regenerate',
      expansionRejectedReason: beatPlanExpansionReadiness.complete
        ? 'short_draft_not_in_expand_range'
        : 'beat_plan_incomplete_for_expansion',
      beatPlanExpansionReadiness
    }
  }

  markChapterFlowEvent(chapterNum, 'below_hard_min_auto_regenerate_started', {
    ...shortDraftExpansionDiagnostics,
    shortDraftStrategy: 'full_regenerate',
    wordCount: entry.wordCount || 0,
    wordCountPolicy: entry.wordCountPolicy,
    regenerateAttempted: true,
    originalVersionCount,
    originalVersionIds,
    originalWordCount,
    originalContentHash,
    originalContentHashes,
    originalVersionFingerprints: originalFingerprints.map(summarizeVersionFingerprint)
  })

  await dismissAppDialogs(page)
  let draftEntry
  let regeneratedVersions = []
  try {
    draftEntry = await clickDraftRegenerationEntry(page, chapterNum, { chapterId, clickTimeoutMs: 60000 })
    await clickStartGenerationIfPrompted(page, chapterNum)
    regeneratedVersions = await waitForGeneratedChapterVersion(page, chapterNum, {
      expectNewVersion: true,
      minVersionCountAfter: originalVersionCount + 1,
      previousVersionIds: originalVersionIds,
      previousContentHashes: originalContentHashes,
      previousVersionFingerprints: originalFingerprints,
      draftGenerationStartedAt: draftEntry.draftGenerationStartedAt,
      draftGenerationEntryLabel: draftEntry.draftGenerationEntryLabel,
      generationEntryLabel: draftEntry.draftGenerationEntryLabel,
      generationEntryAttempts: 1,
      generationEntryDiagnostics: {
        ...(draftEntry.diagnostics || {}),
        belowHardMinRecovery: true,
        previousWordCount: entry.wordCount || 0,
        previousWordCountPolicy: entry.wordCountPolicy,
        originalVersionCount,
        originalVersionIds,
        originalWordCount,
        originalContentHash,
        originalContentHashes
      }
    })
  } catch (error) {
    const diagnostics = await collectDraftGenerationWaitDiagnostics(page, chapterNum, chapterId, {
      draftGenerationStartedAt: draftEntry?.draftGenerationStartedAt || '',
      draftGenerationEntryLabel: draftEntry?.draftGenerationEntryLabel || '',
      generationEntryLabel: draftEntry?.draftGenerationEntryLabel || '',
      generationEntryAttempts: draftEntry ? 1 : 0,
      generationEntryDiagnostics: draftEntry?.diagnostics || null,
      draftGenerationEntryDiagnostics: draftEntry?.diagnostics || null,
      startedAtMs: draftEntry?.draftGenerationStartedAt ? Date.parse(draftEntry.draftGenerationStartedAt) : Date.now(),
      versionCountBefore: originalVersionCount,
      expectNewVersion: true,
      minVersionCountAfter: originalVersionCount + 1,
      previousVersionIds: originalVersionIds,
      previousContentHashes: originalContentHashes,
      previousVersionFingerprints: originalFingerprints
    }).catch(() => null)
    const regenerationFailureCode = ['draft_regeneration_not_started', 'draft_regeneration_no_new_candidate', 'draft_regeneration_entry_not_found'].includes(error.code)
      ? error.code
      : (diagnostics ? classifyDraftGenerationFailure(diagnostics) : (error.code || 'draft_regeneration_no_new_candidate'))
    markChapterFlowEvent(chapterNum, 'below_hard_min_auto_regenerate_failed', {
      ...shortDraftExpansionDiagnostics,
      shortDraftStrategy: 'full_regenerate',
      message: error.message,
      code: regenerationFailureCode,
      regenerationFailureCode,
      regenerateAttempted: true,
      regenerateStartedAt: draftEntry?.draftGenerationStartedAt || '',
      regenerateEntryLabel: draftEntry?.draftGenerationEntryLabel || '',
      previousWordCount: entry.wordCount || 0,
      previousWordCountPolicy: entry.wordCountPolicy,
      originalVersionCount,
      originalVersionIds,
      originalWordCount,
      originalContentHash,
      originalContentHashes,
      newVersionCount: diagnostics?.versionCountAfter ?? originalVersionCount,
      newVersionIds: diagnostics?.versionIds || originalVersionIds,
      newContentHash: diagnostics?.newVersionCandidate?.contentHash || originalContentHash,
      newWordCount: diagnostics?.newVersionCandidate?.wordCount || originalWordCount,
      streamRequestCount: diagnostics?.streamRequestCount || diagnostics?.draftStreamRequestCount || 0,
      streamResponseCount: diagnostics?.streamResponseCount || diagnostics?.draftStreamResponseCount || 0,
      aiProxyRequest: diagnostics?.lastAiProxyRequestAt || '',
      aiProxyResponse: diagnostics?.lastAiProxyResponseAt || '',
      diagnostics
    })
    await recordChapterDraftProgress(page, chapterNum, 'below_hard_min_auto_regenerate_failed')
    if (['draft_regeneration_not_started', 'draft_regeneration_no_new_candidate', 'draft_regeneration_entry_not_found'].includes(regenerationFailureCode)) {
      report.blocker = {
        blocked: true,
        stage: 'draft_regeneration',
        code: regenerationFailureCode,
        chapterNum,
        message: regenerationFailureCode === 'draft_regeneration_no_new_candidate'
          ? `第 ${chapterNum} 章低字数自动重生未产生新候选。`
          : `第 ${chapterNum} 章低字数自动重生未启动。`,
        ...shortDraftExpansionDiagnostics,
        shortDraftStrategy: 'full_regenerate',
        regenerateAttempted: true,
        regenerateStartedAt: draftEntry?.draftGenerationStartedAt || '',
        regenerateEntryLabel: draftEntry?.draftGenerationEntryLabel || '',
        originalVersionCount,
        newVersionCount: diagnostics?.versionCountAfter ?? originalVersionCount,
        originalVersionIds,
        newVersionIds: diagnostics?.versionIds || originalVersionIds,
        originalWordCount,
        newWordCount: diagnostics?.newVersionCandidate?.wordCount || originalWordCount,
        originalContentHash,
        newContentHash: diagnostics?.newVersionCandidate?.contentHash || originalContentHash,
        streamRequestCount: diagnostics?.streamRequestCount || diagnostics?.draftStreamRequestCount || 0,
        streamResponseCount: diagnostics?.streamResponseCount || diagnostics?.draftStreamResponseCount || 0,
        aiProxyRequest: diagnostics?.lastAiProxyRequestAt || '',
        aiProxyResponse: diagnostics?.lastAiProxyResponseAt || '',
        diagnostics
      }
      report.acceptance.passed = false
      report.acceptance.reason = report.blocker.message
      writeReport()
      error.code = regenerationFailureCode
      error.liveDiagnostics = report.blocker
      throw error
    }
    throwIfChapterBelowHardMin(chapterNum, 'below_hard_min_auto_regenerate_failed', {
      ...shortDraftExpansionDiagnostics,
      shortDraftStrategy: 'full_regenerate',
      regenerateAttempted: true,
      regenerateSucceeded: false,
      regenerationFailureCode,
      originalVersionCount,
      originalVersionIds,
      originalWordCount,
      originalContentHash,
      originalContentHashes,
      newVersionCount: diagnostics?.versionCountAfter ?? originalVersionCount,
      newVersionIds: diagnostics?.versionIds || originalVersionIds,
      finalCandidateWordCount: diagnostics?.newVersionCandidate?.wordCount || originalWordCount
    })
    throw error
  }

  await recordChapterDraftProgress(page, chapterNum, 'below_hard_min_auto_regenerate_done')
  entry = report.chapterReports.find(item => Number(item.chapterNum) === Number(chapterNum))
  const newFingerprints = candidateVersionFingerprints(regeneratedVersions)
  const regenerationFreshness = hasNewGeneratedVersionCandidate(regeneratedVersions, {
    expectNewVersion: true,
    minVersionCountAfter: originalVersionCount + 1,
    previousVersionIds: originalVersionIds,
    previousContentHashes: originalContentHashes,
    previousVersionFingerprints: originalFingerprints,
    draftGenerationStartedAt: draftEntry?.draftGenerationStartedAt || ''
  })
  const newFingerprint = regenerationFreshness.candidate || latestCandidateFingerprint(regeneratedVersions)
  const newVersionIds = newFingerprints.map(item => item.id).filter(Boolean)
  const newVersionCount = Array.isArray(regeneratedVersions) ? regeneratedVersions.length : 0
  const newWordCount = entry?.wordCount || newFingerprint?.wordCount || 0
  const newContentHash = newFingerprint?.contentHash || ''
  const regenerateStartedAtMs = draftEntry?.draftGenerationStartedAt ? Date.parse(draftEntry.draftGenerationStartedAt) : 0
  const aiTiming = latestAiProxyTimingSince(regenerateStartedAtMs)
  if (entry?.wordCountPolicy?.hardPass !== false) {
    markChapterFlowEvent(chapterNum, 'below_hard_min_auto_regenerate_succeeded', {
      ...shortDraftExpansionDiagnostics,
      shortDraftStrategy: 'full_regenerate',
      wordCount: entry?.wordCount || 0,
      wordCountPolicy: entry?.wordCountPolicy || null,
      draftGenerationEntryLabel: draftEntry?.draftGenerationEntryLabel || '',
      regenerateAttempted: true,
      regenerateSucceeded: true,
      regenerateStartedAt: draftEntry?.draftGenerationStartedAt || '',
      regenerateEntryLabel: draftEntry?.draftGenerationEntryLabel || '',
      originalVersionCount,
      newVersionCount,
      originalVersionIds,
      newVersionIds,
      originalWordCount,
      newWordCount,
      finalCandidateWordCount: newWordCount,
      originalContentHash,
      newContentHash,
      originalContentHashes,
      newContentHashes: newFingerprints.map(item => item.contentHash),
      regenerationFreshnessReason: regenerationFreshness.reason,
      streamRequestCount: aiTiming.streamRequestCount,
      streamResponseCount: aiTiming.streamResponseCount,
      aiProxyRequest: aiTiming.lastAiProxyRequestAt,
      aiProxyResponse: aiTiming.lastAiProxyResponseAt
    })
    return entry
  }

  markChapterFlowEvent(chapterNum, 'below_hard_min_auto_regenerate_failed', {
    ...shortDraftExpansionDiagnostics,
    shortDraftStrategy: 'full_regenerate',
    wordCount: entry?.wordCount || 0,
    wordCountPolicy: entry?.wordCountPolicy || null,
    message: '自动重生后新候选仍低于硬下限',
    regenerateAttempted: true,
    regenerateSucceeded: false,
    regenerateStartedAt: draftEntry?.draftGenerationStartedAt || '',
    regenerateEntryLabel: draftEntry?.draftGenerationEntryLabel || '',
    regenerationFailureCode: 'chapter_below_hard_min',
    originalVersionCount,
    newVersionCount,
    originalVersionIds,
    newVersionIds,
    originalWordCount,
    newWordCount,
    finalCandidateWordCount: newWordCount,
    originalContentHash,
    newContentHash,
    originalContentHashes,
    newContentHashes: newFingerprints.map(item => item.contentHash),
    regenerationFreshnessReason: regenerationFreshness.reason,
    streamRequestCount: aiTiming.streamRequestCount,
    streamResponseCount: aiTiming.streamResponseCount,
    aiProxyRequest: aiTiming.lastAiProxyRequestAt,
    aiProxyResponse: aiTiming.lastAiProxyResponseAt
  })
  throwIfChapterBelowHardMin(chapterNum, 'below_hard_min_auto_regenerate_failed', {
    ...shortDraftExpansionDiagnostics,
    shortDraftStrategy: 'full_regenerate',
    regenerateAttempted: true,
    regenerateSucceeded: false,
    regenerateStartedAt: draftEntry?.draftGenerationStartedAt || '',
    regenerateEntryLabel: draftEntry?.draftGenerationEntryLabel || '',
    regenerationFailureCode: 'chapter_below_hard_min',
    originalVersionCount,
    newVersionCount,
    originalVersionIds,
    newVersionIds,
    originalWordCount,
    newWordCount,
    finalCandidateWordCount: newWordCount,
    originalContentHash,
    newContentHash,
    regenerationFreshnessReason: regenerationFreshness.reason,
    streamRequestCount: aiTiming.streamRequestCount,
    streamResponseCount: aiTiming.streamResponseCount,
    aiProxyRequest: aiTiming.lastAiProxyRequestAt,
    aiProxyResponse: aiTiming.lastAiProxyResponseAt
  })
  return entry
}

function versionCardSelector(versionId = '') {
  const escaped = String(versionId || '').replace(/\\/g, '\\\\').replace(/"/g, '\\"')
  return `[data-version-id="${escaped}"]`
}

async function clickUnsavedSwitchConfirmationIfPresent(page) {
  const dialogText = (await collectDialogAndMessageTexts(page)).join('\n')
  if (!/当前编辑尚未另存为版本/.test(dialogText)) return false
  const switchButton = exactButton(page, '不另存，直接切换').last()
  if (await switchButton.isVisible().catch(() => false)) {
    await switchButton.click({ timeout: 5000 }).catch(() => {})
    await page.waitForTimeout(500)
    return true
  }
  return false
}

async function clickFinalizeForLatestHardPassCandidate(page, chapterNum, preflight = null) {
  const diagnostics = preflight || await ensureLatestHardPassCandidateSelectedForFinalize(page, chapterNum)
  const versionId = diagnostics.latestCandidateVersionId || diagnostics.selectedVersionId
  if (!versionId) {
    const error = new Error(`selected_version_stale: 第 ${chapterNum} 章没有可定稿的过线候选。`)
    error.code = 'selected_version_stale'
    error.liveDiagnostics = diagnostics
    throw error
  }
  const card = page.locator(versionCardSelector(versionId)).first()
  await card.waitFor({ state: 'visible', timeout: 30000 })
  const finalizeButton = card.getByRole('button', { name: /^定稿$/ }).first()
  await finalizeButton.waitFor({ state: 'visible', timeout: 30000 })
  await waitFor(`latest hard-pass version finalize button enabled`, async () => finalizeButton.isEnabled(), 30000, 500)
  await finalizeButton.click({ timeout: 30000 })
  markChapterFlowEvent(chapterNum, 'finalize_clicked_latest_hard_pass_candidate', {
    selectedVersionId: diagnostics.selectedVersionId,
    selectedVersionWordCount: diagnostics.selectedVersionWordCount,
    selectedVersionHash: diagnostics.selectedVersionHash,
    latestCandidateVersionId: diagnostics.latestCandidateVersionId,
    latestCandidateWordCount: diagnostics.latestCandidateWordCount,
    latestCandidateHash: diagnostics.latestCandidateHash
  })
  return diagnostics
}

async function ensureLatestHardPassCandidateSelectedForFinalize(page, chapterNum) {
  await recordChapterDraftProgress(page, chapterNum, 'finalize_version_preflight')
  let diagnostics = await finalizationVersionDiagnostics(page, chapterNum)
  if (!diagnostics.latestCandidateVersionId || !diagnostics.latestCandidateHardPass) {
    throwIfChapterBelowHardMin(chapterNum, 'finalize_version_preflight', {
      ...diagnostics,
      blockerSource: 'current_candidate'
    })
  }
  if (diagnostics.selectedVersionId !== diagnostics.latestCandidateVersionId) {
    const targetCard = page.locator(versionCardSelector(diagnostics.latestCandidateVersionId)).first()
    if (!await targetCard.isVisible().catch(() => false)) {
      throwSelectedVersionStale(chapterNum, {
        ...diagnostics,
        selectedVersionSwitchAttempted: true,
        selectedVersionSwitchSucceeded: false,
        message: 'latest hard-pass version card not visible'
      })
    }
    await targetCard.click({ timeout: 10000 }).catch(async error => {
      await clickUnsavedSwitchConfirmationIfPresent(page)
      if (!await targetCard.isVisible().catch(() => false)) throw error
      await targetCard.click({ timeout: 10000 })
    })
    await clickUnsavedSwitchConfirmationIfPresent(page)
    await waitFor(`latest hard-pass version selected`, async () => {
      const selectedId = await selectedVersionIdFromPage(page)
      return selectedId === diagnostics.latestCandidateVersionId
    }, 30000, 500).catch(() => null)
    const afterSwitch = await finalizationVersionDiagnostics(page, chapterNum)
    diagnostics = {
      ...afterSwitch,
      selectedVersionSwitchAttempted: true,
      selectedVersionSwitchSucceeded: afterSwitch.selectedVersionId === afterSwitch.latestCandidateVersionId
    }
    if (diagnostics.selectedVersionId !== diagnostics.latestCandidateVersionId) {
      throwSelectedVersionStale(chapterNum, diagnostics)
    }
  } else {
    diagnostics.selectedVersionSwitchAttempted = false
    diagnostics.selectedVersionSwitchSucceeded = true
  }
  markChapterFlowEvent(chapterNum, 'finalize_version_preflight_passed', diagnostics)
  return diagnostics
}

async function runChapter(page, chapterNum) {
  markChapterFlowEvent(chapterNum, 'chapter_run_started')
  const writerEnteredAtMs = Date.now()
  await page.goto(`${FRONTEND}/writer/${report.project.id}/${chapterNum}`, { waitUntil: 'domcontentloaded' })
  await page.getByText(`第 ${chapterNum} 章`).first().waitFor({ state: 'visible', timeout: 60000 })
  markChapterFlowEvent(chapterNum, 'writer_page_visible')
  const writerContextDiagnostics = await waitForWriterContextReady(page, chapterNum, {
    timeoutMs: 180000,
    writerEnteredAtMs
  })
  const initialBeatPlan = await api(`/projects/${report.project.id}/chapter-beat-plan/${chapterNum}`).catch(() => null)
  markChapterFlowEvent(chapterNum, 'writer_context_ready', {
    contextReadyByEnabledEntry: Boolean(writerContextDiagnostics.contextReadyByEnabledEntry),
    contextLoadingVisible: Boolean(writerContextDiagnostics.contextLoadingVisible),
    enabledDraftEntryLabels: writerContextDiagnostics.enabledDraftEntryLabels || [],
    disabledDraftEntryLabels: writerContextDiagnostics.disabledDraftEntryLabels || [],
    contextApiFailures: writerContextDiagnostics.contextApiFailures || [],
    hasSavedBeatPlan: Boolean(initialBeatPlan?.content),
    chapterBeatPlanId: initialBeatPlan?.id || '',
    activeAction: writerContextDiagnostics.activeAction || [],
    visibleErrorMessages: writerContextDiagnostics.visibleErrorMessages || [],
    companionVoiceCardsInjected: writerContextDiagnostics.companionVoiceCardsInjected ?? null,
    companionVoiceCardNames: writerContextDiagnostics.companionVoiceCardNames || [],
    sampleCardInjected: writerContextDiagnostics.sampleCardInjected ?? false,
    sampleCardId: writerContextDiagnostics.sampleCardId || '',
    sampleCardTitle: writerContextDiagnostics.sampleCardTitle || '',
    sampleCardType: writerContextDiagnostics.sampleCardType || '',
    sampleInjectionReason: writerContextDiagnostics.sampleInjectionReason || '',
    microDemoChars: writerContextDiagnostics.microDemoChars || 0,
    sourceFieldsStripped: writerContextDiagnostics.sourceFieldsStripped ?? true,
    sampleLeakageDetected: writerContextDiagnostics.sampleLeakageDetected ?? false
  })
  let beatPlanStartedAt = ''
  let beatPlanEntryLabel = ''
  let beatPlanSavedAt = initialBeatPlan?.content ? new Date().toISOString() : ''
  let draftGenerationStartedAt = ''
  let draftGenerationEntryLabel = ''
  let draftEntryClickedAfterBeatPlan = false
  let generationEntryAttempts = 0
  let generationEntryDiagnostics = null
  let existingShortDraftRecovered = false

  if (!initialBeatPlan?.content) {
    const beatPlanEntry = await clickBeatPlanEntry(page, chapterNum, { clickTimeoutMs: 60000 })
    beatPlanStartedAt = beatPlanEntry.beatPlanStartedAt
    beatPlanEntryLabel = beatPlanEntry.beatPlanEntryLabel
    const savedBeatPlan = await waitForSavedBeatPlan(page, chapterNum)
    beatPlanSavedAt = savedBeatPlan.beatPlanSavedAt
    markChapterFlowEvent(chapterNum, 'new_beat_plan_saved', {
      hasSavedBeatPlan: true,
      beatPlanStartedAt,
      beatPlanEntryLabel,
      beatPlanSavedAt,
      chapterBeatPlanId: savedBeatPlan.beatPlanRecord?.id || '',
      beatPlanSource: savedBeatPlan.beatPlanRecord?.beatPlanSource || '',
      storyBlockId: savedBeatPlan.beatPlanRecord?.storyBlockId || '',
      blockStageId: savedBeatPlan.beatPlanRecord?.blockStageId || ''
    })
    await dismissAppDialogs(page)
    const draftEntry = await clickDraftEntry(page, chapterNum, { clickTimeoutMs: 60000 })
    draftGenerationStartedAt = draftEntry.draftGenerationStartedAt
    draftGenerationEntryLabel = draftEntry.draftGenerationEntryLabel
    draftEntryClickedAfterBeatPlan = true
    generationEntryAttempts = 1
    generationEntryDiagnostics = draftEntry.diagnostics
    markChapterFlowEvent(chapterNum, 'draft_entry_clicked_after_new_beat_plan', {
      hasSavedBeatPlan: true,
      draftGenerationStartedAt,
      draftGenerationEntryLabel,
      draftEntryClickedAfterBeatPlan,
      generationEntryAttempts,
      generationEntryDiagnostics
    })
  } else {
    markChapterFlowEvent(chapterNum, 'existing_beat_plan_detected', {
      hasSavedBeatPlan: true,
      chapterBeatPlanId: initialBeatPlan.id || '',
      beatPlanSource: initialBeatPlan.beatPlanSource || '',
      storyBlockId: initialBeatPlan.storyBlockId || '',
      blockStageId: initialBeatPlan.blockStageId || '',
      hasBlockStageSnapshot: Boolean(initialBeatPlan.blockStageSnapshot),
      contentLength: String(initialBeatPlan.content || '').length
    })
    await recordChapterDraftProgress(page, chapterNum, 'existing_candidate_preflight')
    const existingEntry = report.chapterReports.find(item => Number(item.chapterNum) === Number(chapterNum))
    if (existingEntry?.candidateVersionCount > 0 && existingEntry?.wordCountPolicy?.hardPass === false) {
      const recoveredEntry = await ensureDraftAboveHardMinOrRegenerate(page, chapterNum)
      if (recoveredEntry?.wordCountPolicy?.hardPass !== false) {
        existingShortDraftRecovered = true
        draftGenerationStartedAt = new Date().toISOString()
        draftGenerationEntryLabel = 'existing_short_draft_recovered'
        generationEntryAttempts = 0
        generationEntryDiagnostics = {
          existingCandidatePreflight: true,
          recoveredWordCount: recoveredEntry?.wordCount || 0,
          shortDraftStrategy: recoveredEntry?.flowEvents?.below_hard_min_expand_short_draft_succeeded?.shortDraftStrategy || 'expand_existing'
        }
        markChapterFlowEvent(chapterNum, 'existing_short_draft_recovered', {
          hasSavedBeatPlan: true,
          previousWordCount: existingEntry.wordCount || 0,
          recoveredWordCount: recoveredEntry?.wordCount || 0,
          wordCountPolicy: recoveredEntry?.wordCountPolicy || null,
          generationEntryDiagnostics
        })
      }
    }
    if (!existingShortDraftRecovered) {
      const draftEntry = await clickDraftEntry(page, chapterNum, { clickTimeoutMs: 60000 })
      draftGenerationStartedAt = draftEntry.draftGenerationStartedAt
      draftGenerationEntryLabel = draftEntry.draftGenerationEntryLabel
      draftEntryClickedAfterBeatPlan = true
      generationEntryAttempts = 1
      generationEntryDiagnostics = draftEntry.diagnostics
      markChapterFlowEvent(chapterNum, 'draft_entry_clicked_after_existing_beat_plan', {
        hasSavedBeatPlan: true,
        draftGenerationStartedAt,
        draftGenerationEntryLabel,
        draftEntryClickedAfterBeatPlan,
        generationEntryAttempts,
        generationEntryDiagnostics
      })
    }
  }
  if (!existingShortDraftRecovered) {
    await clickStartGenerationIfPrompted(page, chapterNum)
    markChapterFlowEvent(chapterNum, 'draft_generation_wait_started', {
      hasSavedBeatPlan: true,
      beatPlanStartedAt,
      beatPlanEntryLabel,
      beatPlanSavedAt,
      draftGenerationStartedAt,
      draftGenerationEntryLabel,
      draftEntryClickedAfterBeatPlan,
      generationEntryAttempts,
    })
    try {
      await waitForGeneratedChapterVersion(page, chapterNum, {
        beatPlanStartedAt,
        beatPlanEntryLabel,
        beatPlanSavedAt,
        draftGenerationStartedAt,
        draftGenerationEntryLabel,
        draftEntryClickedAfterBeatPlan,
        generationEntryLabel: draftGenerationEntryLabel,
        generationEntryAttempts,
        generationEntryDiagnostics: {
          ...writerContextDiagnostics,
          ...(generationEntryDiagnostics || {}),
          writerContext: writerContextDiagnostics
        }
      })
      await ensureDraftAboveHardMinOrRegenerate(page, chapterNum)
    } catch (error) {
      error.liveDiagnostics ||= { page: await collectVisibleDiagnostics(page) }
      throw error
    }
  } else {
    markChapterFlowEvent(chapterNum, 'draft_generation_wait_skipped_after_existing_short_draft_recovered', {
      hasSavedBeatPlan: true,
      draftGenerationStartedAt,
      draftGenerationEntryLabel,
      generationEntryDiagnostics
    })
  }

  await dismissAppDialogs(page)
  if (await exactButton(page, '生成章名').last().isEnabled().catch(() => false)) {
    markChapterFlowEvent(chapterNum, 'title_generation_started')
    try {
      await clickButton(page, '生成章名')
    } catch (error) {
      markChapterFlowEvent(chapterNum, 'title_generation_failed', { message: error.message })
      error.liveDiagnostics = {
        stage: `chapter_${chapterNum}_title_generation_click`,
        page: await collectVisibleDiagnostics(page),
        masks: await page.locator('.n-modal-mask').count().catch(() => 0),
        dialogs: await page.locator('.n-dialog, .n-modal, .n-message, .n-notification')
          .evaluateAll(nodes => nodes.map(node => node.innerText || node.textContent || '').filter(Boolean))
          .catch(() => [])
      }
      throw error
    }
    const titleGenerated = await waitFor(`chapter ${chapterNum} title generated`, async () => {
      const chapter = await findChapter(chapterNum)
      return chapter && chapter.title && !/^第\s*\d+\s*章$/.test(chapter.title)
    }, 120000, 3000).catch(() => null)
    if (titleGenerated) markChapterFlowEvent(chapterNum, 'title_generation_done')
    else markChapterFlowEvent(chapterNum, 'title_generation_failed', { message: 'title generation did not produce a non-default title before timeout' })
  }
  await recordChapterDraftProgress(page, chapterNum, 'title_quality_pre_audit')
  throwIfChapterTitleInvalid(chapterNum, 'title_quality_pre_audit')

  markChapterFlowEvent(chapterNum, 'audit_click_started')
  try {
    await clickButton(page, '本章审稿', 60000).catch(async () => clickButton(page, '本章审稿（只读）', 60000))
    markChapterFlowEvent(chapterNum, 'audit_started')
  } catch (error) {
    markChapterFlowEvent(chapterNum, 'audit_failed', { code: 'audit_not_started', message: error.message })
    error.code = 'audit_not_started'
    error.liveDiagnostics = await collectPostDraftDiagnostics(page, chapterNum, 'audit_not_started')
    throw error
  }
  try {
    await page.locator('.audit-report-modal, .n-modal').last().waitFor({ state: 'visible', timeout: 180000 })
    const auditSummary = await collectAuditModalSummary(page)
    markChapterFlowEvent(chapterNum, 'audit_modal_visible', auditSummary)
    await waitFor(`chapter ${chapterNum} audit done`, async () => {
      const summary = await collectAuditModalSummary(page)
      return summary.audit_modal_visible
    }, 180000, 3000)
    markChapterFlowEvent(chapterNum, 'audit_done', await collectAuditModalSummary(page))
  } catch (error) {
    const modalVisible = await page.locator('.audit-report-modal, .n-modal').last().isVisible().catch(() => false)
    const code = modalVisible ? 'audit_timed_out' : 'audit_modal_blocked'
    markChapterFlowEvent(chapterNum, 'audit_failed', { code, message: error.message })
    error.code = code
    error.liveDiagnostics = await collectPostDraftDiagnostics(page, chapterNum, code)
    throw error
  }
  await dismissAppDialogs(page)
  await page.waitForTimeout(1000)

  let finalizeVersionPreflight = await ensureLatestHardPassCandidateSelectedForFinalize(page, chapterNum)
  await dismissStaleBelowHardMinModalIfSafe(page, chapterNum, 'before_finalize_click', finalizeVersionPreflight)
  markChapterFlowEvent(chapterNum, 'finalize_click_started', finalizeVersionPreflight)
  try {
    await clickFinalizeForLatestHardPassCandidate(page, chapterNum, finalizeVersionPreflight)
  } catch (error) {
    const staleResolution = await dismissStaleBelowHardMinModalIfSafe(page, chapterNum, 'finalize_click_blocked_by_stale_modal', {
      ...finalizeVersionPreflight,
      originalError: error.message
    }).catch(err => { throw err })
    if (staleResolution.modalStale && staleResolution.closeBelowHardMinModalSucceeded) {
      finalizeVersionPreflight = await ensureLatestHardPassCandidateSelectedForFinalize(page, chapterNum)
      await clickFinalizeForLatestHardPassCandidate(page, chapterNum, finalizeVersionPreflight)
    } else if (await throwIfBelowHardMinModalVisible(page, chapterNum, 'finalize_below_hard_min_modal', {
      ...finalizeVersionPreflight,
      originalError: error.message
    }).catch(err => { throw err })) return
    else {
      markChapterFlowEvent(chapterNum, 'finalize_failed', { code: 'finalize_not_started', message: error.message, finalizeVersionPreflight })
      error.code = 'finalize_not_started'
      error.liveDiagnostics = await collectPostDraftDiagnostics(page, chapterNum, 'finalize_not_started')
      throw error
    }
  }
  const staleAfterFinalizeClick = await dismissStaleBelowHardMinModalIfSafe(page, chapterNum, 'after_finalize_click', finalizeVersionPreflight)
  if (staleAfterFinalizeClick.modalStale && staleAfterFinalizeClick.closeBelowHardMinModalSucceeded) {
    finalizeVersionPreflight = await ensureLatestHardPassCandidateSelectedForFinalize(page, chapterNum)
    markChapterFlowEvent(chapterNum, 'finalize_click_retry_after_stale_modal', finalizeVersionPreflight)
    await clickFinalizeForLatestHardPassCandidate(page, chapterNum, finalizeVersionPreflight)
  }
  await throwIfBelowHardMinModalVisible(page, chapterNum, 'finalize_below_hard_min_modal', finalizeVersionPreflight)
  const confirmVisible = await exactButton(page, '确认').last().isVisible().catch(() => false)
  if (confirmVisible) markChapterFlowEvent(chapterNum, 'finalize_dialog_visible')
  let finalizeConfirmClicked = false
  await clickButton(page, '确认', 60000).then(() => {
    finalizeConfirmClicked = true
    markChapterFlowEvent(chapterNum, 'finalize_confirm_clicked')
  }).catch(() => {})
  await throwIfBelowHardMinModalVisible(page, chapterNum, 'finalize_below_hard_min_modal')
  await clickFinalizeContinuationIfPrompted(page).catch(() => '')
  await throwIfBelowHardMinModalVisible(page, chapterNum, 'finalize_below_hard_min_modal')
  try {
    markChapterFlowEvent(chapterNum, 'finalize_started')
    await waitFor(`chapter ${chapterNum} finalized`, async () => {
      await clickFinalizeContinuationIfPrompted(page).catch(() => '')
      const chapter = await findChapter(chapterNum)
      return chapter?.status === 'final' || chapter?.finalVersionId
    }, FINALIZATION_TIMEOUT_MS, 5000)
    markChapterFlowEvent(chapterNum, 'finalize_done')
  } catch (error) {
    const finalizeDiagnostics = await collectFinalizationDiagnostics(page, chapterNum)
    if (finalizeDiagnostics.belowHardMinModal) {
      upsertChapterReport({ chapterNum, finalizeDiagnostics })
      if (finalizeDiagnostics.modalStale || finalizeDiagnostics.blockerSource === 'stale_modal') {
        throwStaleBelowHardMinModal(chapterNum, finalizeDiagnostics)
      }
      if (finalizeDiagnostics.selectedVersionStale || finalizeDiagnostics.blockerSource === 'selected_version_stale') {
        throwSelectedVersionStale(chapterNum, finalizeDiagnostics)
      }
      throwIfChapterBelowHardMin(chapterNum, 'finalize_below_hard_min_modal', finalizeDiagnostics)
    }
    const finalizeStarted = finalizeConfirmClicked || (finalizeDiagnostics.finalizeApiEvents || []).length > 0
    const failureCode = finalizeStarted ? 'finalize_timed_out' : 'finalize_not_started'
    upsertChapterReport({ chapterNum, finalizeDiagnostics })
    markChapterFlowEvent(chapterNum, 'finalize_failed', {
      code: failureCode,
      message: error.message,
      finalizeDiagnostics
    })
    error.code = failureCode
    error.liveDiagnostics = finalizeDiagnostics
    throw error
  }
  try {
    markChapterFlowEvent(chapterNum, 'postprocess_started')
    await waitFor(`chapter ${chapterNum} postprocess settled`, async () => {
      const chapter = await findChapter(chapterNum)
      return chapter && chapter.status === 'final'
    }, 300000, 5000)
    markChapterFlowEvent(chapterNum, 'postprocess_done')
  } catch (error) {
    markChapterFlowEvent(chapterNum, 'postprocess_failed', { code: 'finalize_postprocess_timed_out', message: error.message })
    error.code = 'finalize_postprocess_timed_out'
    error.liveDiagnostics = await collectPostDraftDiagnostics(page, chapterNum, 'finalize_postprocess_timed_out')
    throw error
  }
  await throwIfPostFinalizeAiProxyFailure(page, chapterNum)
  try {
    markChapterFlowEvent(chapterNum, 'story_block_review_started')
    await waitForStoryBlockReviewSaved(chapterNum)
    markChapterFlowEvent(chapterNum, 'story_block_review_done')
    await validateStoryBlockReviewContinuation(chapterNum)
  } catch (error) {
    markChapterFlowEvent(chapterNum, 'story_block_review_failed', { code: error.code || 'story_block_review_failed', message: error.message })
    error.liveDiagnostics = {
      ...(await collectStoryBlockReviewDiagnostics(page, chapterNum)),
      ...(error.liveDiagnostics || {})
    }
    throw error
  }
  const postFinalizeSettlement = await waitForPostFinalizeSettlement(page, chapterNum)
  await recordChapterDraftProgress(page, chapterNum, 'story_block_review_done')

  markChapterFlowEvent(chapterNum, 'settings_confirmation_started')
  try {
    await confirmPendingCanonFacts(page)
    postFinalizeSettlement.navigatedToSettingsAfterMarkerCleared = !await readFinalizationMarker(page, chapterNum)
    postFinalizeSettlementByChapter.set(Number(chapterNum), postFinalizeSettlement)
    upsertChapterReport({ chapterNum, ...postFinalizeSettlement })
    writeReport()
    await page.goto(`${FRONTEND}/project/${report.project.id}?tab=settingsLibrary`, { waitUntil: 'domcontentloaded' })
    await confirmAllSettings(page)
    markChapterFlowEvent(chapterNum, 'settings_confirmation_done')
  } catch (error) {
    const code = error.code || 'manual_setting_review_required'
    const pending = (await api(`/projects/${report.project.id}/settings/change-events?status=pending_review`).catch(() => [])) || []
    const settingEntities = await api(`/projects/${report.project.id}/settings/entities`).catch(() => [])
    const pendingHardConflicts = pendingHardConflictDiagnostics(pending, settingEntities)
    markChapterFlowEvent(chapterNum, 'settings_confirmation_failed', { code, message: error.message, pendingHardConflicts })
    syncHardConflictBlockerFromFlow(chapterNum, code, error, pending, settingEntities)
    if (report.blocker) writeReport()
    error.code = code
    error.liveDiagnostics = {
      ...(await collectSettingsConfirmationDiagnostics(page, chapterNum, code)),
      ...(error.settingReview || {}),
      pendingHardConflicts
    }
    if (report.blocker) writeReport()
    throw error
  }

  const chapter = await findChapter(chapterNum)
  const beat = await api(`/projects/${report.project.id}/chapter-beat-plan/${chapterNum}`).catch(() => null)
  const blocks = await api(`/projects/${report.project.id}/story-blocks`).catch(() => [])
  const block = (blocks || []).find(item => item.id === (beat?.storyBlockId || chapter?.storyBlockId)) || {}
  const reviews = block.reviewHistory || block.review_history || []
  const latestReview = Array.isArray(reviews) ? reviews.at(-1) : null
  const versions = await api(`/projects/${report.project.id}/chapters/${chapter.id}/versions`).catch(() => [])
  const finalVersion = versions.find(version => version.id === chapter.finalVersionId || version.versionType === 'final') || versions.at(-1) || {}
  const pendingSettings = (await api(`/projects/${report.project.id}/settings/change-events?status=pending_review`).catch(() => [])) || []
  const chapterSettingChanges = (await api(`/projects/${report.project.id}/settings/change-events?chapterNum=${chapterNum}`).catch(() => [])) || []
  const settingEntities = (await api(`/projects/${report.project.id}/settings/entities`).catch(() => [])) || []
  const pendingFacts = (await api(`/projects/${report.project.id}/canon-facts`).catch(() => [])).filter(fact => fact.status === 'pending_review')
  const activeBlocks = (blocks || []).filter(item => item.status === 'active')
  const classifiedChapterSettingChanges = classifySettingEvents(chapterSettingChanges, settingEntities)
  const postFinalizeReportFields = postFinalizeSettlementByChapter.get(Number(chapterNum)) || {}
  const preRunStageSettlement = Number(chapterNum) === Number(START_CHAPTER)
    ? (report.stageContinuationSettlementDiagnostics || {})
    : {}

  const entry = {
    chapterNum,
    title: chapter.title || '',
    wordCount: chapter.wordCount || finalVersion.content?.length || 0,
    storyBlockId: beat?.storyBlockId || chapter?.storyBlockId || '',
    blockStageId: beat?.blockStageId || '',
    blockStageSnapshot: beat?.blockStageSnapshot || null,
    currentBlockCompletedStages: block.completedStages || block.completed_stages || [],
    currentBlockStagePlan: block.stagePlan || block.stage_plan || [],
    outlineFromActiveStoryBlock: Boolean(beat?.storyBlockId),
    draftReadSnapshotBoundary: Boolean(beat?.blockStageSnapshot),
    storyBlockReviewDecision: latestReview?.decision || '',
    storyBlockReviewFallback: Boolean(latestReview?.aiReviewFallback || latestReview?.ai_review_fallback),
    storyBlockStageContinues: Boolean(latestReview?.stageContinues || latestReview?.stage_continues),
    storyBlockStageContinueReason: latestReview?.stageContinueReason || latestReview?.stage_continue_reason || latestReview?.reason || '',
    stageContinuationDepth: Number(latestReview?.stageContinuationDepth || latestReview?.stage_continuation_depth || preRunStageSettlement.stageContinuationDepth || 0) || 0,
    previousOpenStageId: latestReview?.previousOpenStageId || latestReview?.previous_open_stage_id || preRunStageSettlement.previousOpenStageId || '',
    settlementDecision: latestReview?.settlementDecision || latestReview?.settlement_decision || preRunStageSettlement.settlementDecision || '',
    settlementEvidence: toList(latestReview?.settlementEvidence || latestReview?.settlement_evidence || preRunStageSettlement.settlementEvidence || []),
    equivalentCompletionScope: latestReview?.equivalentCompletionScope || latestReview?.equivalent_completion_scope || preRunStageSettlement.equivalentCompletionScope || '',
    futureStageTouched: Boolean(latestReview?.futureStageTouched || latestReview?.future_stage_touched || preRunStageSettlement.futureStageTouched),
    futureStageEvidence: toList(latestReview?.futureStageEvidence || latestReview?.future_stage_evidence || preRunStageSettlement.futureStageEvidence || []),
    futureStageOverClosed: Boolean(latestReview?.futureStageOverClosed || latestReview?.future_stage_over_closed || preRunStageSettlement.futureStageOverClosed),
    needsFutureStageReplan: Boolean(latestReview?.needsFutureStageReplan || latestReview?.needs_future_stage_replan || preRunStageSettlement.needsFutureStageReplan),
    replanRemainingStages: Boolean(latestReview?.replanRemainingStages || latestReview?.replan_remaining_stages || preRunStageSettlement.replanRemainingStages),
    whetherStageClosedBeforeNextBeatPlan: Boolean(latestReview?.whetherStageClosedBeforeNextBeatPlan || latestReview?.whether_stage_closed_before_next_beat_plan || preRunStageSettlement.whetherStageClosedBeforeNextBeatPlan),
    storyBlockStatus: block.status || '',
    multipleActiveStoryBlocks: activeBlocks.length > 1,
    missingStoryBlockReviewDecision: !latestReview?.decision,
    missingStoryBlockBinding: !beat?.storyBlockId || !beat?.blockStageId || !beat?.blockStageSnapshot,
    taskProviders: report.modelBinding.taskProviders,
    pendingSettingChanges: pendingSettings.length,
    pendingSettingIds: classifiedChapterSettingChanges
      .filter(item => pendingSettings.some(pending => pending.id === item.id))
      .map(item => item.id),
    settingChanges: classifiedChapterSettingChanges,
    pendingCanonFacts: pendingFacts.length,
    finalized: chapter.status === 'final',
    ...postFinalizeReportFields
  }
  report.pendingSettingsCount = pendingSettings.length
  await runFreezeGuards()
  upsertChapterReport(entry)
  report.acceptance.completedChapters = report.chapterReports.filter(item => item.finalized).length
  await refreshStoryBlockSummaries()
  writeReport()

  if (entry.missingStoryBlockBinding) throw new Error(`第 ${chapterNum} 章故事块绑定或 snapshot 缺失`)
  if (entry.multipleActiveStoryBlocks) throw new Error(`第 ${chapterNum} 章出现多个 active 故事块`)
  if (entry.missingStoryBlockReviewDecision) throw new Error(`chapter ${chapterNum} storyBlockReviewDecision missing after finalize`)
  const previous = report.chapterReports.at(-2)
  entry.previousStoryBlockReviewDecision = previous?.storyBlockReviewDecision || ''
  entry.previousStoryBlockStageContinues = previous ? Boolean(previous.storyBlockStageContinues) : null
  entry.previousStoryBlockStageContinueReason = previous?.storyBlockStageContinueReason || ''
  entry.currentStageReuseAllowed = false
  entry.currentStageReuseReason = ''
  entry.reusedStageFromChapter = null
  if (previous && previous.storyBlockId === entry.storyBlockId && previous.blockStageId === entry.blockStageId) {
    entry.reusedStageFromChapter = previous.chapterNum
    entry.currentStageReuseAllowed = Boolean(previous.storyBlockStageContinues && previous.storyBlockStageContinueReason)
    entry.currentStageReuseReason = previous.storyBlockStageContinueReason || ''
  }
  upsertChapterReport(entry)
  writeReport()
  if (previous && previous.storyBlockId === entry.storyBlockId && previous.blockStageId === entry.blockStageId) {
    if (!previous.storyBlockStageContinues) {
      const message = `第 ${chapterNum} 章无理由复用已完成阶段 ${entry.blockStageId}`
      throw storyBlockStageReuseError(chapterNum, entry, previous, message)
    }
    if (!previous.storyBlockStageContinueReason) {
      const message = `第 ${chapterNum} 章跨章继续同一阶段但缺少 reason`
      throw storyBlockStageReuseError(chapterNum, entry, previous, message)
    }
  }
  if (chapterNum < PHASE_TARGET) {
    await page.goto(`${FRONTEND}/writer/${report.project.id}/${chapterNum}`, { waitUntil: 'domcontentloaded' })
    await clickButton(page, '+ 新章节', 60000)
    await waitFor(`chapter ${chapterNum + 1} exists`, async () => Boolean(await findChapter(chapterNum + 1)), 120000, 3000)
  }
}

function storyBlockStageReuseError(chapterNum, entry, previous, message) {
  const error = new Error(`story_block_stage_reuse_detected: ${message}`)
  error.code = 'story_block_stage_reuse_detected'
  error.liveDiagnostics = {
    chapterNum,
    storyBlockId: entry.storyBlockId,
    blockStageId: entry.blockStageId,
    blockStageSnapshot: entry.blockStageSnapshot || null,
    previousChapterNum: previous?.chapterNum || null,
    previousDecision: previous?.storyBlockReviewDecision || '',
    previousStageContinues: Boolean(previous?.storyBlockStageContinues),
    previousStageContinueReason: previous?.storyBlockStageContinueReason || '',
    currentStageReuseAllowed: Boolean(entry.currentStageReuseAllowed),
    currentStageReuseReason: entry.currentStageReuseReason || previous?.storyBlockStageContinueReason || '',
    reusedStageFromChapter: previous?.chapterNum || null,
    currentBlockCompletedStages: entry.currentBlockCompletedStages || []
  }
  return error
}

function formatCompletedStageIds(stages = []) {
  if (!Array.isArray(stages) || !stages.length) return '无'
  return stages
    .map(stage => {
      if (stage && typeof stage === 'object') return stage.id || stage.stageId || ''
      return stage || ''
    })
    .filter(Boolean)
    .join(',') || '无'
}

async function confirmPendingCanonFacts(page) {
  for (let i = 0; i < 12; i += 1) {
    const facts = (await api(`/projects/${report.project.id}/canon-facts`)) || []
    const pending = facts.filter(fact => fact.status === 'pending_review')
    if (!pending.length) return
    await page.goto(`${FRONTEND}/writer/${report.project.id}`, { waitUntil: 'domcontentloaded' })
    await clickButton(page, '记忆')
    await clickButton(page, '确认')
    await page.waitForTimeout(1000)
  }
}

async function findChapter(chapterNum) {
  const chapters = await api(`/projects/${report.project.id}/chapters`)
  return chapters.find(chapter => Number(chapter.chapterNum) === Number(chapterNum))
}

async function currentChapterId(chapterNum) {
  const chapter = await findChapter(chapterNum)
  if (!chapter?.id) throw new Error(`第 ${chapterNum} 章不存在`)
  return chapter.id
}

async function collectDirtyDataWritten() {
  if (!report.project.id) {
    return {
      project: false,
      settingsChangeEvents: false,
      chapters: false,
      storyBlocks: false
    }
  }
  try {
    const [settings, chapters, blocks] = await Promise.all([
      api(`/projects/${report.project.id}/settings/change-events`).catch(() => []),
      api(`/projects/${report.project.id}/chapters`).catch(() => []),
      api(`/projects/${report.project.id}/story-blocks`).catch(() => [])
    ])
    return {
      project: true,
      settingsChangeEvents: Array.isArray(settings) ? settings.length > 0 : null,
      chapters: Array.isArray(chapters) ? chapters.length > 0 : null,
      storyBlocks: Array.isArray(blocks) ? blocks.length > 0 : null
    }
  } catch {
    return {
      project: true,
      settingsChangeEvents: null,
      chapters: null,
      storyBlocks: null
    }
  }
}

async function fail(stage, error) {
  const classifiedStage = error?.code || error?.liveDiagnostics?.stage || stage
  const previousBlocker = report.blocker && typeof report.blocker === 'object' ? report.blocker : {}
  report.blocker = {
    ...previousBlocker,
    blocked: true,
    stage: previousBlocker.stage || classifiedStage,
    code: previousBlocker.code || error?.code || classifiedStage,
    message: error?.message || String(error),
    stack: String(error?.stack || '').slice(0, 3000),
    liveDiagnostics: error?.liveDiagnostics || error?.settingReview || null,
    pendingHardConflicts: error?.settingReview?.pendingHardConflicts || previousBlocker.pendingHardConflicts || [],
    dirtyDataWritten: await collectDirtyDataWritten()
  }
  report.acceptance.passed = false
  report.acceptance.reason = report.blocker.message
  writeReport()
}

async function main() {
  const browser = await chromium.launch({
    headless: false,
    executablePath: CHROME,
    args: ['--disable-dev-shm-usage']
  })
  const page = await browser.newPage({ viewport: { width: 1440, height: 960 } })
  page.setDefaultTimeout(60000)
  page.on('console', msg => {
    if (msg.type() === 'error') {
      pushLiveConsoleError(msg.text())
      if (/Access-Control-Allow-Origin|CORS policy/i.test(msg.text())) {
        report.aiProxy.browserConsoleCorsErrors += 1
      }
      console.log('[browser:error]', msg.text())
      if (promotePostFinalizeAiProxyFailureFromConsole()) {
        writeReport()
      }
    }
  })
  page.on('request', request => {
    const url = request.url()
    if (isBackendApiUrl(url)) {
      pushLiveNetworkEvent({
        kind: 'request',
        url,
        path: apiPathFromUrl(url),
        method: request.method()
      })
    }
    if (isBackendAiProxyUrl(url)) {
      report.aiProxy.aiProxyUsed = true
      report.aiProxy.backendAiRequests += 1
      pushAiProxyStage({ kind: 'request', url, method: request.method() })
    }
    if (isBrowserProviderChatCompletionUrl(url)) {
      if (!report.aiProxy.providerChatCompletionUrls.includes(url)) {
        report.aiProxy.providerChatCompletionUrls.push(url)
      }
      pushAiProxyStage({ kind: 'browser_provider_request', url, method: request.method() })
    }
  })
  page.on('response', response => {
    const url = response.url()
    if (isBackendApiUrl(url)) {
      pushLiveNetworkEvent({
        kind: 'response',
        url,
        path: apiPathFromUrl(url),
        status: response.status()
      })
    }
    if (isBackendAiProxyUrl(url)) {
      pushAiProxyStage({ kind: 'response', url, status: response.status() })
    }
  })
  page.on('requestfailed', request => {
    const url = request.url()
    if (isBackendApiUrl(url)) {
      pushLiveNetworkEvent({
        kind: 'requestfailed',
        url,
        path: apiPathFromUrl(url),
        method: request.method(),
        errorText: request.failure()?.errorText || ''
      })
    }
    if (isBackendAiProxyUrl(url) || isBrowserProviderChatCompletionUrl(url)) {
      pushAiProxyStage({
        kind: 'requestfailed',
        url,
        method: request.method(),
        errorText: request.failure()?.errorText || ''
      })
    }
  })

  try {
    if (EXISTING_PROJECT_ID) {
      await openExistingProject(page)
      await validateModelInheritance(page)
      await validatePlanningHierarchyText(page)
      writeReport()
    } else {
      await createProject(page)
      await validateModelInheritance(page)
      writeReport()
      await createAndSelectSeed(page)
      writeReport()
      await createBibleAndSettings(page)
      writeReport()
      await generateVolumes(page)
      await validatePlanningHierarchyText(page)
      writeReport()
    }

    await runFreezeGuards()
    for (let chapterNum = START_CHAPTER; chapterNum <= PHASE_TARGET; chapterNum += 1) {
      await runChapter(page, chapterNum)
    }
    await runFreezeGuards()

    report.acceptance.passed = report.acceptance.completedChapters >= RUN_CHAPTER_COUNT
    report.acceptance.reason = report.acceptance.passed
      ? `真实浏览器流程完成第 ${START_CHAPTER}-${PHASE_TARGET} 章。`
      : `第 ${START_CHAPTER}-${PHASE_TARGET} 章仅完成 ${report.acceptance.completedChapters}/${RUN_CHAPTER_COUNT} 章。`
    writeReport()
  } catch (error) {
    await fail(report.stepsCompleted.at(-1) || 'startup', error)
    throw error
  } finally {
    await browser.close().catch(() => {})
  }
}

main()
