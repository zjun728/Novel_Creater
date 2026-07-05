import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '@/api/db/client'
import { chatCompletion } from '@/api/ai'
import {
  buildCompactVolumePlanRetryPrompt,
  buildVolumePlanPrompt,
  buildVolumePlanRepairPrompt,
  buildVolumePlanSystemPrompt
} from '@/prompts/volumePlan'
import { useProjectStore } from './projectStore'
import { useProviderStore } from './providerStore'
import { useNovelStore } from './novelStore'
import { useSeedStore } from './seedStore'
import { useSettingStore } from './settingStore'
import { normalizeStateProvenance } from '@/utils/stateProvenance'

export const VOLUME_STATUS_OPTIONS = [
  { label: '规划中', value: 'planned' },
  { label: '创作中', value: 'active' },
  { label: '已完成', value: 'completed' },
  { label: '暂缓', value: 'paused' }
]

const VOLUME_PLAN_DIAGNOSTICS_PREFIX = 'volume-plan-diagnostics'

export const useVolumeStore = defineStore('volume', () => {
  const volumes = ref([])
  const loading = ref(false)
  const generating = ref(false)
  const volumePlanQualityWarnings = ref([])
  const lastPlanningDiagnostics = ref(null)

  async function loadVolumes(projectId) {
    loading.value = true
    try {
      volumes.value = await api.volumes.list(projectId)
      volumePlanQualityWarnings.value = detectVolumePlanPlaceholders(volumes.value)
      return volumes.value
    } catch (e) {
      console.error('加载分卷规划失败:', e.message)
      throw e
    } finally {
      loading.value = false
    }
  }

  async function saveVolume(projectId, data) {
    const payload = normalizeVolume(data)
    const result = data.id
      ? await api.volumes.update(projectId, data.id, payload)
      : await api.volumes.create(projectId, payload)

    const idx = volumes.value.findIndex(v => v.id === result.id)
    if (idx === -1) volumes.value.push(result)
    else volumes.value[idx] = result
    sortVolumes()
    volumePlanQualityWarnings.value = detectVolumePlanPlaceholders(volumes.value)
    await refreshProject(projectId)
    return result
  }

  async function saveAudit(projectId, volumeId, report) {
    const result = await api.volumes.saveAudit(projectId, volumeId, report)
    upsertVolume(result)
    sortVolumes()
    await refreshProject(projectId)
    return result
  }

  async function saveStageSummary(projectId, volumeId, report, options = {}) {
    const provenance = normalizeStateProvenance(options.provenance || report?.snapshotProvenance || {})
    const payload = {
      ...(report || {}),
      snapshotProvenance: provenance,
      sourceExplanation: report?.sourceExplanation || {
        sourceType: provenance.commitStatus === 'final' ? 'final_state' : 'degraded_fallback',
        reason: provenance.commitStatus || 'unknown'
      }
    }
    const result = await api.volumes.saveSummary(projectId, volumeId, payload)
    upsertVolume(result)
    sortVolumes()
    await refreshProject(projectId)
    return result
  }

  async function deleteVolume(projectId, volumeId) {
    await api.volumes.delete(projectId, volumeId)
    volumes.value = volumes.value.filter(v => v.id !== volumeId)
    volumePlanQualityWarnings.value = detectVolumePlanPlaceholders(volumes.value)
    await refreshProject(projectId)
  }

  async function initializeEmptyByProject(project) {
    if (!project?.id) return []
    const targetChapters = Number(project.targetChapters || 100)
    const targetWords = Number(project.targetWords || 100000)
    const size = targetChapters <= 80 ? targetChapters : 60
    const count = Math.max(1, Math.ceil(targetChapters / size))
    const created = []

    for (let index = 0; index < count; index++) {
      const startChapter = index * size + 1
      const endChapter = Math.min((index + 1) * size, targetChapters)
      const ratio = (endChapter - startChapter + 1) / targetChapters
      const volume = await saveVolume(project.id, {
        volumeNum: index + 1,
        title: `第 ${index + 1} 卷`,
        startChapter,
        endChapter,
        targetWords: Math.round(targetWords * ratio),
        coreGoal: '',
        mainConflict: '',
        keyCharacters: [],
        summary: '',
        foreshadowingPlan: [],
        unresolvedItems: [],
        handoffPoint: '',
        status: index === 0 ? 'active' : 'planned'
      })
      created.push(volume)
    }
    return created
  }

  async function initializeByProject(project) {
    return initializeEmptyByProject(project)
  }

  async function generateVolumePlanByAI(project) {
    if (!project?.id) return []
    if (volumes.value.length > 0) {
      throw new Error('当前项目已经有分卷规划。如需重新规划，请先手动删除旧分卷。')
    }

    generating.value = true
    try {
      const provider = await resolveVolumePlanningProvider(project.id)
      const novelStore = useNovelStore()
      const seedStore = useSeedStore()
      const settingStore = useSettingStore()

      await Promise.all([
        novelStore.loadBible(project.id).catch(() => null),
        seedStore.loadSeeds(project.id).catch(() => []),
        settingStore.loadEntities(project.id).catch(() => [])
      ])

      const seed = (seedStore.seeds || []).find(item => item.status === 'selected') || seedStore.seeds?.[0] || null
      lastPlanningDiagnostics.value = null
      saveVolumePlanningDiagnostics(project.id, null)
      const updateDiagnostics = (patch = {}) => {
        lastPlanningDiagnostics.value = {
          ...(lastPlanningDiagnostics.value || {}),
          ...patch
        }
        saveVolumePlanningDiagnostics(project.id, lastPlanningDiagnostics.value)
        return lastPlanningDiagnostics.value
      }
      const planned = await requestVolumePlan(provider, {
        project,
        seed,
        bible: novelStore.bible,
        settings: settingStore.entities
      }, diagnostics => {
        lastPlanningDiagnostics.value = diagnostics
        saveVolumePlanningDiagnostics(project.id, diagnostics)
      })

      const normalizedResult = normalizeGeneratedVolumesWithDiagnostics(planned, project)
      const normalized = normalizedResult.volumes
      updateDiagnostics({
        parsedVolumeCount: Array.isArray(planned) ? planned.length : 0,
        normalizedVolumeCount: normalized.length,
        droppedVolumes: normalizedResult.droppedVolumes,
        failureStage: normalized.length ? '' : 'normalize_empty'
      })
      if (!normalized.length) {
        const error = new Error('AI 返回的分卷规划归一化后为空，无法保存。')
        error.code = 'volume_plan_normalize_empty'
        error.volumePlanDiagnostics = lastPlanningDiagnostics.value
        throw error
      }
      const warnings = detectVolumePlanPlaceholders(normalized)

      const created = []
      updateDiagnostics({
        saveAttempted: true,
        savedVolumeCount: 0,
        saveErrors: [],
        failureStage: ''
      })
      for (const volume of normalized) {
        try {
          created.push(await saveVolume(project.id, volume))
          updateDiagnostics({ savedVolumeCount: created.length })
        } catch (saveError) {
          const saveErrors = [
            ...(lastPlanningDiagnostics.value?.saveErrors || []),
            {
              volumeNum: volume.volumeNum,
              title: volume.title,
              message: saveError.message || String(saveError)
            }
          ]
          updateDiagnostics({
            saveErrors,
            failureStage: 'save_failed'
          })
          const error = new Error(`分卷规划保存失败：${saveError.message || String(saveError)}`)
          error.code = 'volume_plan_save_failed'
          error.volumePlanDiagnostics = lastPlanningDiagnostics.value
          throw error
        }
      }
      updateDiagnostics({
        saveAttempted: true,
        savedVolumeCount: created.length,
        saveErrors: [],
        failureStage: ''
      })
      volumePlanQualityWarnings.value = warnings.length
        ? warnings
        : detectVolumePlanPlaceholders(created)
      return created
    } finally {
      generating.value = false
    }
  }

  function sortVolumes() {
    volumes.value = [...volumes.value].sort((a, b) =>
      (a.volumeNum || 0) - (b.volumeNum || 0) ||
      (a.startChapter || 0) - (b.startChapter || 0)
    )
  }

  function upsertVolume(result) {
    const idx = volumes.value.findIndex(v => v.id === result.id)
    if (idx === -1) volumes.value.push(result)
    else volumes.value[idx] = result
  }

  return {
    volumes,
    loading,
    generating,
    volumePlanQualityWarnings,
    lastPlanningDiagnostics,
    loadVolumes,
    saveVolume,
    saveAudit,
    saveStageSummary,
    deleteVolume,
    initializeByProject,
    initializeEmptyByProject,
    generateVolumePlanByAI
  }
})

