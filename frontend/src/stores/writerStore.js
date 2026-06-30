import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '@/api/db/client'
import { chatCompletion, chatCompletionStream } from '@/api/ai'
import { useProviderStore } from './providerStore'
import { useProjectStore } from './projectStore'
import {
  buildDraftSystemPrompt as buildChapterSystemPrompt,
  buildDraftPrompt as buildChapterPrompt
} from '@/prompts/chapterDraftPrompt'
import {
  buildScenePlanSystemPrompt as buildChapterBeatSystemPrompt,
  buildScenePlanPromptWithDiagnostics
} from '@/prompts/chapterPlanPrompt'
import {
  buildContinuePrompt,
  buildExpandPrompt,
  buildCompressPrompt,
  buildMultiVariantPrompt,
  buildChapterTitleSystemPrompt,
  buildChapterTitlePrompt,
  buildChapterBeatPlanCompactionPrompt,
  buildChapterBeatPlanJsonRepairPrompt,
  buildChapterBeatPlanParseRetryPrompt,
  buildChapterBeatPlanRepairPrompt,
  collectStructuredBeatPlanIssues,
  compactStructuredBeatPlanFields,
  formatStructuredBeatPlan,
  parseStructuredBeatPlan,
  squeezeChapterBeatPlanText,
  buildProseRhythmRepairSystemPrompt,
  buildProseRhythmRepairPrompt,
  buildNotXButYRepairSystemPrompt,
  buildNotXButYRepairPrompt,
  buildNotXButYSegmentRepairPrompt,
  buildParagraphRepetitionRepairPrompt,
  parseMultiVariantText,
  cleanGeneratedChapterText,
  cleanChapterBeatPlanText,
  BEAT_PLAN_SOURCES,
  buildLocalChapterBeatPlanFallback,
  buildNearTurnDecisionCard,
  deriveChapterBeatPlanFromStoryBlock,
  cleanGeneratedChapterTitle,
  deriveFallbackChapterTitle,
  isDefaultChapterTitle
} from '@/prompts/chapter'
import { buildRewriteSystemPrompt, buildRewritePrompt } from '@/prompts/rewrite'
import { buildCorrectionDraftPrompt } from '@/prompts/correctionDraft'
import {
  buildCorrectionPatchPrompt,
  buildCorrectionPatchRepairPrompt,
  buildCorrectionPatchRetryPrompt
} from '@/prompts/correctionPatch'
import {
  applyLocalRevisionPatches,
  buildLocalRevisionPatchesFromIssues,
  extractLocalRevisionPatches
} from '@/utils/localRevisionPatch'
import {
  analyzeProseRhythm,
  applyNotXButYSegmentReplacements,
  buildLocalProseRhythmRepairCandidate,
  countCjkChars,
  extractNotXButYRepairSegments,
  shouldAcceptNotXButYRepair,
  shouldAcceptNotXButYSegmentRepair,
  shouldAcceptProseRhythmRepair,
  shouldRepairProseRhythm
} from '@/utils/proseRhythmGuard'
import {
  analyzeNarrativeReadability,
  buildPlanningHealthRecord,
  shouldAcceptNarrativeReadabilityRepair,
  validateBeatPlanProgressionGate
} from '@/quality/writingQualityScoring'
import { extractAiContent } from '@/domain/chapter-draft/ai-content'
import { runDraftRepairPipeline } from '@/application/writer-flow/draft-repair-pipeline'

const CHAPTER_DRAFT_MAX_TOKENS = 5000
const BEAT_PLAN_INITIAL_MAX_TOKENS = 1800
const BEAT_PLAN_EMPTY_LENGTH_RETRY_MAX_TOKENS = 4096
const BEAT_PLAN_REQUIRES_REVIEW = 'BEAT_PLAN_REQUIRES_REVIEW'

