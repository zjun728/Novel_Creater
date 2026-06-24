import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '@/api/db/client'
import { chatCompletion } from '@/api/ai'
import { useProviderStore } from './providerStore'
import {
  canEditRemainingStage,
  normalizeStoryBlockReviewDecision,
  normalizeStoryBlockStatus
} from '@/utils/storyBlockSnapshot'
import {
  buildStoryBlockPlanningSystemPrompt,
  buildStoryBlockPlanningPrompt,
  buildStoryBlockPlanningRepairPrompt,
  buildStoryBlockReviewSystemPrompt,
  buildStoryBlockReviewPrompt,
  buildStoryBlockReviewRepairPrompt,
  buildStoryBlockReviewSemanticRepairPrompt,
  normalizeStoryBlockReviewResult
} from '@/prompts/storyBlockPrompt'

const STORY_BLOCK_REVIEW_TIMEOUT_MS = 240000
const STORY_BLOCK_REVIEW_REPAIR_TIMEOUT_MS = 90000

export const STORY_BLOCK_STATUS_OPTIONS = [
  { label: '进行中', value: 'active' },
  { label: '已完成', value: 'completed' },
  { label: '暂缓', value: 'paused' },
  { label: '已提前结束', value: 'closed' }
]

export const STORY_BLOCK_REVIEW_DECISION_LABELS = {
  continue_current_block: '继续当前故事块',
  adjust_remaining_stages: '更新后续阶段',
  split_unfinalized_content: '拆分未定稿内容',
  complete_current_block: '完成当前故事块',
  open_new_block: '开启新故事块'
}