export function detectVolumePlanPlaceholders(items = []) {
  const placeholderPattern = /摘要不完整|TODO|待补充|略|待完善|TBD|\[(?:摘要)?不完整\]/i
  return (Array.isArray(items) ? items : [])
    .flatMap((volume, index) => {
      const fields = [
        ['title', volume?.title],
        ['coreGoal', volume?.coreGoal],
        ['mainConflict', volume?.mainConflict],
        ['summary', volume?.summary],
        ['handoffPoint', volume?.handoffPoint],
        ['foreshadowingPlan', volume?.foreshadowingPlan],
        ['unresolvedItems', volume?.unresolvedItems]
      ]
      return fields
        .filter(([, value]) => placeholderPattern.test(stringifyVolumeField(value)))
        .map(([field, value]) => ({
          volumeNum: volume?.volumeNum || index + 1,
          title: volume?.title || `第 ${index + 1} 卷`,
          field,
          value: stringifyVolumeField(value).slice(0, 120)
        }))
    })
}

function stringifyVolumeField(value) {
  if (Array.isArray(value)) return value.join(' ')
  if (value && typeof value === 'object') return JSON.stringify(value)
  return String(value || '')
}

async function resolveVolumePlanningProvider(projectId) {
  const providerStore = useProviderStore()
  return providerStore.resolveTaskProvider({
    projectId,
    bindingKeys: ['outlineModelId', 'brainstormModelId', 'writingModelId'],
    taskName: 'volume_planning'
  })
}