export const useWriterStore = defineStore('writer', () => {
  const chapters = ref([])
  const versions = ref([])
  const currentChapter = ref(null)
  const currentVersion = ref(null)
  const tempDraft = ref(null)
  const loading = ref(false)
  const generating = ref(false)
  const beatPlanning = ref(false)
  const chapterBeatPlan = ref('')
  const beatPlanRecord = ref(null)
  const beatPlanSource = ref('')
  const beatPlanQualityNotice = ref(null)
  const beatPlanDiagnostics = ref(null)
  const beatPlanQualityDiagnostics = ref(null)
  const generationStream = ref('')

  function estimatePromptTokens(text = '') {
    return Math.ceil(String(text || '').length / 2)
  }

  function saveBeatPlanDiagnostics(projectId, chapterNum, diagnostics = {}) {
    beatPlanDiagnostics.value = diagnostics
    if (typeof window === 'undefined' || !window.localStorage || !projectId || !chapterNum) return
    try {
      window.localStorage.setItem(`beat-plan-diagnostics:${projectId}:${chapterNum}`, JSON.stringify({
        ...diagnostics,
        savedAt: new Date().toISOString()
      }))
    } catch (error) {
      console.warn('保存小纲诊断失败:', error.message)
    }
  }

  function readUsageNumber(usage, ...keys) {
    if (!usage || typeof usage !== 'object') return null
    for (const key of keys) {
      const value = usage[key]
      if (typeof value === 'number' && Number.isFinite(value)) return value
    }
    return null
  }

  function readReasoningTokens(usage) {
    if (!usage || typeof usage !== 'object') return null
    const details = usage.completion_tokens_details || usage.completionTokensDetails || usage.output_tokens_details || usage.outputTokensDetails || {}
    return readUsageNumber(details, 'reasoning_tokens', 'reasoningTokens') ??
      readUsageNumber(usage, 'reasoning_tokens', 'reasoningTokens')
  }

  function buildAiResponseDiagnostics(result) {
    if (!result || typeof result !== 'object') {
      const contentLength = String(result || '').length
      return {
        backendResponseStatus: null,
        responseBodyLength: null,
        choicesLength: null,
        messageContentLength: contentLength,
        contentLength,
        finishReason: null,
        usage: null,
        completionTokens: null,
        promptTokens: null,
        totalTokens: null,
        reasoningTokens: null
      }
    }
    const proxyDiagnostics = result.proxyDiagnostics || result.proxy_diagnostics || {}
    const choices = Array.isArray(result.choices) ? result.choices : []
    const firstChoice = choices[0] || {}
    const content = firstChoice?.message?.content ?? firstChoice?.text ?? ''
    const usage = proxyDiagnostics.usage ?? result.usage ?? null
    const messageContentLength = proxyDiagnostics.messageContentLength ?? String(content || '').length
    const contentLength = proxyDiagnostics.contentLength ?? messageContentLength
    const serializedLength = (() => {
      try {
        return JSON.stringify(result).length
      } catch {
        return null
      }
    })()
    return {
      backendResponseStatus: proxyDiagnostics.backendResponseStatus ?? proxyDiagnostics.httpStatus ?? null,
      responseBodyLength: proxyDiagnostics.responseBodyLength ?? serializedLength,
      choicesLength: proxyDiagnostics.choicesLength ?? choices.length,
      messageContentLength,
      contentLength,
      finishReason: proxyDiagnostics.finishReason ?? firstChoice?.finish_reason ?? null,
      usage,
      completionTokens: proxyDiagnostics.completionTokens ?? readUsageNumber(usage, 'completion_tokens', 'completionTokens', 'output_tokens', 'outputTokens'),
      promptTokens: proxyDiagnostics.promptTokens ?? readUsageNumber(usage, 'prompt_tokens', 'promptTokens', 'input_tokens', 'inputTokens'),
      totalTokens: proxyDiagnostics.totalTokens ?? readUsageNumber(usage, 'total_tokens', 'totalTokens'),
      reasoningTokens: proxyDiagnostics.reasoningTokens ?? readReasoningTokens(usage)
    }
  }

  function isEmptyLengthAiResponse(result, content = '') {
    const diagnostics = buildAiResponseDiagnostics(result)
    const finishReason = String(diagnostics.finishReason || '').toLowerCase()
    const contentLength = Number(diagnostics.contentLength ?? diagnostics.messageContentLength ?? String(content || '').length) || 0
    return finishReason === 'length' && contentLength === 0
  }

  function stripBeatPlanJsonFence(raw = '') {
    return String(raw || '').trim()
      .replace(/^```(?:json)?/i, '')
      .replace(/```$/i, '')
      .trim()
  }

  function looksLikeUnclosedBeatPlanJson(raw = '') {
    const source = stripBeatPlanJsonFence(raw)
    if (!source.startsWith('{') || source.endsWith('}')) return false
    return /"chapterEvent"|"characterGoal"|"coreConflict"|"endingHandoff"/.test(source)
  }

  function shouldTriggerBeatPlanParseRecovery(candidateDiagnostics = {}, responseDiagnostics = {}, raw = '') {
    const parseError = String(candidateDiagnostics.parseError || '')
    if (candidateDiagnostics.candidateFailureCode !== 'beat_plan_parse_failed') return false
    return String(responseDiagnostics.finishReason || '').toLowerCase() === 'length' ||
      parseError.includes('JSON 对象边界不完整') ||
      looksLikeUnclosedBeatPlanJson(raw)
  }

  function buildBeatPlanRecoveryContextBrief(context = {}, chapterNum = context?.chapterNum) {
    const snapshot = context.blockStageSnapshot || context.stageSnapshot || null
    const lines = [
      context.previousChapterEnding ? `上一章结尾：${String(context.previousChapterEnding).slice(0, 180)}` : '',
      context.chapterGoal ? `本章目标：${typeof context.chapterGoal === 'string' ? context.chapterGoal : JSON.stringify(context.chapterGoal)}` : '',
      snapshot?.stagePurpose ? `故事块阶段目的：${snapshot.stagePurpose}` : '',
      snapshot?.stageAction ? `阶段行动：${snapshot.stageAction}` : '',
      snapshot?.stageChoice ? `人物选择：${snapshot.stageChoice}` : '',
      snapshot?.stageCostOrConsequence ? `代价后果：${snapshot.stageCostOrConsequence}` : '',
      snapshot?.exitTarget ? `结尾交接：${snapshot.exitTarget}` : '',
      context.volumeStage?.coreGoal ? `当前卷目标：${context.volumeStage.coreGoal}` : '',
      chapterNum ? `当前章节：第 ${chapterNum} 章` : ''
    ].filter(Boolean)
    return lines.join('\n').slice(0, 1200)
  }

  function appendBeatPlanAttemptDiagnostics(diagnostics, {
    attempt,
    reason = '',
    maxTokens,
    thinkingOverride = null,
    messages = [],
    promptDiagnostics = null,
    result = null,
    raw = '',
    content = '',
    forceMinimal = false
  }) {
    const responseDiagnostics = buildAiResponseDiagnostics(result)
    diagnostics.attempts.push({
      attempt,
      reason,
      maxTokens,
      thinkingOverride,
      promptChars: messages.reduce((sum, message) => sum + String(message.content || '').length, 0),
      promptTokensApprox: estimatePromptTokens(messages.map(message => message.content || '').join('\n')),
      storyBlockId: promptDiagnostics?.storyBlockId || diagnostics.storyBlockId || '',
      blockStageId: promptDiagnostics?.blockStageId || diagnostics.blockStageId || '',
      activeStoryBlockExists: promptDiagnostics?.activeStoryBlockExists ?? diagnostics.activeStoryBlockExists,
      activeStoryBlockStageCount: promptDiagnostics?.activeStoryBlockStageCount ?? diagnostics.activeStoryBlockStageCount,
      activeStoryBlockNextStage: promptDiagnostics?.activeStoryBlockNextStage || diagnostics.activeStoryBlockNextStage,
      forceMinimal,
      rawHead: String(raw || '').slice(0, 1500),
      rawTail: String(raw || '').slice(-800),
      extractedLength: String(raw || '').length,
      cleanedLength: String(content || '').length,
      responseDiagnostics
    })
    return responseDiagnostics
  }

  function hasConfiguredThinking(provider = {}) {
    return Boolean(provider?.thinking || provider?.thinkingConfig || provider?.thinking_config || provider?.reasoning || provider?.reasoningConfig || provider?.reasoning_config)
  }

  function resolveBeatPlanRetryThinking(provider = {}, emptyLengthRetry = false) {
    if (!emptyLengthRetry || !hasConfiguredThinking(provider)) return undefined
    return { type: 'disabled' }
  }

  function hasText(value) {
    return value !== undefined && value !== null && String(value).trim() !== ''
  }

  async function compactChapterBeatPlanIfNeeded(provider, chapterNum, content, context = {}) {
    content = String(content || '').trim()
    if (content.length <= 1300) return content

    let best = content
    try {
      for (let attempt = 1; attempt <= 2; attempt += 1) {
        const messages = [
          {
            role: 'system',
            content: '你是长篇小说分章小纲编辑。只负责压缩小纲，不写正文，不解释。'
          },
          {
            role: 'user',
            content: buildChapterBeatPlanCompactionPrompt({
              chapterNum,
              beatPlan: best,
              contextBrief: context?.previousChapterEnding ? `上一章结尾：${context.previousChapterEnding}` : '',
              attempt,
              previousLength: best.length
            })
          }
        ]
        const result = await chatCompletion(provider, messages, { maxTokens: 1400, temperature: 0.3 })
        const compacted = cleanChapterBeatPlanText(extractAiContent(result))
        if (compacted.length >= 500 && compacted.length < best.length) best = compacted
        if (best.length <= 1300) return best
      }

      const squeezed = squeezeChapterBeatPlanText(best, { maxChars: 1300, minChars: 500 })
      if (squeezed.length <= 1300 && squeezed.length >= 500 && squeezed.length < best.length) return squeezed

      if (best.length < content.length) {
        console.warn('压缩章节小纲后仍超过建议上限，已阻止继续生成正文:', {
          before: content.length,
          after: best.length
        })
        throw new Error(`第 ${chapterNum} 章小纲压缩后仍超过上限（${content.length} -> ${best.length} 字符），请重新生成或手动删减后再生成正文。`)
      }
    } catch (e) {
      console.warn('压缩章节小纲失败，已阻止继续生成正文:', e.message)
    }
    const fallback = buildLocalChapterBeatPlanFallback({ ...context, chapterNum }, chapterNum, best)
    if (fallback.length >= 500 && fallback.length <= 1300) {
      beatPlanQualityNotice.value = {
        source: 'local_safety_rebuild',
        chapterNum,
        content: fallback,
        originalLength: content.length,
        fallbackLength: fallback.length,
        issues: ['overlong_after_compaction'],
        message: 'AI 小纲质量不足，已生成安全小纲，请审阅后再生成正文。'
      }
      return fallback
    }

    throw new Error(`第 ${chapterNum} 章小纲超过上限（${content.length} 字符），请重新生成或手动删减后再生成正文。`)
  }

  async function expandChapterBeatPlanIfNeeded(provider, chapterNum, content, context = {}) {
    content = String(content || '').trim()
    if (content.length >= 500) return content

    let best = content
    try {
      for (let attempt = 1; attempt <= 2; attempt += 1) {
        const messages = [
          {
            role: 'system',
            content: '你是长篇小说分章小纲编辑。只负责把过短小纲扩展成可执行小纲，不写正文，不解释。'
          },
          {
            role: 'user',
            content: [
              `请把第 ${chapterNum} 章小纲扩展为 700-1100 字，控制在 4-6 个节拍，绝不能超过 1300 字。`,
              '必须补足：本章核心目的、场景摩擦、人物欲望/恐惧/遮掩、关键选择、选择代价、信息释放方式、状态延续、道具来源、伏笔铺垫和章末钩子。',
              '只扩展可执行节拍，不写正文句子，不新增完整大场景，不把下一章冲突提前塞进本章。',
              context?.previousChapterEnding ? `上一章结尾：${context.previousChapterEnding}` : '',
              context?.chapterGoal ? `本章目标：${JSON.stringify(context.chapterGoal).slice(0, 800)}` : '',
              attempt > 1 ? `上一次扩展仍过短或不合格（${best.length} 字符），请补足可执行节拍。` : '',
              `原小纲：\n${best || '只有空白或极短提示，请根据本章上下文补成可执行小纲。'}`
            ].filter(Boolean).join('\n\n')
          }
        ]
        const result = await chatCompletion(provider, messages, { maxTokens: 1800, temperature: 0.35 })
        const expanded = cleanChapterBeatPlanText(extractAiContent(result))
        if (expanded.length > best.length && expanded.length <= 1300) best = expanded
        if (best.length >= 500 && best.length <= 1300) return best
      }
    } catch (e) {
      console.warn('扩展章节小纲失败，已阻止继续生成正文:', e.message)
    }

    const fallback = buildLocalChapterBeatPlanFallback({ ...context, chapterNum }, chapterNum, best)
    if (fallback.length >= 500 && fallback.length <= 1300) {
      beatPlanQualityNotice.value = {
        source: 'local_safety_rebuild',
        chapterNum,
        content: fallback,
        originalLength: content.length,
        fallbackLength: fallback.length,
        issues: ['too_short_after_expansion'],
        message: 'AI 小纲质量不足，已生成安全小纲，请审阅后再生成正文。'
      }
      return fallback
    }

    throw new Error(`第 ${chapterNum} 章小纲过短（${content.length} 字符），请重新生成或手动补足人物动机、场景摩擦、选择代价和章末钩子后再生成正文。`)
  }

  function getVolumeGoalForBeatPlanRepair(context = {}, nearTurnDecisionCard = null) {
    return [
      nearTurnDecisionCard?.currentVolumeGoal,
      context.volumeStage?.coreGoal,
      context.volumeStage?.mainConflict,
      context.currentVolume?.goal,
      context.currentVolume?.mainConflict
    ].filter(Boolean).join('；')
  }

  function compactStructuredBeatPlanForLength(content, maxChars = 1300) {
    const parsed = parseStructuredBeatPlan(content)
    if (!Object.values(parsed).some(value => String(value || '').trim())) return content
    for (const maxFieldChars of [180, 150, 120, 95, 75]) {
      const compacted = compactStructuredBeatPlanFields(parsed, { maxFieldChars })
      const formatted = formatStructuredBeatPlan(compacted)
      const issues = collectStructuredBeatPlanIssues(compacted)
      if (formatted.length <= maxChars && !issues.missingRequiredFields.length && !issues.placeholderFields?.length) return formatted
    }
    return formatStructuredBeatPlan(compactStructuredBeatPlanFields(parsed, { maxFieldChars: 75 }))
  }

  function buildBeatPlanQualityDiagnostics(chapterNum, issues = {}, options = {}) {
    return {
      chapterNum,
      missingFields: issues.missingRequiredFields || [],
      placeholderFields: issues.placeholderFields || [],
      repaired: Boolean(options.repaired),
      repairSucceeded: Boolean(options.repairSucceeded),
      finalBeatPlanLength: Number(options.finalBeatPlanLength || 0),
      issueTypes: (issues.issues || []).map(item => item.type).filter(Boolean),
      failureCode: options.failureCode || '',
      candidateRaw: options.candidateRaw || '',
      parsedCandidate: options.parsedCandidate || null,
      qualityGateInput: options.qualityGateInput || '',
      qualityGateResult: options.qualityGateResult || null,
      parseError: options.parseError || ''
    }
  }

  function detectBeatPlanJsonParseError(raw = '') {
    const source = String(raw || '').trim()
      .replace(/^```(?:json)?/i, '')
      .replace(/```$/i, '')
      .trim()
    const start = source.indexOf('{')
    const end = source.lastIndexOf('}')
    if (start < 0 && end < 0) return ''
    if (start < 0 || end <= start) return 'JSON 对象边界不完整'
    try {
      JSON.parse(source.slice(start, end + 1))
      return ''
    } catch (error) {
      return error.message || 'JSON 解析失败'
    }
  }

  function summarizeBeatPlanGateResult(result = null) {
    if (!result) return null
    const volumeGoalHandoff = result.freshness?.volumeGoalHandoff || null
    const volumeGoalHandoffDiagnostic = volumeGoalHandoff
      ? {
          status: volumeGoalHandoff.status || '',
          missing: Boolean(volumeGoalHandoff.missing),
          derived: Boolean(volumeGoalHandoff.derived),
          source: volumeGoalHandoff.source || '',
          matchedTerms: volumeGoalHandoff.matchedTerms || [],
          derivedHandoffText: volumeGoalHandoff.derivedHandoffText || '',
          derivableChangeTypes: volumeGoalHandoff.derivableChangeTypes || [],
          evidence: volumeGoalHandoff.evidence || null,
          warning: volumeGoalHandoff.warning || ''
        }
      : null
    return {
      gate: result.gate || '',
      passed: Boolean(result.passed),
      issues: (result.issues || []).map(item => ({
        type: item.type || '',
        severity: item.severity || '',
        detail: item.detail || '',
        missingFields: item.missingFields || item.missingRequiredFields || []
      })),
      irreversibleChange: result.irreversibleChange || '',
      irreversibleChangeTypes: result.irreversibleChangeTypes || [],
      loopExit: result.loopExit ?? null,
      freshnessGate: result.freshnessGate || '',
      volumeGoalHandoffDiagnostic
    }
  }

  function buildBeatPlanCandidateDiagnostics(chapterNum, rawCandidate = '', context = {}) {
    const candidateRaw = String(rawCandidate || '').trim()
    const parseError = detectBeatPlanJsonParseError(candidateRaw)
    const parsedCandidate = parseError ? {} : parseStructuredBeatPlan(candidateRaw)
    const nearTurnDecisionCard = context?.nearTurnDecisionCard || buildNearTurnDecisionCard({ ...context, chapterNum })
    const structuredIssues = parseError
      ? { missingRequiredFields: [], placeholderFields: [], issues: [] }
      : collectStructuredBeatPlanIssues(parsedCandidate, { nearTurnDecisionCard })
    const hasBlockingStructuredIssues = Boolean(
      structuredIssues.missingRequiredFields?.length ||
      structuredIssues.placeholderFields?.length ||
      structuredIssues.toolingLeakFields?.length
    )
    const qualityGateInput = (!parseError && !hasBlockingStructuredIssues)
      ? compactStructuredBeatPlanForLength(formatStructuredBeatPlan(parsedCandidate))
      : ''
    const qualityGateResult = qualityGateInput
      ? validateBeatPlanProgressionGate(qualityGateInput, { ...context, chapterNum, nearTurnDecisionCard })
      : null
    const failureCode = parseError
      ? 'beat_plan_parse_failed'
      : (structuredIssues.toolingLeakFields?.length
          ? 'beat_plan_requires_review'
          : (hasBlockingStructuredIssues ? 'beat_plan_missing_fields' : (qualityGateResult && !qualityGateResult.passed ? 'beat_plan_quality_failed' : '')))
    return {
      candidateRaw: candidateRaw.slice(0, 4000),
      parsedCandidate,
      candidateStructuredIssues: structuredIssues,
      qualityGateInput,
      qualityGateResult: summarizeBeatPlanGateResult(qualityGateResult),
      candidateFailureCode: failureCode,
      candidateFailureIssueTypes: qualityGateResult?.issues?.map(item => item.type).filter(Boolean) || [],
      parseError
    }
  }

  function hasBlockingBeatPlanQualityIssues(issues = {}) {
    return Boolean(
      issues.missingRequiredFields?.length ||
      issues.placeholderFields?.length ||
      issues.toolingLeakFields?.length
    )
  }

  function throwBeatPlanQualityError(chapterNum, issues = {}, content = '', options = {}) {
    const candidateDiagnostics = buildBeatPlanCandidateDiagnostics(chapterNum, content, options.context || {})
    const failureCode = issues.toolingLeakFields?.length
      ? 'beat_plan_requires_review'
      : (candidateDiagnostics.candidateFailureCode === 'beat_plan_parse_failed'
          ? 'beat_plan_parse_failed'
          : 'beat_plan_missing_fields')
    const diagnostics = buildBeatPlanQualityDiagnostics(chapterNum, issues, {
      ...options,
      ...candidateDiagnostics,
      failureCode,
      finalBeatPlanLength: String(content || '').length
    })
    beatPlanQualityDiagnostics.value = diagnostics
    const toolingFields = (issues.toolingLeakFields || []).filter(Boolean)
    const fields = [...diagnostics.missingFields, ...diagnostics.placeholderFields, ...toolingFields].filter(Boolean).join(', ') || 'unknown'
    const error = new Error(failureCode === 'beat_plan_requires_review'
      ? `beat_plan_requires_review: 第 ${chapterNum} 章小纲仍含模板话术字段：${fields}。请重新生成自然小纲后再生成正文。`
      : `第 ${chapterNum} 章小纲字段缺失或占位：${fields}。请重新生成或补齐真实剧情字段后再生成正文。`)
    error.code = failureCode
    error.diagnostics = diagnostics
    throw error
  }

  async function repairChapterBeatPlanIfNeeded(provider, chapterNum, content, context = {}, options = {}) {
    const nearTurnDecisionCard = options.nearTurnDecisionCard || context?.nearTurnDecisionCard || buildNearTurnDecisionCard({ ...context, chapterNum })
    let currentStructured = parseStructuredBeatPlan(content)
    let currentIssues = options.structuredIssues || collectStructuredBeatPlanIssues(currentStructured, { nearTurnDecisionCard })
    let previousIssues = options.previousIssues || currentIssues.issues || []
    const mustRepair = currentIssues.missingRequiredFields?.length ||
      currentIssues.placeholderFields?.length ||
      currentIssues.toolingLeakFields?.length ||
      currentIssues.volumeGoalHandoffStatus === 'fail' ||
      currentIssues.turnDecisionStatus === 'fail' ||
      previousIssues.length
    if (!mustRepair) {
      return {
        content: compactStructuredBeatPlanForLength(formatStructuredBeatPlan(currentStructured)),
        repairAttempted: false,
        repairSucceeded: false,
        structuredIssues: currentIssues
      }
    }

    for (let attempt = 1; attempt <= 2; attempt += 1) {
      const prompt = buildChapterBeatPlanRepairPrompt({
        chapterNum,
        originalBeatPlan: currentStructured,
        missingRequiredFields: [...new Set([...(currentIssues.missingRequiredFields || []), ...(currentIssues.placeholderFields || []), ...(currentIssues.toolingLeakFields || [])])],
        previousIssues,
        nearTurnDecisionCard,
        volumeGoal: getVolumeGoalForBeatPlanRepair(context, nearTurnDecisionCard)
      })
      const result = await chatCompletion(provider, [
        { role: 'system', content: '你是长篇小说小纲结构修复器。只输出合法 JSON，不要 Markdown，不要解释。' },
        { role: 'user', content: attempt > 1 ? `${prompt}\n\n上一次修复仍不合格，请只补缺失字段并强化 loopExit 与 volumeGoalHandoff。` : prompt }
      ], { maxTokens: 1800, temperature: 0.25 })
      const repairedStructured = parseStructuredBeatPlan(extractAiContent(result))
      const merged = {
        ...currentStructured,
        ...Object.fromEntries(Object.entries(repairedStructured).filter(([, value]) => hasText(value) || typeof value === 'boolean'))
      }
      const mergedIssues = collectStructuredBeatPlanIssues(merged, { nearTurnDecisionCard })
      currentStructured = merged
      currentIssues = mergedIssues
      const compactedContent = compactStructuredBeatPlanForLength(formatStructuredBeatPlan(merged))
      const progressionGate = previousIssues.length
        ? validateBeatPlanProgressionGate(compactedContent, { ...context, chapterNum, nearTurnDecisionCard })
        : { passed: true, issues: [] }
      if (!mergedIssues.missingRequiredFields.length &&
        !mergedIssues.placeholderFields?.length &&
        mergedIssues.volumeGoalHandoffStatus !== 'fail' &&
        mergedIssues.turnDecisionStatus !== 'fail' &&
        progressionGate.passed) {
        return {
          content: compactedContent,
          repairAttempted: true,
          repairSucceeded: true,
          structuredIssues: mergedIssues
        }
      }
      if (previousIssues.length && progressionGate.issues?.length) {
        previousIssues = progressionGate.issues
        currentIssues = {
          ...mergedIssues,
          issues: [...(mergedIssues.issues || []), ...progressionGate.issues]
        }
      }
    }

    return {
      content: compactStructuredBeatPlanForLength(formatStructuredBeatPlan(currentStructured)),
      repairAttempted: true,
      repairSucceeded: false,
      structuredIssues: currentIssues
    }
  }

  async function ensureChapterBeatPlanQuality(provider, chapterNum, content, context = {}) {
    content = cleanChapterBeatPlanText(String(content || '').trim())
    beatPlanQualityDiagnostics.value = null
    if (!content) {
      const diagnostics = buildBeatPlanQualityDiagnostics(chapterNum, {}, {
        failureCode: 'beat_plan_empty_after_quality_cleaning',
        candidateRaw: content,
        finalBeatPlanLength: 0,
        qualityGateResult: {
          passed: false,
          issues: [{ type: 'empty_after_quality_cleaning' }]
        }
      })
      beatPlanQualityDiagnostics.value = diagnostics
      const error = new Error(`第 ${chapterNum} 章小纲为空，请先生成或填写本章小纲。`)
      error.code = 'beat_plan_empty_after_quality_cleaning'
      error.diagnostics = diagnostics
      throw error
    }

    const nearTurnDecisionCard = context?.nearTurnDecisionCard || buildNearTurnDecisionCard({ ...context, chapterNum })
    const initialCandidateDiagnostics = buildBeatPlanCandidateDiagnostics(chapterNum, content, { ...context, nearTurnDecisionCard })
    if (initialCandidateDiagnostics.candidateFailureCode === 'beat_plan_parse_failed') {
      const diagnostics = buildBeatPlanQualityDiagnostics(chapterNum, {}, {
        ...initialCandidateDiagnostics,
        failureCode: 'beat_plan_parse_failed',
        finalBeatPlanLength: String(content || '').length
      })
      beatPlanQualityDiagnostics.value = diagnostics
      const error = new Error(`第 ${chapterNum} 章小纲解析失败：${initialCandidateDiagnostics.parseError}。请重新生成合法 JSON 或结构化小纲。`)
      error.code = 'beat_plan_parse_failed'
      error.diagnostics = diagnostics
      throw error
    }
    let repairAttempted = false
    let repairSucceeded = false
    let localSafetyRebuildUsed = false
    let structuredIssues = collectStructuredBeatPlanIssues(parseStructuredBeatPlan(content), { nearTurnDecisionCard })
    if (structuredIssues.missingRequiredFields.length ||
      structuredIssues.placeholderFields?.length ||
      structuredIssues.toolingLeakFields?.length ||
      structuredIssues.volumeGoalHandoffStatus === 'fail' ||
      structuredIssues.turnDecisionStatus === 'fail') {
      const repaired = await repairChapterBeatPlanIfNeeded(provider, chapterNum, content, context, {
        nearTurnDecisionCard,
        structuredIssues
      })
      content = repaired.content
      repairAttempted = repaired.repairAttempted
      repairSucceeded = repaired.repairSucceeded
      structuredIssues = repaired.structuredIssues
    } else {
      content = compactStructuredBeatPlanForLength(formatStructuredBeatPlan(parseStructuredBeatPlan(content)))
    }

    if (content.length > 1300) {
      content = await compactChapterBeatPlanIfNeeded(provider, chapterNum, content, context)
      structuredIssues = collectStructuredBeatPlanIssues(parseStructuredBeatPlan(content), { nearTurnDecisionCard })
      if (structuredIssues.missingRequiredFields.length || structuredIssues.placeholderFields?.length || structuredIssues.toolingLeakFields?.length || structuredIssues.volumeGoalHandoffStatus === 'fail') {
        const repaired = await repairChapterBeatPlanIfNeeded(provider, chapterNum, content, context, {
          nearTurnDecisionCard,
          structuredIssues
        })
        content = repaired.content
        repairAttempted = repairAttempted || repaired.repairAttempted
        repairSucceeded = repairSucceeded || repaired.repairSucceeded
        structuredIssues = repaired.structuredIssues
      }
    }
    if (content.length < 500) {
      content = await expandChapterBeatPlanIfNeeded(provider, chapterNum, content, context)
    }
    if (content.length > 1300) {
      content = await compactChapterBeatPlanIfNeeded(provider, chapterNum, content, context)
    }

    if (content.length < 500) {
      throw new Error(`第 ${chapterNum} 章小纲过短（${content.length} 字符），请重新生成或手动补足后再生成正文。`)
    }
    if (content.length > 1300) {
      throw new Error(`第 ${chapterNum} 章小纲超过上限（${content.length} 字符），请重新生成或手动删减后再生成正文。`)
    }
    structuredIssues = collectStructuredBeatPlanIssues(parseStructuredBeatPlan(content), { nearTurnDecisionCard })
    if (hasBlockingBeatPlanQualityIssues(structuredIssues)) {
      const repaired = await repairChapterBeatPlanIfNeeded(provider, chapterNum, content, context, {
        nearTurnDecisionCard,
        structuredIssues
      })
      repairAttempted = repairAttempted || repaired.repairAttempted
      repairSucceeded = repairSucceeded || repaired.repairSucceeded
      content = repaired.content
      structuredIssues = collectStructuredBeatPlanIssues(parseStructuredBeatPlan(content), { nearTurnDecisionCard })
      if (hasBlockingBeatPlanQualityIssues(structuredIssues)) {
        throwBeatPlanQualityError(chapterNum, structuredIssues, content, {
          repaired: repairAttempted,
          repairSucceeded,
          context
        })
      }
    }
    let progressionGate = validateBeatPlanProgressionGate(content, {
      ...context,
      chapterNum,
      nearTurnDecisionCard
    })
    if (!progressionGate.passed) {
      const repaired = await repairChapterBeatPlanIfNeeded(provider, chapterNum, content, context, {
        nearTurnDecisionCard,
        structuredIssues,
        previousIssues: progressionGate.issues || []
      })
      repairAttempted = repairAttempted || repaired.repairAttempted
      repairSucceeded = repairSucceeded || repaired.repairSucceeded
      if (repaired.repairSucceeded) {
        content = repaired.content
        structuredIssues = repaired.structuredIssues
        progressionGate = validateBeatPlanProgressionGate(content, {
          ...context,
          chapterNum,
          nearTurnDecisionCard
        })
      }
    }
    if (!progressionGate.passed) {
      const fallback = buildLocalChapterBeatPlanFallback({ ...context, chapterNum, nearTurnDecisionCard }, chapterNum, content)
      const fallbackGate = validateBeatPlanProgressionGate(fallback, {
        ...context,
        chapterNum,
        nearTurnDecisionCard
      })
      if (fallback.length >= 500 && fallback.length <= 1300 && fallbackGate.passed) {
        localSafetyRebuildUsed = true
        console.warn('章节小纲推进闸未通过，已启用本地安全重建:', {
          chapterNum,
          issues: progressionGate.issues?.map(item => item.type)
        })
        beatPlanQualityNotice.value = {
          source: 'local_safety_rebuild',
          chapterNum,
          content: fallback,
          originalLength: content.length,
          fallbackLength: fallback.length,
          issues: progressionGate.issues?.map(item => item.type) || [],
          planningHealth: buildPlanningHealthRecord({
            chapterNum,
            aiBeatPlanGenerated: true,
            aiBeatPlanValid: false,
            repairAttempted,
            repairSucceeded,
            localSafetyRebuildUsed,
            consecutiveLocalRebuildCount: 1,
            missingRequiredFields: structuredIssues.missingRequiredFields || [],
            placeholderFields: structuredIssues.placeholderFields || [],
            volumeGoalHandoffStatus: structuredIssues.volumeGoalHandoffStatus || 'fail'
          }),
          message: 'AI 小纲质量不足，已生成安全小纲，请审阅后再生成正文。'
        }
        content = fallback
        progressionGate = fallbackGate
      }
    }
    if (!progressionGate.passed) {
      const issueTypes = progressionGate.issues?.map(item => item.type).join('、') || 'unknown'
      const candidateDiagnostics = buildBeatPlanCandidateDiagnostics(chapterNum, content, { ...context, chapterNum, nearTurnDecisionCard })
      const diagnostics = buildBeatPlanQualityDiagnostics(chapterNum, structuredIssues, {
        ...candidateDiagnostics,
        qualityGateResult: summarizeBeatPlanGateResult(progressionGate),
        failureCode: 'beat_plan_quality_failed',
        repaired: repairAttempted,
        repairSucceeded,
        finalBeatPlanLength: String(content || '').length
      })
      beatPlanQualityDiagnostics.value = diagnostics
      const error = new Error(`第 ${chapterNum} 章小纲质量闸未通过：${issueTypes}。请重新生成小纲，让本章出现可复述真实事件、具体行动和离开最近循环的转向。`)
      error.code = 'beat_plan_quality_failed'
      error.diagnostics = diagnostics
      throw error
    }
    structuredIssues = collectStructuredBeatPlanIssues(parseStructuredBeatPlan(content), { nearTurnDecisionCard })
    if (hasBlockingBeatPlanQualityIssues(structuredIssues)) {
      throwBeatPlanQualityError(chapterNum, structuredIssues, content, {
        repaired: repairAttempted,
        repairSucceeded,
        context
      })
    }
    const candidateDiagnostics = buildBeatPlanCandidateDiagnostics(chapterNum, content, { ...context, chapterNum, nearTurnDecisionCard })
    beatPlanQualityDiagnostics.value = buildBeatPlanQualityDiagnostics(chapterNum, structuredIssues, {
      ...candidateDiagnostics,
      repaired: repairAttempted,
      repairSucceeded,
      finalBeatPlanLength: content.length
    })
    return content
  }

  function applyDerivedBeatPlanFallback(chapterNum, context = {}, diagnostics = {}, reason = '', originalText = '') {
    const derivation = deriveChapterBeatPlanFromStoryBlock({ ...context, chapterNum }, chapterNum)
    const localSafetyDraft = derivation.content || buildLocalChapterBeatPlanFallback({ ...context, chapterNum }, chapterNum, originalText)
    diagnostics.derivedFallbackTriggered = true
    diagnostics.derivedFallbackSucceeded = Boolean(derivation.allowedToContinue && derivation.content?.trim())
    diagnostics.localSafetyDraftGenerated = Boolean(localSafetyDraft?.trim())
    diagnostics.localSafetyDraftLength = String(localSafetyDraft || '').length
    diagnostics.beatPlanSource = derivation.source
    diagnostics.derivedFromStoryBlock = Boolean(derivation.derivedFromStoryBlock)
    diagnostics.derivedReason = derivation.reason || reason || ''
    diagnostics.stageSnapshotFields = derivation.stageSnapshotFields || null
    diagnostics.whetherAllowedToContinue = Boolean(derivation.allowedToContinue)
    diagnostics.derivationIssues = derivation.issues || []
    if (derivation.allowedToContinue && derivation.content?.trim()) {
      chapterBeatPlan.value = derivation.content
      beatPlanSource.value = BEAT_PLAN_SOURCES.derivedFromStoryBlock
      beatPlanQualityNotice.value = {
        source: BEAT_PLAN_SOURCES.derivedFromStoryBlock,
        chapterNum,
        content: derivation.content,
        requiresReview: false,
        originalLength: String(originalText || '').length,
        fallbackLength: derivation.content.length,
        issues: [reason || 'beat_plan_recovery_derived'],
        derivedReason: derivation.reason,
        stageSnapshotFields: derivation.stageSnapshotFields,
        message: 'AI 小纲不可用，已使用故事块阶段派生小纲继续。'
      }
      return { allowed: true, content: derivation.content, derivation, localSafetyDraft }
    }
    if (localSafetyDraft?.trim()) {
      chapterBeatPlan.value = localSafetyDraft
      beatPlanSource.value = BEAT_PLAN_SOURCES.localSafetyRequiresReview
      beatPlanQualityNotice.value = {
        source: BEAT_PLAN_SOURCES.localSafetyRequiresReview,
        chapterNum,
        content: localSafetyDraft,
        requiresReview: true,
        originalLength: String(originalText || '').length,
        fallbackLength: localSafetyDraft.length,
        issues: derivation.issues?.length ? derivation.issues : [reason || 'beat_plan_recovery_failed'],
        derivedReason: derivation.reason,
        stageSnapshotFields: derivation.stageSnapshotFields,
        message: 'AI 小纲不可用，且故事块阶段快照不足以自动派生，请审阅后再继续。'
      }
    }
    return { allowed: false, content: '', derivation, localSafetyDraft }
  }

  async function repairProseRhythmIfNeeded(provider, chapterNum, content, context = {}) {
    const original = String(content || '').trim()
    const analysis = analyzeProseRhythm(original)
    if (!shouldRepairProseRhythm(analysis)) return original

    try {
      const result = await chatCompletion(provider, [
        { role: 'system', content: buildProseRhythmRepairSystemPrompt() },
        {
          role: 'user',
          content: buildProseRhythmRepairPrompt({
            chapterNum,
            content: original,
            analysis,
            beatPlan: context?.beatPlan,
            context
          })
        }
      ], { maxTokens: 8192, temperature: 0.28 })

      const repaired = cleanGeneratedChapterText(extractAiContent(result))
      const repairedAnalysis = analyzeProseRhythm(repaired)
      const originalCount = Math.max(countCjkChars(original), 1)
      const repairedCount = countCjkChars(repaired)
      const drift = repairedCount / originalCount
      const originalNarrative = analyzeNarrativeReadability({
        content: original,
        beatPlan: context?.beatPlan || ''
      })
      const repairedNarrative = analyzeNarrativeReadability({
        content: repaired,
        beatPlan: context?.beatPlan || ''
      })
      const originalNarrativeIssueTypes = new Set((originalNarrative.issues || []).map(item => item.type))
      const repairedHardNarrativeRegression = (repairedNarrative.gate === 'fail' && originalNarrative.gate !== 'fail') ||
        (repairedNarrative.issues || []).some(item =>
          ['paragraph_level_repetition', 'template_level_repetition', 'unreadable_chapter', 'concept_spinning'].includes(item.type) &&
          ['critical', 'severe', 'major'].includes(String(item.severity || '').toLowerCase()) &&
          !originalNarrativeIssueTypes.has(item.type)
        )
      const wordTarget = context?.wordTarget
      if (
        repaired &&
        wordTarget?.hardMin &&
        wordTarget?.hardMax &&
        (repairedCount < wordTarget.hardMin || repairedCount > wordTarget.hardMax)
      ) {
        console.warn('正文节奏修订稿字数越过硬边界，保留原稿', {
          repairedCount,
          hardMin: wordTarget.hardMin,
          hardMax: wordTarget.hardMax
        })
        return original
      }
      if (repairedHardNarrativeRegression) {
        console.warn('正文节奏修订稿叙事可读性退化，保留原稿', {
          before: originalNarrative.gate,
          after: repairedNarrative.gate,
          issues: repairedNarrative.issues?.map(item => item.type)
        })
        return original
      }
      const aiRiskWorsened = Number(repairedAnalysis?.aiContrastCount || 0) > Number(analysis?.aiContrastCount || 0) + 2
      const improved =
        repaired &&
        repaired !== original &&
        shouldAcceptProseRhythmRepair(analysis, repairedAnalysis, drift, {
          allowControlledDrift: true,
          narrativeRegression: false,
          aiRiskWorsened
        })

      if (improved) return repaired

      const localCandidate = buildLocalProseRhythmRepairCandidate(original)
      const localAnalysis = analyzeProseRhythm(localCandidate)
      const localNarrative = analyzeNarrativeReadability({
        content: localCandidate,
        beatPlan: context?.beatPlan || ''
      })
      const localNarrativeRegression = (localNarrative.gate === 'fail' && originalNarrative.gate !== 'fail') ||
        (localNarrative.issues || []).some(item =>
          ['paragraph_level_repetition', 'template_level_repetition', 'unreadable_chapter', 'concept_spinning'].includes(item.type) &&
          ['critical', 'severe', 'major'].includes(String(item.severity || '').toLowerCase()) &&
          !originalNarrativeIssueTypes.has(item.type)
        )
      const localCount = countCjkChars(localCandidate)
      const localDrift = localCount / originalCount
      const localInRange = !wordTarget?.hardMin || !wordTarget?.hardMax ||
        (localCount >= wordTarget.hardMin && localCount <= wordTarget.hardMax)
      const localImproved =
        localCandidate &&
        localCandidate !== original &&
        localInRange &&
        !localNarrativeRegression &&
        shouldAcceptProseRhythmRepair(analysis, localAnalysis, localDrift, {
          allowControlledDrift: false,
          narrativeRegression: false,
          aiRiskWorsened: false
        })

      if (localImproved) return localCandidate
      console.warn('正文节奏修订未带来稳定改善，保留原稿', {
        before: analysis,
        after: repairedAnalysis,
        drift
      })
    } catch (e) {
      console.warn('正文节奏修订失败，保留原稿:', e.message)
    }
    return original
  }

  async function repairNotXButYIfNeeded(provider, chapterNum, content, context = {}) {
    const original = String(content || '').trim()
    const analysis = analyzeProseRhythm(original)
    if (Number(analysis.aiContrastCount || 0) <= 2) return original

    try {
      const result = await chatCompletion(provider, [
        { role: 'system', content: buildNotXButYRepairSystemPrompt() },
        {
          role: 'user',
          content: buildNotXButYRepairPrompt({
            chapterNum,
            content: original,
            analysis,
            beatPlan: context?.beatPlan,
            context
          })
        }
      ], { maxTokens: CHAPTER_DRAFT_MAX_TOKENS, temperature: 0.22 })

      const repaired = cleanGeneratedChapterText(extractAiContent(result))
      const repairedAnalysis = analyzeProseRhythm(repaired)
      const originalCount = Math.max(countCjkChars(original), 1)
      const repairedCount = countCjkChars(repaired)
      const drift = repairedCount / originalCount
      const originalNarrative = analyzeNarrativeReadability({
        content: original,
        beatPlan: context?.beatPlan || ''
      })
      const repairedNarrative = analyzeNarrativeReadability({
        content: repaired,
        beatPlan: context?.beatPlan || ''
      })
      const narrativeRegression = repairedNarrative.gate === 'fail' && originalNarrative.gate !== 'fail'
      const wordTarget = context?.wordTarget
      const inRange = !wordTarget?.hardMin || !wordTarget?.hardMax ||
        (repairedCount >= wordTarget.hardMin && repairedCount <= wordTarget.hardMax)
      if (
        repaired &&
        repaired !== original &&
        inRange &&
        shouldAcceptNotXButYRepair(analysis, repairedAnalysis, drift, { narrativeRegression })
      ) {
        return repaired
      }
      console.warn('反差句专项轻修订未采用，保留原稿', {
        before: analysis.aiContrastCount,
        after: repairedAnalysis.aiContrastCount,
        drift,
        narrativeRegression
      })
    } catch (e) {
      console.warn('反差句专项轻修订失败，保留原稿', e.message)
    }
    const segmentRepaired = await repairNotXButYSegmentsIfNeeded(provider, chapterNum, original, analysis, context)
    return segmentRepaired || original
  }

  function parseJsonObject(text = '') {
    const source = String(text || '').trim()
      .replace(/^```(?:json)?/i, '')
      .replace(/```$/i, '')
      .trim()
    const start = source.indexOf('{')
    const end = source.lastIndexOf('}')
    if (start < 0 || end <= start) return {}
    try {
      return JSON.parse(source.slice(start, end + 1))
    } catch {
      return {}
    }
  }

  async function repairNotXButYSegmentsIfNeeded(provider, chapterNum, original, analysis, context = {}) {
    const segments = extractNotXButYRepairSegments(original)
    if (!segments.length) return original
    try {
      const result = await chatCompletion(provider, [
        { role: 'system', content: 'You repair only exact sentence groups. Return strict JSON only.' },
        {
          role: 'user',
          content: buildNotXButYSegmentRepairPrompt({
            chapterNum,
            segments,
            analysis,
            beatPlan: context?.beatPlan,
            context
          })
        }
      ], { maxTokens: 2200, temperature: 0.18 })
      const payload = parseJsonObject(extractAiContent(result))
      const repaired = applyNotXButYSegmentReplacements(original, payload?.replacements || [])
      const repairedAnalysis = analyzeProseRhythm(repaired)
      const originalNarrative = analyzeNarrativeReadability({
        content: original,
        beatPlan: context?.beatPlan || ''
      })
      const repairedNarrative = analyzeNarrativeReadability({
        content: repaired,
        beatPlan: context?.beatPlan || ''
      })
      const narrativeRegression = repairedNarrative.gate === 'fail' && originalNarrative.gate !== 'fail'
      if (
        repaired &&
        repaired !== original &&
        shouldAcceptNotXButYSegmentRepair(analysis, repairedAnalysis, repaired, original, { narrativeRegression })
      ) {
        return repaired
      }
      console.warn('notXButY segment repair rejected', {
        before: analysis.aiContrastCount,
        after: repairedAnalysis.aiContrastCount,
        narrativeRegression
      })
    } catch (e) {
      console.warn('notXButY segment repair failed', e.message)
    }
    return original
  }

  async function repairParagraphRepetitionIfNeeded(provider, chapterNum, content, context = {}) {
    const original = String(content || '').trim()
    const before = analyzeNarrativeReadability({
      content: original,
      beatPlan: context?.beatPlan || ''
    })
    if (!(before.issues || []).some(item => item.type === 'paragraph_level_repetition')) return original
    try {
      const result = await chatCompletion(provider, [
        { role: 'system', content: 'You are a longform fiction line editor. Repair repetition only. Output full chapter text only.' },
        {
          role: 'user',
          content: buildParagraphRepetitionRepairPrompt({
            chapterNum,
            content: original,
            analysis: before,
            beatPlan: context?.beatPlan,
            context
          })
        }
      ], { maxTokens: 6200, temperature: 0.24 })
      const repaired = cleanGeneratedChapterText(extractAiContent(result))
      const after = analyzeNarrativeReadability({
        content: repaired,
        beatPlan: context?.beatPlan || ''
      })
      const repairedCount = countCjkChars(repaired)
      const wordTarget = context?.wordTarget
      const inRange = !wordTarget?.hardMin || !wordTarget?.hardMax ||
        (repairedCount >= wordTarget.hardMin && repairedCount <= wordTarget.hardMax)
      if (
        repaired &&
        repaired !== original &&
        inRange &&
        shouldAcceptNarrativeReadabilityRepair(before, after, repaired, original)
      ) {
        return repaired
      }
      console.warn('paragraph repetition repair rejected', {
        before: before.gate,
        after: after.gate,
        issues: (after.issues || []).map(item => item.type)
      })
    } catch (e) {
      console.warn('paragraph repetition repair failed', e.message)
    }
    return original
  }

  async function resolveTaskProvider(projectId, bindingKeys = [], providerId = null) {
    const providerStore = useProviderStore()
    const fallbackProjectId = projectId || useProjectStore().currentProject?.id || currentChapter.value?.projectId || currentChapter.value?.project_id
    return providerStore.resolveTaskProvider({
      projectId: fallbackProjectId,
      bindingKeys,
      providerId,
      taskName: bindingKeys.join('/') || 'writer_task'
    })
  }

  async function syncProjectCurrentChapter(projectId, chapterNum) {
    try {
      const projectStore = useProjectStore()
      await projectStore.updateCurrentChapterNum(projectId, chapterNum)
    } catch (e) {
      console.warn('同步项目当前章节失败:', e.message)
    }
  }

  // === 章节管理 ===
  async function loadChapters(projectId) {
    loading.value = true
    try {
      chapters.value = await api.chapters.list(projectId)
      return chapters.value
    } catch (e) {
      console.error('加载章节列表失败:', e.message)
      throw e
    } finally {
      loading.value = false
    }
  }

  async function getOrCreateChapter(projectId, chapterNum) {
    try {
      const existing = chapters.value.find(c => c.chapterNum === chapterNum)
      if (existing) {
        currentChapter.value = existing
        return existing
      }
      const chapter = await api.chapters.create(projectId, { chapterNum, title: `第 ${chapterNum} 章` })
      chapters.value.push(chapter)
      chapters.value.sort((a, b) => a.chapterNum - b.chapterNum)
      currentChapter.value = chapter
      return chapter
    } catch (e) {
      console.error('获取/创建章节失败:', e.message)
      throw e
    }
  }

  async function bulkCreateEmptyChapters(projectId, targetChapters) {
    const total = Number(targetChapters || 0)
    if (!projectId || total < 1) return []

    const existingNums = new Set(chapters.value.map(ch => Number(ch.chapterNum)))
    const created = []

    for (let chapterNum = 1; chapterNum <= total; chapterNum += 1) {
      if (existingNums.has(chapterNum)) continue
      const chapter = await api.chapters.create(projectId, {
        chapterNum,
        title: `第 ${chapterNum} 章`
      })
      created.push(chapter)
      chapters.value.push(chapter)
      existingNums.add(chapterNum)
    }

    chapters.value.sort((a, b) => a.chapterNum - b.chapterNum)
    return created
  }

  async function bulkCreateEmptyChapterRange(projectId, startChapter, endChapter) {
    const start = Number(startChapter || 0)
    const end = Number(endChapter || 0)
    if (!projectId || start < 1 || end < start) return []

    const existingNums = new Set(chapters.value.map(ch => Number(ch.chapterNum)))
    const created = []

    for (let chapterNum = start; chapterNum <= end; chapterNum += 1) {
      if (existingNums.has(chapterNum)) continue
      const chapter = await api.chapters.create(projectId, {
        chapterNum,
        title: `第 ${chapterNum} 章`
      })
      created.push(chapter)
      chapters.value.push(chapter)
      existingNums.add(chapterNum)
    }

    chapters.value.sort((a, b) => a.chapterNum - b.chapterNum)
    return created
  }

  async function updateChapter(chapter) {
    try {
      const pid = chapter.projectId || chapter.project_id
      const data = {
        title: chapter.title,
        status: chapter.status,
        summary: chapter.summary,
        wordCount: chapter.wordCount || (chapter.content?.length || 0),
        finalVersionId: chapter.finalVersionId
      }
      const updated = await api.chapters.update(pid, chapter.id, data)
      const idx = chapters.value.findIndex(c => c.id === chapter.id)
      if (idx !== -1) chapters.value[idx] = { ...chapter, ...updated }
      if (currentChapter.value?.id === chapter.id) currentChapter.value = { ...chapter, ...updated }
    } catch (e) {
      console.error('更新章节失败:', e.message)
      throw e
    }
  }

  async function generateDefaultChapterTitle(projectId, chapter, chapterNum, content, context, provider, options = {}) {
    if (!projectId || !chapter?.id || !content) return ''
    if (!options.force && !isDefaultChapterTitle(chapter.title, chapterNum)) return chapter.title || ''
    const resolvedProvider = provider || await resolveTaskProvider(projectId, ['summaryModelId', 'writingModelId'])
    const existingTitles = chapters.value
      .filter(item => item.id !== chapter.id)
      .map(item => item.title)
      .filter(Boolean)
    const titleContext = {
      chapterNum,
      chapterGoal: context?.chapterGoal,
      beatPlan: context?.beatPlan,
      content,
      existingTitles
    }

    const messages = [
      { role: 'system', content: buildChapterTitleSystemPrompt() },
      {
        role: 'user',
        content: buildChapterTitlePrompt(titleContext)
      }
    ]

    const result = await chatCompletion(resolvedProvider, messages, { maxTokens: 80, temperature: 0.35 })
    const rawTitle = extractAiContent(result)
    let title = cleanGeneratedChapterTitle(rawTitle, titleContext)
    if (!title) {
      const retryResult = await chatCompletion(resolvedProvider, [
        { role: 'system', content: buildChapterTitleSystemPrompt() },
        {
          role: 'user',
          content: [
            '上一次输出不符合小说目录章名 JSON 候选格式，或候选不可用，请重新给出朴素直接的目录标题候选。',
            `上一次输出：${rawTitle}`,
            buildChapterTitlePrompt(titleContext),
            '只输出 JSON。生成 3-5 个 candidates；标题优先 1-6 个汉字，可以是人物、地点、功法、武器、组织、道具、事件、冲突或结果。不要输出完整句子，不要和最近章节完全同名。'
          ].join('\n\n')
        }
      ], { maxTokens: 80, temperature: 0.25 })
      title = cleanGeneratedChapterTitle(extractAiContent(retryResult), titleContext)
    }
    if (!title) {
      title = deriveFallbackChapterTitle(titleContext)
    }
    if (!title) return ''

    const updated = await api.chapters.updateTitle(projectId, chapter.id, { title })
    const idx = chapters.value.findIndex(c => c.id === chapter.id)
    if (idx !== -1) chapters.value[idx] = { ...chapters.value[idx], ...updated }
    if (currentChapter.value?.id === chapter.id) currentChapter.value = { ...currentChapter.value, ...updated }
    return title
  }

  async function updateChapterTitle(projectId, chapterId, title) {
    const updated = await api.chapters.updateTitle(projectId, chapterId, { title })
    const idx = chapters.value.findIndex(c => c.id === chapterId)
    if (idx !== -1) chapters.value[idx] = { ...chapters.value[idx], ...updated }
    if (currentChapter.value?.id === chapterId) currentChapter.value = { ...currentChapter.value, ...updated }
    return updated
  }

  async function deleteChapter(id) {
    try {
      const ch = chapters.value.find(c => c.id === id)
      if (!ch) return
      await api.chapters.delete(ch.projectId || ch.project_id, id)
      chapters.value = chapters.value.filter(c => c.id !== id)
      if (currentChapter.value?.id === id) currentChapter.value = null
    } catch (e) {
      console.error('删除章节失败:', e.message)
      throw e
    }
  }

  // === 版本管理 ===
  async function loadVersions(projectId, chapterId) {
    try {
      versions.value = await api.versions.list(projectId, chapterId)
      return versions.value
    } catch (e) {
      console.error('加载版本列表失败:', e.message)
      throw e
    }
  }

  async function createVersion(projectId, chapterId, chapterNum, data) {
    try {
      const version = await api.versions.create(projectId, chapterId, {
        title: data.title || '',
        content: data.content || '',
        versionType: data.versionType || 'ai_candidate',
        sourceModelId: data.sourceModelId || null,
        promptBrief: data.promptBrief || ''
      })
      versions.value.unshift(version)
      return version
    } catch (e) {
      console.error('创建版本失败:', e.message)
      throw e
    }
  }

  async function updateVersion(version) {
    try {
      const pid = version.projectId || version.project_id
      const cid = version.chapterId || version.chapter_id
      const updated = await api.versions.update(pid, cid, version.id, {
        title: version.title,
        content: version.content,
        versionType: version.versionType
      })
      const idx = versions.value.findIndex(v => v.id === version.id)
      if (idx !== -1) versions.value[idx] = updated
      if (currentVersion.value?.id === version.id) currentVersion.value = updated
    } catch (e) {
      console.error('更新版本失败:', e.message)
      throw e
    }
  }

  async function deleteVersion(id) {
    try {
      const v = versions.value.find(v => v.id === id)
      if (!v) return
      const pid = v.projectId || v.project_id
      const cid = v.chapterId || v.chapter_id
      await api.versions.delete(pid, cid, id)
      versions.value = versions.value.filter(v => v.id !== id)
      if (currentVersion.value?.id === id) currentVersion.value = null
    } catch (e) {
      console.error('删除版本失败:', e.message)
      throw e
    }
  }

  // === 自动保存草稿 ===
  async function saveTempDraft(projectId, chapterNum, content) {
    try {
      await api.tempDrafts.save(projectId, chapterNum, content)
      tempDraft.value = { projectId, chapterNum, content, savedAt: Date.now() }
    } catch (e) {
      console.error('保存草稿失败:', e.message)
      // 静默失败，不中断用户输入
    }
  }

  async function loadTempDraft(projectId, chapterNum) {
    try {
      tempDraft.value = await api.tempDrafts.get(projectId, chapterNum)
      return tempDraft.value
    } catch (e) {
      console.error('加载草稿失败:', e.message)
      tempDraft.value = null
      return null
    }
  }

  async function clearTempDraft(projectId, chapterNum) {
    try {
      await api.tempDrafts.delete(projectId, chapterNum)
      tempDraft.value = null
    } catch (e) {
      console.error('清除草稿失败:', e.message)
    }
  }

  // === 章节小纲持久化 ===
  async function loadChapterBeatPlan(projectId, chapterNum) {
    try {
      beatPlanRecord.value = await api.beatPlans.get(projectId, chapterNum)
      chapterBeatPlan.value = beatPlanRecord.value?.content || ''
      beatPlanSource.value = beatPlanRecord.value?.beatPlanSource || ''
      return beatPlanRecord.value
    } catch (e) {
      console.error('加载章节小纲失败:', e.message)
      beatPlanRecord.value = null
      chapterBeatPlan.value = ''
      beatPlanSource.value = ''
      return null
    }
  }

  async function saveChapterBeatPlan(projectId, chapterNum, content, metadata = {}) {
    try {
      const metadataWithSource = {
        ...metadata,
        beatPlanSource: metadata.beatPlanSource || beatPlanSource.value || null
      }
      beatPlanRecord.value = await api.beatPlans.save(projectId, chapterNum, content, metadataWithSource)
      chapterBeatPlan.value = beatPlanRecord.value?.content || content || ''
      beatPlanSource.value = beatPlanRecord.value?.beatPlanSource || metadataWithSource.beatPlanSource || ''
      return beatPlanRecord.value
    } catch (e) {
      console.error('保存章节小纲失败:', e.message)
      throw e
    }
  }

  async function clearChapterBeatPlan(projectId, chapterNum) {
    try {
      await api.beatPlans.delete(projectId, chapterNum)
      beatPlanRecord.value = null
      chapterBeatPlan.value = ''
      beatPlanSource.value = ''
    } catch (e) {
      console.error('清除章节小纲失败:', e.message)
      throw e
    }
  }

  // === AI 生成章前小纲 ===
  async function generateChapterBeatPlan(projectId, chapterNum, context, providerId) {
    beatPlanning.value = true
    beatPlanQualityNotice.value = null
    beatPlanDiagnostics.value = null
    beatPlanSource.value = ''
    let diagnostics = null
    try {
      const provider = await resolveTaskProvider(projectId, ['outlineModelId', 'writingModelId'], providerId)
      const promptBuild = buildScenePlanPromptWithDiagnostics({ chapterNum, ...context })

      const messages = [
        { role: 'system', content: buildChapterBeatSystemPrompt() },
        { role: 'user', content: promptBuild.prompt }
      ]

      diagnostics = {
        ...promptBuild.diagnostics,
        providerId: provider.id,
        modelName: provider.model || provider.name || '',
        supportsJSON: provider.supportsJSON !== false && provider.supports_json !== false,
        promptChars: messages.reduce((sum, message) => sum + String(message.content || '').length, 0),
        promptTokensApprox: estimatePromptTokens(messages.map(message => message.content || '').join('\n')),
        promptDiagnostics: promptBuild.diagnostics,
        attempts: [],
        failureStage: '',
        beatPlanSource: '',
        derivedFromStoryBlock: false,
        derivedReason: '',
        stageSnapshotFields: null,
        whetherAllowedToContinue: null,
        parseRetryTriggered: false,
        parseRetrySucceeded: false,
        repairTriggered: false,
        repairSucceeded: false,
        derivedFallbackTriggered: false,
        derivedFallbackSucceeded: false,
        finalFailureAfterRecovery: false
      }
      saveBeatPlanDiagnostics(projectId, chapterNum, diagnostics)
      let result = await chatCompletion(provider, messages, {
        maxTokens: BEAT_PLAN_INITIAL_MAX_TOKENS,
        temperature: 0.6,
        returnRaw: true,
        projectId,
        taskName: 'outline_beat_plan_generation'
      })
      let raw = extractAiContent(result)
      let content = cleanChapterBeatPlanText(raw)
      const firstResponseDiagnostics = appendBeatPlanAttemptDiagnostics(diagnostics, {
        attempt: 1,
        reason: 'initial',
        maxTokens: BEAT_PLAN_INITIAL_MAX_TOKENS,
        messages,
        promptDiagnostics: promptBuild.diagnostics,
        result,
        raw,
        content,
        forceMinimal: false,
      })
      saveBeatPlanDiagnostics(projectId, chapterNum, diagnostics)
      if (!content.trim()) {
        const emptyLengthRetry = isEmptyLengthAiResponse(result, content)
        const retryMaxTokens = emptyLengthRetry ? BEAT_PLAN_EMPTY_LENGTH_RETRY_MAX_TOKENS : BEAT_PLAN_INITIAL_MAX_TOKENS
        const retryThinking = resolveBeatPlanRetryThinking(provider, emptyLengthRetry)
        const retryPromptBuild = buildScenePlanPromptWithDiagnostics({ chapterNum, ...context }, { forceMinimal: true })
        const retryMessages = [
          { role: 'system', content: buildChapterBeatSystemPrompt() },
          {
            role: 'user',
            content: [
              '上一次模型返回了空小纲。请重新生成第 ' + chapterNum + ' 章场景型小纲。',
              '必须输出可保存的小纲内容，不要输出空文本、寒暄、解释或 Markdown 代码块。',
              retryPromptBuild.prompt
            ].join('\n\n')
          }
        ]
        diagnostics.retryPromptDiagnostics = retryPromptBuild.diagnostics
        diagnostics.emptyLengthRetryBoosted = emptyLengthRetry
        diagnostics.retryMaxTokens = retryMaxTokens
        diagnostics.retryThinking = retryThinking || null
        result = await chatCompletion(provider, retryMessages, {
          maxTokens: retryMaxTokens,
          temperature: 0.45,
          thinking: retryThinking,
          returnRaw: true,
          projectId,
          taskName: 'outline_beat_plan_generation_retry'
        })
        raw = extractAiContent(result)
        content = cleanChapterBeatPlanText(raw)
        appendBeatPlanAttemptDiagnostics(diagnostics, {
          attempt: diagnostics.attempts.length + 1,
          reason: 'empty_retry',
          maxTokens: retryMaxTokens,
          thinkingOverride: retryThinking || null,
          messages: retryMessages,
          promptDiagnostics: retryPromptBuild.diagnostics,
          result,
          raw,
          content,
          forceMinimal: true,
        })
        saveBeatPlanDiagnostics(projectId, chapterNum, diagnostics)
      }
      if (!content.trim()) {
        const derived = applyDerivedBeatPlanFallback(chapterNum, context, diagnostics, 'empty_ai_response_after_retry', '')
        diagnostics.failureStage = derived.allowed ? '' : 'beat_plan_requires_review'
        saveBeatPlanDiagnostics(projectId, chapterNum, diagnostics)
        if (derived.allowed) return derived.content
        const error = new Error(`beat_plan_requires_review: 第 ${chapterNum} 章小纲需要人工审阅，故事块阶段快照不足以自动派生。`)
        error.code = BEAT_PLAN_REQUIRES_REVIEW
        error.diagnostics = diagnostics
        error.localSafetyBeatPlan = derived.localSafetyDraft
        error.requiresReview = true
        throw error
      }
      let recoveryUsed = false
      let candidateDiagnostics = buildBeatPlanCandidateDiagnostics(chapterNum, content, context)
      Object.assign(diagnostics, candidateDiagnostics)
      saveBeatPlanDiagnostics(projectId, chapterNum, diagnostics)
      const latestAttempt = diagnostics.attempts[diagnostics.attempts.length - 1] || null
      const latestResponseDiagnostics = latestAttempt?.responseDiagnostics || firstResponseDiagnostics
      const originalRecoveryRaw = content
      if (shouldTriggerBeatPlanParseRecovery(candidateDiagnostics, latestResponseDiagnostics, content)) {
        diagnostics.parseRetryTriggered = true
        diagnostics.failureStage = 'beat_plan_parse_retry'
        const parseRetryThinking = resolveBeatPlanRetryThinking(provider, true)
        const parseRetryMessages = [
          { role: 'system', content: '你是小纲 JSON 恢复器。只输出合法 JSON，不写正文，不解释。' },
          {
            role: 'user',
            content: buildChapterBeatPlanParseRetryPrompt({
              chapterNum,
              previousCandidate: content,
              contextBrief: buildBeatPlanRecoveryContextBrief(context, chapterNum)
            })
          }
        ]
        result = await chatCompletion(provider, parseRetryMessages, {
          maxTokens: BEAT_PLAN_EMPTY_LENGTH_RETRY_MAX_TOKENS,
          temperature: 0.25,
          thinking: parseRetryThinking,
          returnRaw: true,
          projectId,
          taskName: 'outline_beat_plan_parse_retry'
        })
        raw = extractAiContent(result)
        content = cleanChapterBeatPlanText(raw)
        appendBeatPlanAttemptDiagnostics(diagnostics, {
          attempt: diagnostics.attempts.length + 1,
          reason: 'parse_retry',
          maxTokens: BEAT_PLAN_EMPTY_LENGTH_RETRY_MAX_TOKENS,
          thinkingOverride: parseRetryThinking || null,
          messages: parseRetryMessages,
          result,
          raw,
          content,
          forceMinimal: true
        })
        candidateDiagnostics = buildBeatPlanCandidateDiagnostics(chapterNum, content, context)
        Object.assign(diagnostics, candidateDiagnostics)
        diagnostics.parseRetrySucceeded = candidateDiagnostics.candidateFailureCode !== 'beat_plan_parse_failed'
        recoveryUsed = diagnostics.parseRetrySucceeded
        saveBeatPlanDiagnostics(projectId, chapterNum, diagnostics)
      }
      if (diagnostics.parseRetryTriggered && candidateDiagnostics.candidateFailureCode === 'beat_plan_parse_failed') {
        diagnostics.repairTriggered = true
        diagnostics.failureStage = 'beat_plan_json_repair'
        const repairSourceRaw = [originalRecoveryRaw, content]
          .map(item => String(item || '').trim())
          .sort((a, b) => b.length - a.length)[0] || ''
        const repairMessages = [
          { role: 'system', content: '你是小纲 JSON 修复器。只修复 JSON，不写新剧情，不解释。' },
          {
            role: 'user',
            content: buildChapterBeatPlanJsonRepairPrompt({
              chapterNum,
              candidateRaw: repairSourceRaw
            })
          }
        ]
        result = await chatCompletion(provider, repairMessages, {
          maxTokens: BEAT_PLAN_EMPTY_LENGTH_RETRY_MAX_TOKENS,
          temperature: 0.12,
          returnRaw: true,
          projectId,
          taskName: 'outline_beat_plan_json_repair'
        })
        raw = extractAiContent(result)
        content = cleanChapterBeatPlanText(raw)
        appendBeatPlanAttemptDiagnostics(diagnostics, {
          attempt: diagnostics.attempts.length + 1,
          reason: 'json_repair',
          maxTokens: BEAT_PLAN_EMPTY_LENGTH_RETRY_MAX_TOKENS,
          messages: repairMessages,
          result,
          raw,
          content,
          forceMinimal: true
        })
        candidateDiagnostics = buildBeatPlanCandidateDiagnostics(chapterNum, content, context)
        Object.assign(diagnostics, candidateDiagnostics)
        diagnostics.repairSucceeded = candidateDiagnostics.candidateFailureCode !== 'beat_plan_parse_failed'
        recoveryUsed = recoveryUsed || diagnostics.repairSucceeded
        saveBeatPlanDiagnostics(projectId, chapterNum, diagnostics)
      }
      if (diagnostics.parseRetryTriggered && candidateDiagnostics.candidateFailureCode === 'beat_plan_parse_failed') {
        const derived = applyDerivedBeatPlanFallback(chapterNum, context, diagnostics, 'parse_recovery_failed', content || originalRecoveryRaw)
        diagnostics.failureStage = derived.allowed ? '' : 'beat_plan_parse_failed'
        saveBeatPlanDiagnostics(projectId, chapterNum, diagnostics)
        if (derived.allowed) return derived.content
        diagnostics.finalFailureAfterRecovery = true
        diagnostics.failureStage = 'beat_plan_parse_failed'
        const finalDiagnostics = buildBeatPlanQualityDiagnostics(chapterNum, {}, {
          ...candidateDiagnostics,
          failureCode: 'beat_plan_parse_failed',
          finalBeatPlanLength: String(content || '').length
        })
        beatPlanQualityDiagnostics.value = finalDiagnostics
        diagnostics.beatPlanQualityDiagnostics = finalDiagnostics
        saveBeatPlanDiagnostics(projectId, chapterNum, diagnostics)
        const error = new Error(`第 ${chapterNum} 章小纲解析失败：${candidateDiagnostics.parseError || 'JSON 解析失败'}。parse-retry、JSON repair 和故事块派生均未恢复成功。`)
        error.code = 'beat_plan_parse_failed'
        error.diagnostics = finalDiagnostics
        throw error
      }
      const preQualityIssues = collectStructuredBeatPlanIssues(parseStructuredBeatPlan(content))
      content = await ensureChapterBeatPlanQuality(provider, chapterNum, content, context)
      Object.assign(diagnostics, buildBeatPlanCandidateDiagnostics(chapterNum, content, context))
      chapterBeatPlan.value = content
      const aiSource = recoveryUsed ||
        preQualityIssues.missingRequiredFields.length ||
        preQualityIssues.placeholderFields?.length ||
        preQualityIssues.volumeGoalHandoffStatus === 'fail' ||
        preQualityIssues.turnDecisionStatus === 'fail'
        ? BEAT_PLAN_SOURCES.aiRepaired
        : BEAT_PLAN_SOURCES.aiGenerated
      beatPlanSource.value = aiSource
      diagnostics.beatPlanSource = aiSource
      diagnostics.derivedFromStoryBlock = false
      diagnostics.derivedReason = ''
      diagnostics.whetherAllowedToContinue = true
      saveBeatPlanDiagnostics(projectId, chapterNum, diagnostics)
      return content
    } catch (e) {
      if (diagnostics && e?.code === 'beat_plan_empty_after_quality_cleaning') {
        Object.assign(diagnostics, {
          failureStage: 'beat_plan_empty_after_quality_cleaning',
          candidateFailureCode: 'beat_plan_empty_after_quality_cleaning',
          candidateRaw: e.diagnostics?.candidateRaw || diagnostics.candidateRaw || '',
          qualityGateInput: e.diagnostics?.qualityGateInput || diagnostics.qualityGateInput || '',
          qualityGateResult: e.diagnostics?.qualityGateResult || diagnostics.qualityGateResult || null,
          beatPlanQualityDiagnostics: e.diagnostics || diagnostics.beatPlanQualityDiagnostics || null
        })
        const derived = applyDerivedBeatPlanFallback(
          chapterNum,
          context,
          diagnostics,
          'beat_plan_empty_after_quality_cleaning',
          diagnostics.candidateRaw || ''
        )
        diagnostics.failureStage = derived.allowed ? '' : 'beat_plan_requires_review'
        if (!derived.allowed) diagnostics.finalFailureAfterRecovery = true
        saveBeatPlanDiagnostics(projectId, chapterNum, diagnostics)
        if (derived.allowed) return derived.content
        const error = new Error(`beat_plan_requires_review: 第 ${chapterNum} 章小纲为空，且故事块阶段快照不足以自动派生。`)
        error.code = BEAT_PLAN_REQUIRES_REVIEW
        error.diagnostics = diagnostics
        error.localSafetyBeatPlan = derived.localSafetyDraft
        error.requiresReview = true
        throw error
      }
      if (diagnostics && e?.diagnostics) {
        Object.assign(diagnostics, {
          failureStage: e.code || e.diagnostics.failureCode || diagnostics.failureStage || '',
          candidateFailureCode: e.diagnostics.failureCode || e.code || diagnostics.candidateFailureCode || '',
          candidateRaw: e.diagnostics.candidateRaw || diagnostics.candidateRaw || '',
          parsedCandidate: e.diagnostics.parsedCandidate || diagnostics.parsedCandidate || null,
          qualityGateInput: e.diagnostics.qualityGateInput || diagnostics.qualityGateInput || '',
          qualityGateResult: e.diagnostics.qualityGateResult || diagnostics.qualityGateResult || null,
          parseError: e.diagnostics.parseError || diagnostics.parseError || '',
          beatPlanQualityDiagnostics: e.diagnostics
        })
        saveBeatPlanDiagnostics(projectId, chapterNum, diagnostics)
      }
      console.error('生成章前小纲失败:', e.message)
      throw e
    } finally {
      beatPlanning.value = false
    }
  }

  // === AI 生成章节（流式） ===
  async function generateChapter(projectId, chapterNum, context, providerId, onStream) {
    generating.value = true
    generationStream.value = ''
    beatPlanQualityNotice.value = null
    try {
      const provider = await resolveTaskProvider(projectId, ['writingModelId'], providerId)
      if (context?.beatPlan) {
        const ensuredBeatPlan = await ensureChapterBeatPlanQuality(provider, chapterNum, context.beatPlan, context)
        if (beatPlanQualityNotice.value?.source === 'local_safety_rebuild') {
          if (context?.beatPlanConfirmedByUser && ensuredBeatPlan?.trim()) {
            chapterBeatPlan.value = ensuredBeatPlan
            context = {
              ...context,
              beatPlan: ensuredBeatPlan,
              beatPlanSafetyRebuildAcknowledged: true
            }
            beatPlanQualityNotice.value = {
              ...beatPlanQualityNotice.value,
              source: 'local_safety_rebuild_acknowledged',
              message: '已使用确认后的安全小纲继续生成正文。'
            }
          } else {
            chapterBeatPlan.value = ensuredBeatPlan
            const error = new Error(beatPlanQualityNotice.value.message)
            error.code = 'BEAT_PLAN_LOCAL_SAFETY_REBUILD'
            throw error
          }
        } else {
          context = { ...context, beatPlan: ensuredBeatPlan }
        }
      }

      const messages = [
        { role: 'system', content: buildChapterSystemPrompt() },
        { role: 'user', content: buildChapterPrompt({ chapterNum, ...context }) }
      ]

      let content = ''
      try {
        const stream = await chatCompletionStream(provider, messages, { maxTokens: CHAPTER_DRAFT_MAX_TOKENS, temperature: 0.64 })
        while (true) {
          const { done, delta } = await stream.readNext()
          if (delta) {
            content += delta
            generationStream.value = content
            if (onStream) onStream(content, delta)
          }
          if (done) break
        }
      } catch (streamErr) {
        console.warn('流式请求失败，回退到非流式:', streamErr.message)
        const result = await chatCompletion(provider, messages, { maxTokens: CHAPTER_DRAFT_MAX_TOKENS, temperature: 0.64 })
        content = extractAiContent(result, { preferOwnContent: false, unknownFallback: '' })
      }

      content = await runDraftRepairPipeline({
        rawContent: content,
        cleaner: cleanGeneratedChapterText,
        repairProseRhythm: draft => repairProseRhythmIfNeeded(provider, chapterNum, draft, context),
        repairNotXButY: draft => repairNotXButYIfNeeded(provider, chapterNum, draft, context),
        repairParagraphRepetition: draft => repairParagraphRepetitionIfNeeded(provider, chapterNum, draft, context),
        emptyDraftErrorMessage: 'AI 生成正文为空，请重新生成或切换模型后重试。'
      })
      generationStream.value = content
      if (onStream) onStream(content, '')

      const chapter = await getOrCreateChapter(projectId, chapterNum)
      let version = null
      try {
        version = await createVersion(projectId, chapter.id, chapterNum, {
          title: `第 ${chapterNum} 章 - AI 候选`,
          content,
          versionType: 'ai_candidate',
          sourceModelId: provider.id,
          promptBrief: context?.beatPlan ? '按确认小纲生成章节' : '章节生成'
        })
      } catch (saveError) {
        const error = new Error(`正文候选保存失败：${saveError.message || saveError}`)
        error.code = 'draft_save_failed'
        error.diagnostics = {
          chapterId: chapter.id,
          chapterNum,
          contentLength: content.length,
          sourceModelId: provider.id
        }
        throw error
      }
      await syncProjectCurrentChapter(projectId, chapterNum)
      currentVersion.value = version
      return version
    } finally {
      generating.value = false
    }
  }

  async function generateCorrectionDraft(projectId, chapterNum, taskOrTasks, originalContent, providerId) {
    generating.value = true
    try {
      const provider = await resolveTaskProvider(projectId, ['polishModelId', 'auditModelId', 'writingModelId'], providerId)

      const result = await chatCompletion(provider, [
        {
          role: 'user',
          content: buildCorrectionDraftPrompt({
            chapterNum,
            originalContent,
            tasks: normalizeCorrectionTasks(taskOrTasks)
          })
        }
      ], { maxTokens: 8192, temperature: 0.62 })

      const content = cleanGeneratedChapterText(extractAiContent(result))
      if (!content.trim()) {
        throw new Error('AI 生成纠偏草案为空，请重新生成或切换模型后重试。')
      }
      const chapter = await getOrCreateChapter(projectId, chapterNum)
      const taskCount = normalizeCorrectionTasks(taskOrTasks).length
      const version = await createVersion(projectId, chapter.id, chapterNum, {
        title: taskCount > 1 ? `第 ${chapterNum} 章 - 综合纠偏候选` : `第 ${chapterNum} 章 - 纠偏候选`,
        content,
        versionType: 'correction_candidate',
        sourceModelId: provider.id,
        promptBrief: buildCorrectionPromptBrief(taskOrTasks)
      })
      await syncProjectCurrentChapter(projectId, chapterNum)
      currentVersion.value = version
      return version
    } finally {
      generating.value = false
    }
  }

  async function generateLocalCorrectionPatchCandidate(projectId, chapterNum, issues, originalContent, providerId) {
    generating.value = true
    try {
      const provider = await resolveTaskProvider(projectId, ['polishModelId', 'auditModelId', 'writingModelId'], providerId)
      const normalizedIssues = (Array.isArray(issues) ? issues : []).map((item, index) => ({
        ...item,
        issueIndex: item?.issueIndex || item?.index || index + 1,
        replacement: item?.replacement || item?.replacementText || item?.rewrite || item?.fixedText || item?.newText || '',
        suggestion: item?.suggestion || ''
      }))

      const result = await chatCompletion(provider, [
        {
          role: 'user',
          content: buildCorrectionPatchPrompt({
            chapterNum,
            originalContent,
            issues: normalizedIssues
          })
        }
      ], { maxTokens: 4096, temperature: 0.35 })

      const text = extractAiContent(result)
      let patches = extractLocalRevisionPatches(text)
      if (!patches.length && text.trim()) {
        const repairResult = await chatCompletion(provider, [
          { role: 'user', content: buildCorrectionPatchRepairPrompt(text) }
        ], { maxTokens: 4096, temperature: 0 })
        patches = extractLocalRevisionPatches(extractAiContent(repairResult))
      }

      if (!patches.length) {
        const retryResult = await chatCompletion(provider, [
          {
            role: 'user',
            content: buildCorrectionPatchRetryPrompt({
              chapterNum,
              originalContent,
              issues: normalizedIssues,
              previousOutput: text
            })
          }
        ], { maxTokens: 4096, temperature: 0.2 })
        patches = extractLocalRevisionPatches(extractAiContent(retryResult))
      }

      if (!patches.length) {
        patches = buildLocalRevisionPatchesFromIssues(normalizedIssues)
      }

      const patchResult = applyLocalRevisionPatches(originalContent, patches)
      if (patchResult.applied.length) {
        const chapter = await getOrCreateChapter(projectId, chapterNum)
        const version = await createVersion(projectId, chapter.id, chapterNum, {
          title: `第 ${chapterNum} 章 - 局部修订候选`,
          content: patchResult.content,
          versionType: 'correction_candidate',
          sourceModelId: provider.id,
          promptBrief: `本章审稿局部修订：应用 ${patchResult.applied.length} 处，跳过 ${patchResult.skipped.length} 处`
        })
        await syncProjectCurrentChapter(projectId, chapterNum)
        currentVersion.value = version
        return { version, ...patchResult, mode: 'local_patch' }
      }

      const skippedReasons = patchResult.skipped
        .map(item => item.reason)
        .filter(Boolean)
      const reasonText = skippedReasons.length ? `跳过原因：${[...new Set(skippedReasons)].join('、')}。` : ''
      throw new Error(`AI 没有返回可安全应用的局部修订补丁，${reasonText}请使用审稿面板的“定位原文/替换”，或手动选区改写。`)
    } finally {
      generating.value = false
    }
  }

  // === AI 续写 ===
  async function continueWriting(currentContent, instruction, providerId, context = {}) {
    generating.value = true
    try {
      const provider = await resolveTaskProvider(context?.projectId, ['writingModelId'], providerId)
      const messages = [{ role: 'user', content: buildContinuePrompt(currentContent, instruction, context) }]
      return await chatCompletion(provider, messages, { maxTokens: 2048, temperature: 0.8 })
    } finally {
      generating.value = false
    }
  }

  // === AI 多候选生成 ===
  async function generateMultiVariants(projectId, chapterNum, context) {
    generating.value = true
    try {
      const provider = await resolveTaskProvider(projectId, ['writingModelId'])
      const messages = [
        { role: 'system', content: buildChapterSystemPrompt() },
        { role: 'user', content: buildMultiVariantPrompt({ chapterNum, ...context }) }
      ]
      const result = await chatCompletion(provider, messages, { maxTokens: 8192, temperature: 0.85 })
      const content = extractAiContent(result, { preferOwnContent: false, unknownFallback: '' })

      const results = []
      const chapter = await getOrCreateChapter(projectId, chapterNum)
      const variants = parseMultiVariantText(content)
      for (const variant of variants) {
        const v = await createVersion(projectId, chapter.id, chapterNum, {
          title: `第 ${chapterNum} 章 - ${variant.label || '候选'}`,
          content: variant.content,
          versionType: 'ai_candidate',
          sourceModelId: provider.id,
          promptBrief: `多候选生成 - ${variant.label || '候选'}`
        })
        results.push(v)
      }
      if (results.length > 0) await syncProjectCurrentChapter(projectId, chapterNum)
      return results
    } finally {
      generating.value = false
    }
  }

  // === AI 选区重写 ===
  async function rewriteSelection(selectedText, mode, context, providerId) {
    generating.value = true
    try {
      const provider = await resolveTaskProvider(context?.projectId, ['polishModelId', 'writingModelId'], providerId)
      const messages = [
        { role: 'system', content: buildRewriteSystemPrompt() },
        { role: 'user', content: buildRewritePrompt(selectedText, mode, context) }
      ]
      const result = await chatCompletion(provider, messages, { maxTokens: 2048, temperature: 0.7 })
      return extractAiContent(result, { preferOwnContent: false, stringifyUnknown: false })
    } finally {
      generating.value = false
    }
  }

  // === AI 扩写 ===
  async function expandText(selectedText, context = {}) {
    generating.value = true
    try {
      const provider = await resolveTaskProvider(context?.projectId, ['polishModelId', 'writingModelId'])
      const messages = [{ role: 'user', content: buildExpandPrompt(selectedText, context) }]
      const result = await chatCompletion(provider, messages, { maxTokens: 2048, temperature: 0.7 })
      return extractAiContent(result, { preferOwnContent: false, stringifyUnknown: false })
    } finally {
      generating.value = false
    }
  }

  // === AI 压缩 ===
  async function compressText(selectedText) {
    generating.value = true
    try {
      const provider = await resolveTaskProvider(null, ['polishModelId', 'summaryModelId', 'writingModelId'])
      const messages = [{ role: 'user', content: buildCompressPrompt(selectedText) }]
      const result = await chatCompletion(provider, messages, { maxTokens: 1024, temperature: 0.5 })
      return extractAiContent(result, { preferOwnContent: false, stringifyUnknown: false })
    } finally {
      generating.value = false
    }
  }

  // === 确认定稿 ===
  async function finalizeVersion(version) {
    try {
      const pid = version.projectId || version.project_id
      const cid = version.chapterId || version.chapter_id
      const chapter = chapters.value.find(c => c.id === cid)
      if (chapter && isDefaultChapterTitle(chapter.title, chapter.chapterNum || chapter.chapter_num || version.chapterNum || version.chapter_num)) {
        try {
          await generateDefaultChapterTitle(
            pid,
            chapter,
            chapter.chapterNum || chapter.chapter_num || version.chapterNum || version.chapter_num,
            version.content,
            {}
          )
        } catch (titleErr) {
          console.warn('定稿章名生成失败，保留默认章名:', titleErr.message)
        }
      }
      const result = await api.versions.finalize(pid, cid, version.id, {
        summary: chapter?.summary || '',
        wordCount: version.content?.length || 0
      })
      const finalizedVersion = result?.version || { ...version, versionType: 'final' }
      const finalizedChapter = result?.chapter

      Object.assign(version, finalizedVersion)

      if (finalizedChapter) {
        const idx = chapters.value.findIndex(c => c.id === cid)
        if (idx !== -1) chapters.value[idx] = { ...chapters.value[idx], ...finalizedChapter }
        if (currentChapter.value?.id === cid) currentChapter.value = { ...currentChapter.value, ...finalizedChapter }
        await syncProjectCurrentChapter(pid, finalizedChapter.chapterNum || finalizedChapter.chapter_num)
      } else if (chapter) {
        chapter.finalVersionId = version.id
        chapter.status = 'final'
        chapter.wordCount = version.content?.length || 0
        await syncProjectCurrentChapter(pid, chapter.chapterNum || chapter.chapter_num)
      }

      const vIdx = versions.value.findIndex(v => v.id === version.id)
      if (vIdx !== -1) versions.value[vIdx] = version
      if (currentVersion.value?.id === version.id) currentVersion.value = version

      return version
    } catch (e) {
      console.error('定稿失败:', e.message)
      throw e
    }
  }

  function normalizeCorrectionTasks(taskOrTasks) {
    if (Array.isArray(taskOrTasks)) return taskOrTasks.filter(Boolean)
    return taskOrTasks ? [taskOrTasks] : []
  }

  function normalizeAuditIssuesAsCorrectionTasks(issues) {
    return (Array.isArray(issues) ? issues : [])
      .filter(Boolean)
      .map((issue, index) => {
        const descriptionParts = [
          issue?.description,
          issue?.location ? `位置：${issue.location}` : '',
          issue?.reason ? `原因：${issue.reason}` : ''
        ].filter(Boolean)

        return {
          title: `本章审稿问题 ${index + 1}`,
          issueType: issue?.type || 'chapter_audit',
          severity: issue?.severity || 'minor',
          description: descriptionParts.join('\n') || '本章审稿发现的问题',
          suggestedAction: issue?.suggestion || '在不改动无关正文的前提下进行保守修订。'
        }
      })
  }

  function buildCorrectionPromptBrief(taskOrTasks) {
    const tasks = normalizeCorrectionTasks(taskOrTasks)
    const title = tasks.length > 1
      ? `综合纠偏任务：${tasks.map(task => task?.title || '未命名').join('；')}`.slice(0, 160)
      : `纠偏任务：${tasks[0]?.title || ''}`.slice(0, 130)
    const ids = tasks
      .map(task => task?.id)
      .filter(Boolean)
      .map(id => `[correctionTaskId:${id}]`)
      .join('\n')
    return ids ? `${title}\n${ids}` : title
  }

  return {
    chapters,
    versions,
    currentChapter,
    currentVersion,
    tempDraft,
    loading,
    generating,
    beatPlanning,
    chapterBeatPlan,
    beatPlanRecord,
    beatPlanSource,
    beatPlanQualityNotice,
    beatPlanDiagnostics,
    beatPlanQualityDiagnostics,
    generationStream,
    loadChapters,
    getOrCreateChapter,
    bulkCreateEmptyChapters,
    bulkCreateEmptyChapterRange,
    updateChapter,
    generateDefaultChapterTitle,
    updateChapterTitle,
    deleteChapter,
    loadVersions,
    createVersion,
    updateVersion,
    deleteVersion,
    saveTempDraft,
    loadTempDraft,
    clearTempDraft,
    loadChapterBeatPlan,
    saveChapterBeatPlan,
    clearChapterBeatPlan,
    generateChapterBeatPlan,
    generateChapter,
    generateCorrectionDraft,
    generateLocalCorrectionPatchCandidate,
    continueWriting,
    generateMultiVariants,
    rewriteSelection,
    expandText,
    compressText,
    finalizeVersion
  }
})