export const useStoryBlockStore = defineStore('storyBlock', () => {
  const blocks = ref([])
  const activeBlock = ref(null)
  const loading = ref(false)
  const reviewResult = ref(null)
  const aiPlanning = ref(false)
  const aiReviewing = ref(false)
  const lastPlanningDiagnostics = ref(null)
  const lastReviewDiagnostics = ref(null)

  async function loadBlocks(projectId) {
    if (!projectId) return []
    loading.value = true
    try {
      blocks.value = await api.storyBlocks.list(projectId)
      activeBlock.value = resolveSingleActiveBlock(blocks.value)
      return blocks.value
    } finally {
      loading.value = false
    }
  }

  async function loadActiveBlock(projectId) {
    if (!projectId) return null
    await loadBlocks(projectId)
    return activeBlock.value
  }

  async function createStoryBlock(projectId, payload = {}) {
    const result = await api.storyBlocks.create(projectId, normalizeStoryBlockPayload(payload))
    upsertBlock(result)
    activeBlock.value = resolveSingleActiveBlock(blocks.value)
    return result
  }

  async function updateRemainingStages(projectId, blockId, payload = {}) {
    const result = await api.storyBlocks.updateRemainingStages(projectId, blockId, {
      stagePlan: payload.stagePlan || [],
      nextStageSuggestion: payload.nextStageSuggestion || '',
      unresolvedQuestions: normalizeList(payload.unresolvedQuestions),
      dontAdvanceYet: normalizeList(payload.dontAdvanceYet),
      carryOverToNextChapter: normalizeList(payload.carryOverToNextChapter),
      capacityAssessment: payload.capacityAssessment || 'normal'
    })
    upsertBlock(result)
    if (activeBlock.value?.id === result.id) activeBlock.value = result
    return result
  }

  async function closeBlock(projectId, blockId, payload = {}) {
    const result = await api.storyBlocks.close(projectId, blockId, payload)
    upsertBlock(result)
    if (activeBlock.value?.id === result.id) activeBlock.value = null
    return result
  }

  async function completeBlock(projectId, blockId, payload = {}) {
    const result = await api.storyBlocks.complete(projectId, blockId, payload)
    upsertBlock(result)
    if (activeBlock.value?.id === result.id) activeBlock.value = null
    return result
  }

  async function confirmStoryBlockReview(projectId, blockId, payload = {}) {
    const result = await api.storyBlocks.confirmReview(projectId, blockId, payload)
    upsertBlock(result)
    if (result.status === 'active') activeBlock.value = resolveSingleActiveBlock(blocks.value)
    return result
  }

  async function saveBlockReview(projectId, blockId, payload = {}) {
    const decision = normalizeStoryBlockReviewDecision(payload.decision)
    const result = await api.storyBlocks.createReview(projectId, blockId, {
      chapterNum: payload.chapterNum,
      decision,
      review: payload.review || {}
    })
    reviewResult.value = result
    await loadBlocks(projectId).catch(() => null)
    return result
  }

  async function planStoryBlockWithAI(projectId, context = {}, providerId = null) {
    aiPlanning.value = true
    lastPlanningDiagnostics.value = null
    try {
      const provider = await resolveStoryBlockProvider(projectId, ['outlineModelId', 'writingModelId'], providerId)
      const messages = [
        { role: 'system', content: buildStoryBlockPlanningSystemPrompt() },
        { role: 'user', content: buildStoryBlockPlanningPrompt(context) }
      ]
      const result = await chatCompletion(provider, messages, jsonOptions(provider, { maxTokens: 3200, temperature: 0.35 }))
      const rawText = getCompletionText(result)
      const diagnostics = createStoryBlockPlanningDiagnostics({
        provider,
        messages,
        rawText,
        repairTriggered: false,
        repairSucceeded: false
      })
      let parsed = null
      try {
        if (diagnostics.likelyTruncated) throw new Error('AI story block JSON is likely truncated')
        parsed = parseStoryBlockPlanningJson(rawText)
        assertUsableStoryBlockPlanningRoot(parsed)
      } catch (parseError) {
        diagnostics.parseError = parseError.message
        diagnostics.repairTriggered = true
        try {
          const repair = await repairStoryBlockPlanningJson(provider, rawText)
          diagnostics.repairSucceeded = true
          diagnostics.repairRawHead = repair.rawText.slice(0, 1500)
          diagnostics.repairRawTail = repair.rawText.slice(-800)
          assertUsableStoryBlockPlanningRoot(repair.parsed)
          parsed = repair.parsed
        } catch (repairError) {
          diagnostics.repairSucceeded = false
          diagnostics.repairError = repairError.message
          lastPlanningDiagnostics.value = diagnostics
          const error = new Error(`无法解析故事块 AI 返回的 JSON；JSON 修复失败：${repairError.message}`)
          error.diagnostics = diagnostics
          throw error
        }
      }
      lastPlanningDiagnostics.value = diagnostics
      const payload = normalizeStoryBlockPlanningResult(parsed, context)
      payload.lockState = {
        ...(payload.lockState || {}),
        planningDiagnostics: compactPlanningDiagnostics(diagnostics)
      }
      return payload
    } finally {
      aiPlanning.value = false
    }
  }

  async function reviewStoryBlockWithAI(projectId, context = {}, providerId = null) {
    aiReviewing.value = true
    lastReviewDiagnostics.value = null
    try {
      const provider = await resolveStoryBlockProvider(projectId, ['auditModelId', 'outlineModelId', 'writingModelId'], providerId)
      const messages = [
        { role: 'system', content: buildStoryBlockReviewSystemPrompt() },
        { role: 'user', content: buildStoryBlockReviewPrompt(context) }
      ]
      const diagnostics = createStoryBlockReviewDiagnostics({ provider, messages })
      let rawText = ''
      try {
        const result = await withStoryBlockReviewTimeout(
          chatCompletion(provider, messages, jsonOptions(provider, { maxTokens: 2200, temperature: 0.2 })),
          STORY_BLOCK_REVIEW_TIMEOUT_MS,
          '故事块回看 AI 调用超时'
        )
        rawText = getCompletionText(result)
        Object.assign(diagnostics, createStoryBlockReviewDiagnostics({ provider, messages, rawText }))
      } catch (callError) {
        diagnostics.callError = callError.message || String(callError)
        diagnostics.timedOut = callError.code === 'STORY_BLOCK_REVIEW_TIMEOUT'
        lastReviewDiagnostics.value = diagnostics
        callError.diagnostics = diagnostics
        throw callError
      }

      try {
        const parsed = await reviewStoryBlockJsonWithRepair(provider, rawText, diagnostics)
        const normalized = normalizeStoryBlockReviewResult(parsed)
        const validReview = await ensureValidStoryBlockReview(provider, normalized, context, diagnostics)
        lastReviewDiagnostics.value = diagnostics
        return {
          ...validReview,
          aiReviewDiagnostics: compactStoryBlockReviewDiagnostics(diagnostics)
        }
      } catch (parseError) {
        lastReviewDiagnostics.value = diagnostics
        parseError.diagnostics = diagnostics
        throw parseError
      }
    } finally {
      aiReviewing.value = false
    }
  }

  function isStageLocked(stage) {
    return !canEditRemainingStage(stage)
  }

  function canEditStage(stage) {
    return canEditRemainingStage(stage)
  }

  function hasChapterRefs(block) {
    return Array.isArray(block?.chapterRefs) && block.chapterRefs.length > 0
  }

  function upsertBlock(block) {
    if (!block?.id) return
    const idx = blocks.value.findIndex(item => item.id === block.id)
    if (idx === -1) blocks.value.push(block)
    else blocks.value[idx] = block
    blocks.value = [...blocks.value].sort((a, b) => Number(a.blockNum || 0) - Number(b.blockNum || 0))
  }

  return {
    blocks,
    activeBlock,
    loading,
    reviewResult,
    aiPlanning,
    aiReviewing,
    lastPlanningDiagnostics,
    lastReviewDiagnostics,
    loadBlocks,
    loadActiveBlock,
    createStoryBlock,
    updateRemainingStages,
    closeBlock,
    completeBlock,
    confirmStoryBlockReview,
    saveBlockReview,
    planStoryBlockWithAI,
    reviewStoryBlockWithAI,
    isStageLocked,
    canEditStage,
    hasChapterRefs
  }
})