function getCompletionText(result) {
  if (typeof result === 'string') return result
  if (result?.content) return result.content
  if (result?.choices?.[0]?.message?.content) return result.choices[0].message.content
  return ''
}

function jsonOptions(provider, options = {}) {
  return provider?.supportsJSON === false
    ? options
    : { ...options, responseFormat: 'json' }
}

async function requestVolumePlan(provider, context, onDiagnostics = () => {}) {
  const messages = [
    { role: 'system', content: buildVolumePlanSystemPrompt() },
    { role: 'user', content: buildVolumePlanPrompt(context) }
  ]
  const diagnostics = createVolumePlanningDiagnostics({
    provider,
    messages,
    maxTokens: 10000
  })

  let text = ''
  let repairText = ''
  let compactText = ''
  let parsed = null

  try {
    const result = await chatCompletion(provider, messages, jsonOptions(provider, {
      maxTokens: 10000,
      temperature: 0.35,
      returnRaw: true
    }))
    text = getCompletionText(result)
    updateVolumePlanningDiagnosticsFromResult(diagnostics, result, text)
    parsed = parseVolumePlan(text, diagnostics)
    diagnostics.parsedVolumeCount = parsed?.volumes?.length || 0

    if (!parsed?.volumes?.length) {
      diagnostics.parseError = text.trim() ? '无法解析分卷规划 JSON' : '模型返回内容为空'
      diagnostics.failureStage = text.trim() ? 'parse_failed' : 'empty_response'
      if (text.trim()) {
        diagnostics.repairTriggered = true
        try {
          const repair = await chatCompletion(provider, [
            { role: 'system', content: '你是 JSON 修复器。只输出合法 JSON，不要解释，不要 Markdown。' },
            { role: 'user', content: buildVolumePlanRepairPrompt(text, context.project) }
          ], jsonOptions(provider, { maxTokens: 8000, temperature: 0, returnRaw: true }))
          repairText = getCompletionText(repair)
          diagnostics.repairRawHead = snippet(repairText || stringifyModelResult(repair), 1500)
          diagnostics.repairRawTail = tailSnippet(repairText || stringifyModelResult(repair), 800)
          diagnostics.repairFinishReason = getFinishReason(repair)
          diagnostics.repairUsage = normalizeUsage(getUsage(repair))
          parsed = parseVolumePlan(repairText, diagnostics)
          diagnostics.repairSucceeded = Boolean(parsed?.volumes?.length)
          diagnostics.parsedVolumeCount = parsed?.volumes?.length || diagnostics.parsedVolumeCount || 0
          if (parsed?.volumes?.length) diagnostics.failureStage = ''
        } catch (repairError) {
          diagnostics.repairSucceeded = false
          diagnostics.repairError = repairError.message || String(repairError)
        }
      }
    }

    if (!parsed?.volumes?.length) {
      diagnostics.compactRetryTriggered = true
      try {
        const compact = await chatCompletion(provider, [
          { role: 'system', content: '你是长篇小说分卷规划编辑。只输出精简合法 JSON，不要解释，不要 Markdown。' },
          { role: 'user', content: buildCompactVolumePlanRetryPrompt(context, [text, repairText].filter(Boolean).join('\n\n')) }
        ], jsonOptions(provider, { maxTokens: 10000, temperature: 0.25, returnRaw: true }))
        compactText = getCompletionText(compact)
        diagnostics.compactRawHead = snippet(compactText || stringifyModelResult(compact), 1500)
        diagnostics.compactRawTail = tailSnippet(compactText || stringifyModelResult(compact), 800)
        diagnostics.compactFinishReason = getFinishReason(compact)
        diagnostics.compactUsage = normalizeUsage(getUsage(compact))
        parsed = parseVolumePlan(compactText, diagnostics)
        diagnostics.compactRetrySucceeded = Boolean(parsed?.volumes?.length)
        diagnostics.parsedVolumeCount = parsed?.volumes?.length || diagnostics.parsedVolumeCount || 0
        if (parsed?.volumes?.length) diagnostics.failureStage = ''
      } catch (compactError) {
        diagnostics.compactRetrySucceeded = false
        diagnostics.compactError = compactError.message || String(compactError)
      }
    }

    diagnostics.endedAt = new Date().toISOString()
    onDiagnostics(compactVolumePlanningDiagnostics(diagnostics))

    if (!parsed?.volumes?.length) {
      const raw = snippet(compactText, 300) || snippet(repairText, 300) || snippet(text, 300)
      const error = new Error(`AI 没有返回可解析的分卷规划 JSON${raw ? `。返回片段：${raw}` : '。返回片段为空'}`)
      error.code = 'volume_plan_parse_failed'
      diagnostics.failureStage = diagnostics.failureStage || 'parse_failed'
      error.volumePlanDiagnostics = compactVolumePlanningDiagnostics(diagnostics)
      throw error
    }
    return parsed.volumes
  } catch (error) {
    diagnostics.error = error.message || String(error)
    diagnostics.endedAt = diagnostics.endedAt || new Date().toISOString()
    const compactDiagnostics = error.volumePlanDiagnostics || compactVolumePlanningDiagnostics(diagnostics)
    onDiagnostics(compactDiagnostics)
    error.volumePlanDiagnostics = compactDiagnostics
    throw error
  }
}