function normalizeStoryBlockPayload(payload = {}) {
  return {
    volumeId: payload.volumeId || null,
    blockNum: payload.blockNum,
    status: normalizeStoryBlockStatus(payload.status || 'active'),
    title: payload.title || '',
    goal: payload.goal || '',
    storyFunction: payload.storyFunction || '',
    entryState: payload.entryState || '',
    exitTarget: payload.exitTarget || '',
    mainPressure: payload.mainPressure || '',
    keyCharacters: normalizeList(payload.keyCharacters),
    stagePlan: normalizeList(payload.stagePlan),
    completedStages: normalizeList(payload.completedStages),
    nextStageSuggestion: payload.nextStageSuggestion || '',
    unresolvedQuestions: normalizeList(payload.unresolvedQuestions),
    dontAdvanceYet: normalizeList(payload.dontAdvanceYet),
    carryOverToNextChapter: normalizeList(payload.carryOverToNextChapter),
    capacityAssessment: payload.capacityAssessment || 'normal',
    chapterRefs: normalizeList(payload.chapterRefs),
    lockState: payload.lockState || {}
  }
}

function resolveSingleActiveBlock(blocksToCheck = []) {
  const activeBlocks = blocksToCheck.filter(block => block.status === 'active')
  if (activeBlocks.length > 1) {
    throw new Error(`故事块数据异常：项目存在 ${activeBlocks.length} 个 active 故事块，请先关闭多余故事块`)
  }
  return activeBlocks[0] || null
}

async function resolveStoryBlockProvider(projectId, bindingKeys = [], providerId = null) {
  const providerStore = useProviderStore()
  return providerStore.resolveTaskProvider({
    projectId,
    bindingKeys,
    providerId,
    taskName: bindingKeys.join('/') || 'story_block_task'
  })
}

function jsonOptions(provider, options = {}) {
  return provider?.supportsJSON === false
    ? options
    : { ...options, responseFormat: 'json' }
}

function parseAIJson(result) {
  return parseStoryBlockPlanningJson(getCompletionText(result))
}

async function reviewStoryBlockJsonWithRepair(provider, rawText, diagnostics = {}) {
  try {
    return parseStoryBlockPlanningJson(rawText)
  } catch (parseError) {
    diagnostics.parseError = parseError.message
    diagnostics.repairTriggered = true
    try {
      const repair = await repairStoryBlockReviewJson(provider, rawText)
      diagnostics.repairSucceeded = true
      diagnostics.repairRawHead = repair.rawText.slice(0, 1500)
      diagnostics.repairRawTail = repair.rawText.slice(-800)
      return repair.parsed
    } catch (repairError) {
      diagnostics.repairSucceeded = false
      diagnostics.repairError = repairError.message
      throw repairError
    }
  }
}

async function ensureValidStoryBlockReview(provider, review = {}, context = {}, diagnostics = {}) {
  const normalized = normalizeStageContinueReason(review)
  if (!isInvalidStageContinuationReview(normalized)) return normalized

  diagnostics.semanticRepairTriggered = true
  diagnostics.semanticRepairIssue = 'stage_continue_reason_missing'
  try {
    const repair = await repairStoryBlockReviewSemantics(provider, normalized, context)
    diagnostics.semanticRepairSucceeded = true
    diagnostics.semanticRepairRawHead = repair.rawText.slice(0, 1500)
    diagnostics.semanticRepairRawTail = repair.rawText.slice(-800)
    const repaired = normalizeStageContinueReason(normalizeStoryBlockReviewResult(repair.parsed))
    if (!isInvalidStageContinuationReview(repaired)) {
      return {
        ...repaired,
        semanticRepairApplied: true
      }
    }
    diagnostics.semanticRepairSucceeded = false
    diagnostics.semanticRepairError = 'stage_continue_reason_missing_after_repair'
  } catch (error) {
    diagnostics.semanticRepairSucceeded = false
    diagnostics.semanticRepairError = error.message || String(error)
  }

  return degradeInvalidStageContinuationReview(normalized)
}

function normalizeStageContinueReason(review = {}) {
  const stageContinueReason = getStageContinueReason(review)
  if (review.stageContinues === true && stageContinueReason) {
    return {
      ...review,
      stageContinueReason,
      reason: String(review.reason || stageContinueReason).trim()
    }
  }
  return {
    ...review,
    stageContinueReason
  }
}

function getStageContinueReason(review = {}) {
  return String(review.stageContinueReason || review.stage_continue_reason || review.reason || '').trim()
}

function isInvalidStageContinuationReview(review = {}) {
  return review.stageContinues === true && !getStageContinueReason(review)
}

function degradeInvalidStageContinuationReview(review = {}) {
  return {
    ...review,
    stageContinues: false,
    stageContinueReason: '',
    reason: 'stage_continue_reason_missing：AI 回看要求跨章继续同一阶段但未说明原因，已转为当前阶段完成并进入下一可执行阶段。',
    reviewInvalidRepairedBy: 'stage_continue_reason_missing_degraded',
    reviewWarnings: [
      ...(Array.isArray(review.reviewWarnings) ? review.reviewWarnings : []),
      'stage_continue_reason_missing'
    ]
  }
}

export function parseStoryBlockPlanningJson(text) {
  const candidates = extractJsonCandidates(text)
  for (const candidate of candidates) {
    try {
      return JSON.parse(candidate)
    } catch {}
  }
  throw new Error('无法解析故事块 AI 返回的 JSON')
}

function assertUsableStoryBlockPlanningRoot(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error('Story block planning JSON is not an object root')
  }
  const stagePlan = value.stagePlan || value.stage_plan
  if (!Array.isArray(stagePlan) || !stagePlan.length) {
    throw new Error('Story block planning JSON is missing stagePlan')
  }
  if (!String(value.title || '').trim()) {
    throw new Error('Story block planning JSON is missing title')
  }
  if (!String(value.goal || '').trim()) {
    throw new Error('Story block planning JSON is missing goal')
  }
  const hasMeaningfulStage = stagePlan.some(stage => {
    const item = typeof stage === 'object' && stage ? stage : {}
    return Boolean(item.purpose || item.stagePurpose || item.goal || item.sceneOrAction || item.action || item.description)
  })
  if (!hasMeaningfulStage) {
    throw new Error('Story block planning JSON has no usable stage')
  }
}