function parseVolumePlan(text, diagnostics = null) {
  const cleaned = String(text || '')
    .replace(/^\uFEFF/, '')
    .trim()
  const rejectedParsedCandidates = []
  const candidates = buildVolumePlanParseCandidates(cleaned)

  for (const candidate of candidates) {
    try {
      const parsed = JSON.parse(candidate.text)
      const validation = validateVolumePlanRoot(parsed, candidate.source)
      if (validation.ok) {
        assignVolumePlanParseDiagnostics(diagnostics, {
          parsed,
          volumes: validation.volumes,
          source: candidate.source,
          rejectedParsedCandidates
        })
        return { ...(validation.sourceObject || {}), volumes: validation.volumes }
      }
      rejectedParsedCandidates.push(describeRejectedVolumePlanCandidate(parsed, candidate.source, validation.reason))
    } catch {}
  }
  assignVolumePlanParseDiagnostics(diagnostics, { rejectedParsedCandidates })
  return null
}

function buildVolumePlanParseCandidates(cleaned) {
  const candidates = []
  const seen = new Set()
  const addCandidate = (source, text) => {
    const value = String(text || '').trim()
    if (!value || seen.has(value)) return
    seen.add(value)
    candidates.push({ source, text: value })
  }
  const codeFenceStripped = cleaned
    .replace(/^```(?:json)?\s*/i, '')
    .replace(/\s*```$/i, '')
    .trim()

  addCandidate('cleaned_json', cleaned)
  addCandidate('code_fence_stripped_json', codeFenceStripped)
  addCandidate('largest_outer_object', findLargestBalancedJsonCandidate(cleaned, '{'))
  addCandidate('largest_outer_object_code_fence_stripped', findLargestBalancedJsonCandidate(codeFenceStripped, '{'))

  for (const candidate of findBalancedJsonCandidates(cleaned)) {
    addCandidate('balanced_candidate', candidate)
  }
  if (codeFenceStripped !== cleaned) {
    for (const candidate of findBalancedJsonCandidates(codeFenceStripped)) {
      addCandidate('balanced_candidate_code_fence_stripped', candidate)
    }
  }
  return candidates
}

function findLargestBalancedJsonCandidate(text, openChar = '{') {
  return findBalancedJsonCandidates(text)
    .filter(candidate => candidate.trim().startsWith(openChar))
    .sort((a, b) => b.length - a.length)[0] || ''
}