async function repairStoryBlockPlanningJson(provider, rawText) {
  const repairMessages = [
    { role: 'system', content: '你是 JSON 修复器。只输出合法 JSON，不要解释，不要 Markdown。' },
    { role: 'user', content: buildStoryBlockPlanningRepairPrompt(rawText) }
  ]
  const repairResult = await chatCompletion(provider, repairMessages, jsonOptions(provider, { maxTokens: 3000, temperature: 0 }))
  const repairText = getCompletionText(repairResult)
  return {
    rawText: repairText,
    parsed: parseStoryBlockPlanningJson(repairText)
  }
}

async function repairStoryBlockReviewJson(provider, rawText) {
  const repairMessages = [
    { role: 'system', content: '你是 JSON 修复器。只输出合法 JSON，不要解释，不要 Markdown。' },
    { role: 'user', content: buildStoryBlockReviewRepairPrompt(rawText) }
  ]
  const repairResult = await withStoryBlockReviewTimeout(
    chatCompletion(provider, repairMessages, jsonOptions(provider, { maxTokens: 1800, temperature: 0 })),
    STORY_BLOCK_REVIEW_REPAIR_TIMEOUT_MS,
    '故事块回看 JSON 修复超时'
  )
  const repairText = getCompletionText(repairResult)
  return {
    rawText: repairText,
    parsed: parseStoryBlockPlanningJson(repairText)
  }
}

async function repairStoryBlockReviewSemantics(provider, review, context = {}) {
  const repairMessages = [
    { role: 'system', content: '你是故事块回看 JSON 语义修复器。只输出合法 JSON，不要解释，不要 Markdown。' },
    { role: 'user', content: buildStoryBlockReviewSemanticRepairPrompt(review, context) }
  ]
  const repairResult = await withStoryBlockReviewTimeout(
    chatCompletion(provider, repairMessages, jsonOptions(provider, { maxTokens: 1600, temperature: 0 })),
    STORY_BLOCK_REVIEW_REPAIR_TIMEOUT_MS,
    '故事块回看语义修复超时'
  )
  const repairText = getCompletionText(repairResult)
  return {
    rawText: repairText,
    parsed: parseStoryBlockPlanningJson(repairText)
  }
}

function extractJsonCandidates(text) {
  const raw = String(text || '').replace(/^\uFEFF/, '').trim()
  const strippedFence = raw
    .replace(/^```(?:json)?\s*/i, '')
    .replace(/\s*```$/i, '')
    .trim()
  const candidates = [raw, strippedFence]
  for (const candidate of findBalancedJsonCandidates(strippedFence)) {
    candidates.push(candidate)
  }
  const regexCandidate = strippedFence.match(/\{[\s\S]*\}|\[[\s\S]*\]/)?.[0]
  if (regexCandidate) candidates.push(regexCandidate)
  return [...new Set(candidates.filter(Boolean))]
}

function findBalancedJsonCandidates(text) {
  const candidates = []
  const source = String(text || '')
  for (let start = 0; start < source.length; start++) {
    const open = source[start]
    if (open !== '{' && open !== '[') continue
    const close = open === '{' ? '}' : ']'
    const stack = [close]
    let inString = false
    let escaped = false
    for (let index = start + 1; index < source.length; index++) {
      const char = source[index]
      if (escaped) {
        escaped = false
        continue
      }
      if (char === '\\') {
        escaped = true
        continue
      }
      if (char === '"') {
        inString = !inString
        continue
      }
      if (inString) continue
      if (char === '{') stack.push('}')
      else if (char === '[') stack.push(']')
      else if (char === stack[stack.length - 1]) {
        stack.pop()
        if (!stack.length) {
          candidates.push(source.slice(start, index + 1))
          break
        }
      }
    }
  }
  return candidates
}

export function createStoryBlockPlanningDiagnostics({
  provider,
  messages = [],
  rawText = '',
  repairTriggered = false,
  repairSucceeded = false
} = {}) {
  const promptChars = messages.reduce((sum, message) => sum + String(message.content || '').length, 0)
  return {
    providerId: provider?.id || provider?.providerId || '',
    modelName: provider?.model || provider?.modelName || provider?.name || '',
    supportsJSON: provider?.supportsJSON !== false,
    promptChars,
    promptTokensApprox: Math.ceil(promptChars / 2),
    rawHead: String(rawText || '').slice(0, 1500),
    rawTail: String(rawText || '').slice(-800),
    containsMarkdownCodeBlock: /```/.test(String(rawText || '')),
    likelyTruncated: isLikelyTruncatedStoryBlockJson(rawText),
    repairTriggered,
    repairSucceeded,
    parseError: '',
    repairError: ''
  }
}

export function createStoryBlockReviewDiagnostics({
  provider,
  messages = [],
  rawText = '',
  repairTriggered = false,
  repairSucceeded = false
} = {}) {
  const promptChars = messages.reduce((sum, message) => sum + String(message.content || '').length, 0)
  return {
    providerId: provider?.id || provider?.providerId || '',
    modelName: provider?.model || provider?.modelName || provider?.name || '',
    supportsJSON: provider?.supportsJSON !== false,
    promptChars,
    promptTokensApprox: Math.ceil(promptChars / 2),
    rawHead: String(rawText || '').slice(0, 1500),
    rawTail: String(rawText || '').slice(-800),
    containsMarkdownCodeBlock: /```/.test(String(rawText || '')),
    likelyTruncated: isLikelyTruncatedStoryBlockJson(rawText),
    repairTriggered,
    repairSucceeded,
    parseError: '',
    repairError: '',
    callError: '',
    timedOut: false,
    semanticRepairTriggered: false,
    semanticRepairSucceeded: false,
    semanticRepairIssue: '',
    semanticRepairError: ''
  }
}