function validateVolumePlanRoot(parsed, source = '') {
  if (Array.isArray(parsed)) {
    const validation = validateVolumeArray(parsed, source)
    return validation.ok
      ? { ok: true, volumes: parsed, sourceObject: { volumes: parsed } }
      : validation
  }
  if (parsed && typeof parsed === 'object') {
    if (!Object.prototype.hasOwnProperty.call(parsed, 'volumes')) {
      return { ok: false, reason: 'object_missing_volumes' }
    }
    const validation = validateVolumeArray(parsed.volumes, source)
    return validation.ok
      ? { ok: true, volumes: parsed.volumes, sourceObject: parsed }
      : validation
  }
  return { ok: false, reason: 'volume_like_validation_failed' }
}

function validateVolumeArray(value, source = '') {
  if (!Array.isArray(value)) return { ok: false, reason: 'volume_like_validation_failed' }
  if (!value.length) return { ok: false, reason: 'volume_like_validation_failed' }
  if (!value.every(item => item && typeof item === 'object' && !Array.isArray(item))) {
    return {
      ok: false,
      reason: source.startsWith('balanced_candidate')
        ? 'nested_array_not_volume_plan'
        : 'array_items_not_volume_objects'
    }
  }
  if (!value.every(isVolumeLikeObject)) return { ok: false, reason: 'volume_like_validation_failed' }
  return { ok: true }
}

function isVolumeLikeObject(item) {
  if (!item || typeof item !== 'object' || Array.isArray(item)) return false
  const hasTitleOrNumber = hasMeaningfulValue(item.title) ||
    hasMeaningfulValue(item.volumeNum) ||
    hasMeaningfulValue(item.volume_num) ||
    hasMeaningfulValue(item.volumeNumber)
  const hasPurpose = hasMeaningfulValue(item.coreGoal) ||
    hasMeaningfulValue(item.core_goal) ||
    hasMeaningfulValue(item.mainConflict) ||
    hasMeaningfulValue(item.main_conflict) ||
    hasMeaningfulValue(item.summary)
  return hasTitleOrNumber && hasPurpose && getVolumeLikeFeatureCount(item) >= 4
}

function getVolumeLikeFeatureCount(item) {
  const checks = [
    item.volumeNum,
    item.volume_num,
    item.volumeNumber,
    item.title,
    item.startChapter,
    item.start_chapter,
    item.endChapter,
    item.end_chapter,
    item.coreGoal,
    item.core_goal,
    item.mainConflict,
    item.main_conflict,
    item.summary
  ]
  return checks.reduce((count, value) => count + (hasMeaningfulValue(value) ? 1 : 0), 0)
}

function hasMeaningfulValue(value) {
  if (value === null || value === undefined) return false
  if (Array.isArray(value)) return value.length > 0
  if (typeof value === 'number') return Number.isFinite(value)
  return String(value).trim().length > 0
}

function assignVolumePlanParseDiagnostics(diagnostics, payload = {}) {
  if (!diagnostics || typeof diagnostics !== 'object') return
  const volumes = Array.isArray(payload.volumes) ? payload.volumes : []
  const firstItem = volumes[0]
  diagnostics.parsedCandidateSource = payload.source || diagnostics.parsedCandidateSource || ''
  diagnostics.parsedCandidateType = describeParsedVolumeCandidateType(payload.parsed)
  diagnostics.parsedFirstItemType = describeVolumePlanValueType(firstItem)
  diagnostics.parsedFirstItemKeys = firstItem && typeof firstItem === 'object' && !Array.isArray(firstItem)
    ? Object.keys(firstItem).slice(0, 20)
    : []
  diagnostics.rejectedParsedCandidates = Array.isArray(payload.rejectedParsedCandidates)
    ? payload.rejectedParsedCandidates
    : []
}

function describeRejectedVolumePlanCandidate(parsed, source, reason) {
  const firstItem = getVolumePlanFirstItem(parsed)
  return {
    source,
    reason,
    candidateType: describeParsedVolumeCandidateType(parsed),
    firstItemType: describeVolumePlanValueType(firstItem),
    firstItemKeys: firstItem && typeof firstItem === 'object' && !Array.isArray(firstItem)
      ? Object.keys(firstItem).slice(0, 20)
      : []
  }
}

function getVolumePlanFirstItem(parsed) {
  if (Array.isArray(parsed)) return parsed[0]
  if (Array.isArray(parsed?.volumes)) return parsed.volumes[0]
  return null
}