export function isLikelyTruncatedStoryBlockJson(text) {
  const value = String(text || '').trim()
  if (!value) return false
  if (/```/.test(value) && !/```\s*$/.test(value) && (value.match(/```/g) || []).length % 2 === 1) return true
  const last = value[value.length - 1]
  if (last && !['}', ']', '`'].includes(last)) return true
  let balance = 0
  let inString = false
  let escaped = false
  for (const char of value) {
    if (escaped) {
      escaped = false
      continue
    }
    if (char === '\\') {
      escaped = true
      continue
    }
    if (char === '"') {
      inString = !inString
      continue
    }
    if (inString) continue
    if (char === '{' || char === '[') balance += 1
    if (char === '}' || char === ']') balance -= 1
  }
  return balance > 0 || inString
}

function compactPlanningDiagnostics(diagnostics = {}) {
  return {
    providerId: diagnostics.providerId || '',
    modelName: diagnostics.modelName || '',
    supportsJSON: diagnostics.supportsJSON !== false,
    promptChars: diagnostics.promptChars || 0,
    promptTokensApprox: diagnostics.promptTokensApprox || 0,
    rawHead: diagnostics.rawHead || '',
    rawTail: diagnostics.rawTail || '',
    containsMarkdownCodeBlock: Boolean(diagnostics.containsMarkdownCodeBlock),
    likelyTruncated: Boolean(diagnostics.likelyTruncated),
    repairTriggered: Boolean(diagnostics.repairTriggered),
    repairSucceeded: Boolean(diagnostics.repairSucceeded),
    parseError: diagnostics.parseError || '',
    repairError: diagnostics.repairError || ''
  }
}

function compactStoryBlockReviewDiagnostics(diagnostics = {}) {
  return {
    providerId: diagnostics.providerId || '',
    modelName: diagnostics.modelName || '',
    supportsJSON: diagnostics.supportsJSON !== false,
    promptChars: diagnostics.promptChars || 0,
    promptTokensApprox: diagnostics.promptTokensApprox || 0,
    rawHead: diagnostics.rawHead || '',
    rawTail: diagnostics.rawTail || '',
    containsMarkdownCodeBlock: Boolean(diagnostics.containsMarkdownCodeBlock),
    likelyTruncated: Boolean(diagnostics.likelyTruncated),
    repairTriggered: Boolean(diagnostics.repairTriggered),
    repairSucceeded: Boolean(diagnostics.repairSucceeded),
    parseError: diagnostics.parseError || '',
    repairError: diagnostics.repairError || '',
    callError: diagnostics.callError || '',
    timedOut: Boolean(diagnostics.timedOut),
    repairRawHead: diagnostics.repairRawHead || '',
    repairRawTail: diagnostics.repairRawTail || '',
    semanticRepairTriggered: Boolean(diagnostics.semanticRepairTriggered),
    semanticRepairSucceeded: Boolean(diagnostics.semanticRepairSucceeded),
    semanticRepairIssue: diagnostics.semanticRepairIssue || '',
    semanticRepairError: diagnostics.semanticRepairError || '',
    semanticRepairRawHead: diagnostics.semanticRepairRawHead || '',
    semanticRepairRawTail: diagnostics.semanticRepairRawTail || ''
  }
}

function withStoryBlockReviewTimeout(promise, timeoutMs, message = '故事块回看超时') {
  let timer = null
  const timeout = new Promise((_, reject) => {
    timer = setTimeout(() => {
      const error = new Error(message)
      error.code = 'STORY_BLOCK_REVIEW_TIMEOUT'
      reject(error)
    }, timeoutMs)
  })
  return Promise.race([promise, timeout]).finally(() => {
    if (timer) clearTimeout(timer)
  })
}

function getCompletionText(result) {
  if (typeof result === 'string') return result
  if (Array.isArray(result)) {
    const block = result.find(item => item.type === 'text')
    return block?.text || JSON.stringify(result)
  }
  if (typeof result?.content === 'string') return result.content
  if (result?.choices?.[0]?.message?.content) return result.choices[0].message.content
  return result ? JSON.stringify(result) : ''
}

function normalizeStoryBlockPlanningResult(raw = {}, context = {}) {
  const currentVolume = context.currentVolume || context.volumeStage || {}
  const stagePlan = normalizeList(raw.stagePlan || raw.stage_plan).map((stage, index) => {
    const item = typeof stage === 'object' && stage ? stage : { purpose: String(stage || '') }
    return {
      id: item.id || `stage-${index + 1}`,
      purpose: item.purpose || item.stagePurpose || item.goal || '',
      sceneOrAction: item.sceneOrAction || item.action || item.description || '',
      choice: item.choice || '',
      costOrConsequence: item.costOrConsequence || item.consequence || item.cost || '',
      status: item.status === 'completed' ? 'planned' : (item.status || 'planned')
    }
  }).filter(stage => stage.purpose || stage.sceneOrAction)

  return normalizeStoryBlockPayload({
    volumeId: raw.volumeId || currentVolume.id || null,
    status: 'active',
    title: raw.title || '新故事块',
    goal: raw.goal || context.chapterGoal?.goal || currentVolume.coreGoal || currentVolume.goal || '',
    storyFunction: raw.storyFunction || raw.story_function || '',
    entryState: raw.entryState || raw.entry_state || context.previousChapterEnding || '',
    exitTarget: raw.exitTarget || raw.exit_target || '',
    mainPressure: raw.mainPressure || raw.main_pressure || '',
    keyCharacters: raw.keyCharacters || raw.key_characters || [],
    stagePlan: stagePlan.length ? stagePlan : [{ id: 'stage-1', purpose: raw.nextStageSuggestion || '承接当前剧情', status: 'planned' }],
    completedStages: [],
    nextStageSuggestion: raw.nextStageSuggestion || raw.next_stage_suggestion || '',
    unresolvedQuestions: raw.unresolvedQuestions || raw.unresolved_questions || [],
    dontAdvanceYet: raw.dontAdvanceYet || raw.dont_advance_yet || [],
    carryOverToNextChapter: raw.carryOverToNextChapter || raw.carry_over_to_next_chapter || [],
    capacityAssessment: raw.capacityAssessment || raw.capacity_assessment || 'normal',
    lockState: {
      aiPlanned: true,
      plannedAt: Date.now(),
      shortBlockReason: raw.shortBlockReason || raw.short_block_reason || ''
    }
  })
}

function normalizeList(value) {
  if (Array.isArray(value)) return value
  if (!value) return []
  return String(value)
    .split(/\n|,|，|、/)
    .map(item => item.trim())
    .filter(Boolean)
}