function describeParsedVolumeCandidateType(value) {
  if (Array.isArray(value)) return 'array'
  if (value && typeof value === 'object' && Array.isArray(value.volumes)) return 'object_with_volumes'
  return describeVolumePlanValueType(value)
}

function describeVolumePlanValueType(value) {
  if (Array.isArray(value)) return 'array'
  if (value === null) return 'null'
  return typeof value
}

function findBalancedJsonCandidates(text) {
  const candidates = []
  const source = String(text || '')
  for (let start = 0; start < source.length; start += 1) {
    const open = source[start]
    if (open !== '{' && open !== '[') continue
    const stack = [open === '{' ? '}' : ']']
    let inString = false
    let escaped = false
    for (let index = start + 1; index < source.length; index += 1) {
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

function createVolumePlanningDiagnostics({ provider, messages = [], maxTokens = 0 } = {}) {
  const promptChars = messages.reduce((sum, message) => sum + String(message.content || '').length, 0)
  return {
    providerId: provider?.id || '',
    modelName: provider?.model || provider?.modelName || provider?.name || '',
    supportsJSON: provider?.supportsJSON !== false,
    promptChars,
    promptTokensApprox: Math.ceil(promptChars / 2),
    maxTokens,
    startedAt: new Date().toISOString(),
    endedAt: '',
    finishReason: '',
    usage: null,
    rawHead: '',
    rawTail: '',
    containsMarkdownCodeBlock: false,
    likelyTruncated: false,
    parsedCandidateSource: '',
    parsedCandidateType: '',
    parsedFirstItemType: '',
    parsedFirstItemKeys: [],
    rejectedParsedCandidates: [],
    parsedVolumeCount: 0,
    normalizedVolumeCount: 0,
    droppedVolumes: [],
    saveAttempted: false,
    savedVolumeCount: 0,
    saveErrors: [],
    failureStage: '',
    parseError: '',
    repairTriggered: false,
    repairSucceeded: false,
    repairRawHead: '',
    repairRawTail: '',
    repairFinishReason: '',
    repairUsage: null,
    repairError: '',
    compactRetryTriggered: false,
    compactRetrySucceeded: false,
    compactRawHead: '',
    compactRawTail: '',
    compactFinishReason: '',
    compactUsage: null,
    compactError: '',
    error: ''
  }
}

function updateVolumePlanningDiagnosticsFromResult(diagnostics, result, text = '') {
  const raw = text || stringifyModelResult(result)
  diagnostics.finishReason = getFinishReason(result)
  diagnostics.usage = normalizeUsage(getUsage(result))
  diagnostics.rawHead = snippet(raw, 1500)
  diagnostics.rawTail = tailSnippet(raw, 800)
  diagnostics.containsMarkdownCodeBlock = /```/.test(String(raw || ''))
  diagnostics.likelyTruncated = diagnostics.finishReason === 'length' || isLikelyTruncatedVolumePlan(raw)
}

function compactVolumePlanningDiagnostics(diagnostics = {}) {
  return {
    providerId: diagnostics.providerId || '',
    modelName: diagnostics.modelName || '',
    supportsJSON: diagnostics.supportsJSON !== false,
    promptChars: diagnostics.promptChars || 0,
    promptTokensApprox: diagnostics.promptTokensApprox || 0,
    maxTokens: diagnostics.maxTokens || 0,
    startedAt: diagnostics.startedAt || '',
    endedAt: diagnostics.endedAt || '',
    finishReason: diagnostics.finishReason || '',
    usage: diagnostics.usage || null,
    rawHead: diagnostics.rawHead || '',
    rawTail: diagnostics.rawTail || '',
    containsMarkdownCodeBlock: Boolean(diagnostics.containsMarkdownCodeBlock),
    likelyTruncated: Boolean(diagnostics.likelyTruncated),
    parsedCandidateSource: diagnostics.parsedCandidateSource || '',
    parsedCandidateType: diagnostics.parsedCandidateType || '',
    parsedFirstItemType: diagnostics.parsedFirstItemType || '',
    parsedFirstItemKeys: Array.isArray(diagnostics.parsedFirstItemKeys)
      ? diagnostics.parsedFirstItemKeys
      : [],
    rejectedParsedCandidates: Array.isArray(diagnostics.rejectedParsedCandidates)
      ? diagnostics.rejectedParsedCandidates
      : [],
    parsedVolumeCount: diagnostics.parsedVolumeCount || 0,
    normalizedVolumeCount: diagnostics.normalizedVolumeCount || 0,
    droppedVolumes: Array.isArray(diagnostics.droppedVolumes) ? diagnostics.droppedVolumes : [],
    saveAttempted: Boolean(diagnostics.saveAttempted),
    savedVolumeCount: diagnostics.savedVolumeCount || 0,
    saveErrors: Array.isArray(diagnostics.saveErrors) ? diagnostics.saveErrors : [],
    failureStage: diagnostics.failureStage || '',
    parseError: diagnostics.parseError || '',
    repairTriggered: Boolean(diagnostics.repairTriggered),
    repairSucceeded: Boolean(diagnostics.repairSucceeded),
    repairRawHead: diagnostics.repairRawHead || '',
    repairRawTail: diagnostics.repairRawTail || '',
    repairFinishReason: diagnostics.repairFinishReason || '',
    repairUsage: diagnostics.repairUsage || null,
    repairError: diagnostics.repairError || '',
    compactRetryTriggered: Boolean(diagnostics.compactRetryTriggered),
    compactRetrySucceeded: Boolean(diagnostics.compactRetrySucceeded),
    compactRawHead: diagnostics.compactRawHead || '',
    compactRawTail: diagnostics.compactRawTail || '',
    compactFinishReason: diagnostics.compactFinishReason || '',
    compactUsage: diagnostics.compactUsage || null,
    compactError: diagnostics.compactError || '',
    error: diagnostics.error || ''
  }
}

function saveVolumePlanningDiagnostics(projectId, diagnostics) {
  if (typeof window === 'undefined' || !window.localStorage || !projectId) return
  const key = `${VOLUME_PLAN_DIAGNOSTICS_PREFIX}:${projectId}`
  if (!diagnostics) {
    window.localStorage.removeItem(key)
    return
  }
  window.localStorage.setItem(key, JSON.stringify(diagnostics))
}

function isLikelyTruncatedVolumePlan(text) {
  const value = String(text || '').trim()
  if (!value) return false
  if (/```/.test(value) && !/```\s*$/.test(value) && (value.match(/```/g) || []).length % 2 === 1) return true
  const last = value[value.length - 1]
  if (last && !['}', ']'].includes(last)) return true
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

function getFinishReason(result) {
  return result?.choices?.[0]?.finish_reason || result?.finishReason || ''
}

function getUsage(result) {
  return result?.usage || null
}

function normalizeUsage(usage) {
  if (!usage || typeof usage !== 'object') return null
  return {
    promptTokens: usage.prompt_tokens ?? usage.promptTokens ?? null,
    completionTokens: usage.completion_tokens ?? usage.completionTokens ?? null,
    totalTokens: usage.total_tokens ?? usage.totalTokens ?? null,
    reasoningTokens: usage.completion_tokens_details?.reasoning_tokens ?? usage.reasoningTokens ?? null
  }
}

function stringifyModelResult(result) {
  try {
    return JSON.stringify(result || '')
  } catch {
    return String(result || '')
  }
}

function snippet(value, max = 300) {
  return String(value || '').slice(0, max)
}

function tailSnippet(value, max = 800) {
  return String(value || '').slice(-max)
}

function normalizeGeneratedVolumes(items, project) {
  return normalizeGeneratedVolumesWithDiagnostics(items, project).volumes
}

function normalizeGeneratedVolumesWithDiagnostics(items, project) {
  const sourceItems = Array.isArray(items) ? items : []
  const targetChapters = Number(project?.targetChapters || project?.target_chapters || 100)
  const targetWords = Number(project?.targetWords || project?.target_words || 100000)
  const count = Math.max(1, sourceItems.length)
  const ranges = buildVolumeRanges(targetChapters, targetWords, count)
  const droppedVolumes = []

  const volumes = sourceItems
    .map((item, index) => {
      if (!item || typeof item !== 'object') {
        droppedVolumes.push({
          volumeNum: index + 1,
          title: '',
          dropReason: 'invalid_volume_object'
        })
        return null
      }
      const range = ranges[index]
      const modelStart = Number(item.startChapter || item.start_chapter || 0)
      const modelEnd = Number(item.endChapter || item.end_chapter || 0)
      const startChapter = modelStart > 0 ? modelStart : range.startChapter
      const endChapter = modelEnd >= startChapter ? modelEnd : range.endChapter
      const normalized = normalizeVolume({
        volumeNum: Number(item.volumeNum || item.volume_num || index + 1),
        title: truncateVolumeField(item.title || `第 ${index + 1} 卷`, 80),
        startChapter,
        endChapter,
        targetWords: Number(item.targetWords || item.target_words || range.targetWords || 0),
        coreGoal: truncateVolumeField(item.coreGoal || item.core_goal || '', 220),
        mainConflict: truncateVolumeField(item.mainConflict || item.main_conflict || '', 220),
        keyCharacters: normalizeVolumeList(item.keyCharacters || item.key_characters || [], 4, 40),
        summary: truncateVolumeField(item.summary || '', 360),
        foreshadowingPlan: normalizeVolumeList(item.foreshadowingPlan || item.foreshadowing_plan || item.foreshadowing || [], 3, 120),
        unresolvedItems: normalizeVolumeList(item.unresolvedItems || item.unresolved_items || item.deferredItems || [], 3, 120),
        handoffPoint: truncateVolumeField(item.handoffPoint || item.handoff_point || item.handoff || '', 220),
        status: index === 0 ? 'active' : 'planned'
      })
      const dropReason = getVolumeDropReason(normalized, targetChapters)
      if (dropReason) {
        droppedVolumes.push({
          volumeNum: normalized.volumeNum || index + 1,
          title: normalized.title || '',
          dropReason
        })
        return null
      }
      return normalized
    })
    .filter(Boolean)
    .sort((a, b) => a.volumeNum - b.volumeNum)

  return { volumes, droppedVolumes }
}

function getVolumeDropReason(volume, targetChapters = 0) {
  if (!volume.title) return 'missing_title'
  if (!Number.isFinite(volume.startChapter) || !Number.isFinite(volume.endChapter)) return 'invalid_chapter_range'
  if (volume.startChapter < 1 || volume.endChapter < volume.startChapter) return 'invalid_chapter_range'
  if (targetChapters && volume.startChapter > targetChapters) return 'range_outside_project'
  return ''
}

function truncateVolumeField(value, max = 200) {
  return String(value || '').replace(/\s+/g, ' ').trim().slice(0, max)
}

function normalizeVolumeList(value, maxItems = 3, maxChars = 80) {
  const list = Array.isArray(value) ? value : splitList(value)
  return list
    .map(item => truncateVolumeField(item, maxChars))
    .filter(Boolean)
    .slice(0, maxItems)
}

function buildVolumeRanges(targetChapters, targetWords, count) {
  const safeChapters = Math.max(1, Number(targetChapters || 1))
  const safeWords = Math.max(0, Number(targetWords || 0))
  const safeCount = Math.max(1, Number(count || 1))
  const size = Math.ceil(safeChapters / safeCount)
  return Array.from({ length: safeCount }, (_, index) => {
    const startChapter = index * size + 1
    const endChapter = Math.min((index + 1) * size, safeChapters)
    const ratio = Math.max(1, endChapter - startChapter + 1) / safeChapters
    return {
      startChapter,
      endChapter,
      targetWords: Math.round(safeWords * ratio)
    }
  })
}

function normalizeVolume(data) {
  const provenance = normalizeStateProvenance(data)
  return {
    volumeNum: Number(data.volumeNum || 1),
    title: data.title || '',
    startChapter: Number(data.startChapter || 1),
    endChapter: Number(data.endChapter || data.startChapter || 1),
    targetWords: Number(data.targetWords || 0),
    coreGoal: data.coreGoal || '',
    mainConflict: data.mainConflict || '',
    keyCharacters: Array.isArray(data.keyCharacters)
      ? data.keyCharacters
      : splitList(data.keyCharacters),
    summary: data.summary || '',
    foreshadowingPlan: Array.isArray(data.foreshadowingPlan)
      ? data.foreshadowingPlan
      : splitList(data.foreshadowingPlan),
    unresolvedItems: Array.isArray(data.unresolvedItems)
      ? data.unresolvedItems
      : splitList(data.unresolvedItems),
    handoffPoint: data.handoffPoint || '',
    status: data.status || 'planned',
    sourceChapterNum: provenance.sourceChapterNum,
    sourceVersionId: provenance.sourceVersionId,
    runId: provenance.runId,
    finalizationId: provenance.finalizationId,
    commitStatus: provenance.commitStatus,
    provenance
  }
}

function splitList(value) {
  if (!value) return []
  return String(value)
    .split(/[，,、\n]/)
    .map(item => item.trim())
    .filter(Boolean)
}

async function refreshProject(projectId) {
  const projectStore = useProjectStore()
  if (projectStore.currentProject?.id === projectId) {
    await projectStore.openProject(projectId)
  }
}
