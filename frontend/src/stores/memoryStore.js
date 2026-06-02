import { defineStore } from 'pinia'
import { ref } from 'vue'
import { chatCompletion } from '@/api/ai'
import { api } from '@/api/db/client'
import { useProviderStore } from './providerStore'
import { useNovelStore } from './novelStore'
import { useSettingStore } from './settingStore'
import {
  buildSummarySystemPrompt,
  buildSummaryPrompt
} from '@/prompts/summary'
import {
  buildExtractionSystemPrompt,
  buildExtractionPrompt,
  buildExtractionRepairPrompt,
  buildCompactExtractionPrompt
} from '@/prompts/extraction'
import {
  buildAuditSystemPrompt,
  buildAuditPrompt,
  buildAuditRepairPrompt
} from '@/prompts/audit'
import {
  buildStyleSystemPrompt,
  buildStyleAnalysisPrompt
} from '@/prompts/style'
import {
  buildPacingSystemPrompt,
  buildPacingPrompt
} from '@/prompts/pacing'
import {
  buildSettingExtractionSystemPrompt,
  buildSettingExtractionPrompt,
  buildSettingExtractionRepairPrompt
} from '@/prompts/settingExtraction'
import {
  buildVolumeAuditSystemPrompt,
  buildVolumeAuditPrompt
} from '@/prompts/volumeAudit'
import {
  buildVolumeSummarySystemPrompt,
  buildVolumeSummaryPrompt
} from '@/prompts/volumeSummary'

export const useMemoryStore = defineStore('memory', () => {
  const processing = ref(false)
  const lastSummary = ref(null)
  const lastExtractions = ref([])
  const lastAuditResult = ref(null)
  const lastStyleAnalysis = ref(null)
  const lastPacingAnalysis = ref(null)
  const lastSettingChanges = ref([])
  const lastVolumeAuditResult = ref(null)
  const lastVolumeSummaryResult = ref(null)
  const styleAnalyzing = ref(false)
  const pacingAnalyzing = ref(false)
  const volumeAuditing = ref(false)
  const volumeSummarizing = ref(false)

  function parseAIJson(text) {
    if (typeof text !== 'string') {
      if (Array.isArray(text)) {
        const block = text.find(b => b.type === 'text')
        text = block?.text || ''
      } else if (text?.content) {
        text = typeof text.content === 'string' ? text.content : JSON.stringify(text.content)
      } else if (text?.choices?.[0]?.message?.content) {
        text = text.choices[0].message.content
      } else {
        text = JSON.stringify(text)
      }
    }
    const jsonMatch = text.match(/\{[\s\S]*\}|\[[\s\S]*\]/)
    if (!jsonMatch) throw new Error('无法解析 AI 返回的 JSON')
    return JSON.parse(jsonMatch[0])
  }

  async function getProvider(projectId, preferredKey = 'summaryModelId') {
    const providerStore = useProviderStore()
    await providerStore.ensureProvidersLoaded()
    const bindings = await providerStore.getBindings(projectId)
    const modelId = bindings?.[preferredKey] || bindings?.summaryModelId || bindings?.writingModelId
    const provider = providerStore.providers.find(p => p.id === modelId) || providerStore.providers[0]
    if (!provider) throw new Error('请先在设置中配置模型')
    return provider
  }

  // === 章节摘要生成 ===
  async function generateSummary(projectId, chapterContent, chapterNum) {
    try {
      const provider = await getProvider(projectId, 'summaryModelId')
      const messages = [
        { role: 'system', content: buildSummarySystemPrompt() },
        { role: 'user', content: buildSummaryPrompt(chapterContent, chapterNum) }
      ]
      const result = await chatCompletion(provider, messages, { maxTokens: 1024, temperature: 0.3 })
      const data = parseAIJson(result)
      lastSummary.value = data
      return data
    } catch (e) {
      console.error('摘要生成失败:', e.message)
      throw e
    }
  }

  // === Canon 事实提取 ===
  async function extractFacts(projectId, chapterContent, chapterNum) {
    try {
      const provider = await getProvider(projectId, 'extractionModelId')
      const novelStore = useNovelStore()
      const existingFacts = novelStore.canonFacts?.filter(f => f.status === 'accepted') || []

      const messages = [
        { role: 'system', content: buildExtractionSystemPrompt() },
        { role: 'user', content: buildExtractionPrompt(chapterContent, chapterNum, existingFacts) }
      ]
      const result = await chatCompletion(provider, messages, jsonOptions(provider, { maxTokens: 3000, temperature: 0.25 }))
      const text = getCompletionText(result)
      let parsed = parseFactExtractionText(text)
      let repairText = ''
      let compactText = ''

      if (!parsed.ok && text.trim()) {
        try {
          const repairResult = await chatCompletion(provider, [
            { role: 'system', content: '你是 JSON 修复器。只能输出合法 JSON，不要解释。' },
            { role: 'user', content: buildExtractionRepairPrompt(text) }
          ], jsonOptions(provider, { maxTokens: 3000, temperature: 0 }))
          repairText = getCompletionText(repairResult)
          parsed = parseFactExtractionText(repairText)
        } catch (repairError) {
          console.warn('事实提取 JSON 修复失败:', repairError.message)
        }
      }

      if (!parsed.ok) {
        const compactResult = await chatCompletion(provider, [
          { role: 'system', content: buildExtractionSystemPrompt() },
          { role: 'user', content: buildCompactExtractionPrompt(chapterContent, chapterNum, existingFacts, repairText || text) }
        ], jsonOptions(provider, { maxTokens: 3000, temperature: 0.15 }))
        compactText = getCompletionText(compactResult)
        parsed = parseFactExtractionText(compactText)
      }

      if (!parsed.ok) {
        const snippet = (compactText || repairText || text || '').slice(0, 500)
        throw new Error(`AI 没有返回可解析的记忆事实 JSON。返回片段：${snippet}`)
      }

      lastExtractions.value = parsed.facts
      return parsed.facts
    } catch (e) {
      console.error('事实提取失败:', e.message)
      throw e
    }
  }

  // === 一致性审稿 ===
  async function auditChapter(projectId, chapterContent, chapterNum) {
    try {
      const provider = await getProvider(projectId, 'auditModelId')
      const novelStore = useNovelStore()

      const context = {
        chapterNum,
        bible: novelStore.bible,
        characters: novelStore.characters,
        canonFacts: novelStore.canonFacts?.filter(f => f.status === 'accepted') || [],
        plotThreads: novelStore.plotThreads?.filter(t => t.status === 'planted' || t.status === 'developing') || []
      }

      const messages = [
        { role: 'system', content: buildAuditSystemPrompt() },
        { role: 'user', content: buildAuditPrompt(chapterContent, context) }
      ]
      const result = await chatCompletion(provider, messages, jsonOptions(provider, { maxTokens: 4096, temperature: 0.25 }))
      const text = getCompletionText(result)
      const data = await parseAuditResult(provider, text)
      lastAuditResult.value = data
      return data
    } catch (e) {
      console.error('审稿失败:', e.message)
      throw e
    }
  }

  // === 风格分析 ===
  async function analyzeStyle(projectId, chapterContent, chapterNum) {
    const provider = await getProvider(projectId, 'polishModelId')
    const messages = [
      { role: 'system', content: buildStyleSystemPrompt() },
      { role: 'user', content: buildStyleAnalysisPrompt(chapterContent) }
    ]
    styleAnalyzing.value = true
    try {
      const result = await chatCompletion(provider, messages, { maxTokens: 1024, temperature: 0.3 })
      const data = parseAIJson(result)
      data.analyzedChapterNum = chapterNum
      lastStyleAnalysis.value = data
      return data
    } finally {
      styleAnalyzing.value = false
    }
  }

  // === 节奏分析 ===
  async function analyzePacing(projectId, chapterContent, chapterNum) {
    const provider = await getProvider(projectId, 'auditModelId')
    const messages = [
      { role: 'system', content: buildPacingSystemPrompt() },
      { role: 'user', content: buildPacingPrompt(chapterContent) }
    ]
    pacingAnalyzing.value = true
    try {
      const result = await chatCompletion(provider, messages, { maxTokens: 1536, temperature: 0.3 })
      const data = parseAIJson(result)
      lastPacingAnalysis.value = data
      return data
    } finally {
      pacingAnalyzing.value = false
    }
  }

  // === 设定库变更提取 ===
  async function extractSettingChanges(projectId, chapterContent, chapterNum) {
    try {
      const provider = await getProvider(projectId, 'extractionModelId')
      const settingStore = useSettingStore()
      await settingStore.loadEntities(projectId)
      await settingStore.loadRelations(projectId)
      await settingStore.loadChangeEvents(projectId)

      const messages = [
        { role: 'system', content: buildSettingExtractionSystemPrompt() },
        {
          role: 'user',
          content: buildSettingExtractionPrompt(
            chapterContent,
            chapterNum,
            settingStore.entities,
            settingStore.relations
          )
        }
      ]
      const result = await chatCompletion(provider, messages, jsonOptions(provider, { maxTokens: 4096, temperature: 0.2 }))
      const text = getCompletionText(result)
      let rawChanges = extractSettingChangesPayload(text)
      if (!rawChanges.length && text.trim()) {
        const repairResult = await chatCompletion(provider, [
          { role: 'system', content: '你是 JSON 修复器。只能输出合法 JSON，不要解释。' },
          { role: 'user', content: buildSettingExtractionRepairPrompt(text) }
        ], jsonOptions(provider, { maxTokens: 4096, temperature: 0 }))
        rawChanges = extractSettingChangesPayload(getCompletionText(repairResult))
      }
      const changes = normalizeSettingChanges(rawChanges, settingStore)
      lastSettingChanges.value = changes
      return changes
    } catch (e) {
      console.error('设定变更提取失败:', e.message)
      throw e
    }
  }

  async function auditVolume(projectId, volume, projectInfo = null) {
    volumeAuditing.value = true
    try {
      const provider = await getProvider(projectId, 'auditModelId')
      const novelStore = useNovelStore()
      const settingStore = useSettingStore()

      if (!settingStore.entities.length) {
        await settingStore.loadEntities(projectId)
      }
      if (!settingStore.relations.length) {
        await settingStore.loadRelations(projectId)
      }

      const rawContext = await api.volumes.context(projectId, volume.id)
      const context = buildVolumeAuditContext({
        projectInfo,
        volume,
        rawContext,
        bible: novelStore.bible,
        canonFacts: (novelStore.canonFacts || []).filter(f =>
          f.status === 'accepted' &&
          Number(f.chapterNum || 0) >= Number(volume.startChapter || 0) &&
          Number(f.chapterNum || 0) <= Number(volume.endChapter || 0)
        ),
        plotThreads: (novelStore.plotThreads || []).filter(thread => {
          const planted = Number(thread.plantedChapter || 0)
          const resolved = Number(thread.resolvedChapter || 0)
          return (
            (planted >= Number(volume.startChapter || 0) && planted <= Number(volume.endChapter || 0)) ||
            (!resolved && ['planted', 'developing', 'transformed'].includes(thread.status))
          )
        }),
        entities: settingStore.entities,
        relations: settingStore.relations
      })

      const result = await chatCompletion(provider, [
        { role: 'system', content: buildVolumeAuditSystemPrompt() },
        { role: 'user', content: buildVolumeAuditPrompt(context) }
      ], { maxTokens: 4096, temperature: 0.3 })

      const data = parseAIJson(result)
      lastVolumeAuditResult.value = data
      return data
    } catch (e) {
      console.error('分卷审稿失败:', e.message)
      throw e
    } finally {
      volumeAuditing.value = false
    }
  }

  async function summarizeVolume(projectId, volume, projectInfo = null) {
    volumeSummarizing.value = true
    try {
      const provider = await getProvider(projectId, 'summaryModelId')
      const novelStore = useNovelStore()
      const settingStore = useSettingStore()

      if (!settingStore.entities.length) {
        await settingStore.loadEntities(projectId)
      }
      if (!settingStore.relations.length) {
        await settingStore.loadRelations(projectId)
      }

      const rawContext = await api.volumes.context(projectId, volume.id)
      const context = buildVolumeAuditContext({
        projectInfo,
        volume,
        rawContext,
        bible: novelStore.bible,
        canonFacts: (novelStore.canonFacts || []).filter(f =>
          f.status === 'accepted' &&
          Number(f.chapterNum || 0) >= Number(volume.startChapter || 0) &&
          Number(f.chapterNum || 0) <= Number(volume.endChapter || 0)
        ),
        plotThreads: (novelStore.plotThreads || []).filter(thread => {
          const planted = Number(thread.plantedChapter || 0)
          const resolved = Number(thread.resolvedChapter || 0)
          return (
            (planted >= Number(volume.startChapter || 0) && planted <= Number(volume.endChapter || 0)) ||
            (!resolved && ['planted', 'developing', 'transformed'].includes(thread.status))
          )
        }),
        entities: settingStore.entities,
        relations: settingStore.relations
      })
      context.auditSummary = formatAuditReport(volume.auditReport)

      const result = await chatCompletion(provider, [
        { role: 'system', content: buildVolumeSummarySystemPrompt() },
        { role: 'user', content: buildVolumeSummaryPrompt(context) }
      ], { maxTokens: 4096, temperature: 0.25 })

      const data = parseAIJson(result)
      lastVolumeSummaryResult.value = data
      return data
    } catch (e) {
      console.error('分卷阶段总结失败:', e.message)
      throw e
    } finally {
      volumeSummarizing.value = false
    }
  }

  const requiredFinalizationSteps = new Set(['summary', 'facts', 'settingChanges'])

  function recordFinalizationStepError(results, step, error) {
    const item = {
      step,
      message: error?.message || String(error || 'unknown error'),
      required: requiredFinalizationSteps.has(step)
    }
    results.errors.push(item)
    console.warn(`定稿后处理步骤失败(${step}):`, item.message)
  }

  // === 批量处理：定稿后自动执行记忆和设定提取 ===
  async function processChapterFinalization(projectId, chapterContent, chapterNum, options = {}) {
    const includeAudit = options.includeAudit === true
    processing.value = true
    try {
      const results = { summary: null, facts: [], settingChanges: [], audit: null, errors: [] }

      try { results.summary = await generateSummary(projectId, chapterContent, chapterNum) } catch (e) { recordFinalizationStepError(results, 'summary', e) }
      try {
        results.facts = await extractFacts(projectId, chapterContent, chapterNum)
        if (!results.facts?.length) {
          recordFinalizationStepError(
            results,
            'facts',
            new Error('没有提取到可保存的记忆事实；请重试定稿后处理，完成后再继续下一章。')
          )
        }
      } catch (e) { recordFinalizationStepError(results, 'facts', e) }
      try { results.settingChanges = await extractSettingChanges(projectId, chapterContent, chapterNum) } catch (e) { recordFinalizationStepError(results, 'settingChanges', e) }
      if (includeAudit) {
        try { results.audit = await auditChapter(projectId, chapterContent, chapterNum) } catch (e) { recordFinalizationStepError(results, 'audit', e) }
      }
      const requiredFailures = results.errors.filter(error => error.required)

      const novelStore = useNovelStore()
      const settingStore = useSettingStore()
      for (const f of results.facts) {
        await novelStore.saveCanonFact({
          projectId,
          chapterNum,
          factType: f.factType || 'plot',
          content: f.content || '',
          relatedCharacters: f.relatedCharacters || [],
          relatedPlotThreads: f.relatedPlotThreads || [],
          evidence: f.evidence || '',
          confidence: f.confidence || 0.8,
          status: 'pending_review'
        })
      }

      if (results.summary?.characterChanges?.length) {
        await novelStore.loadCharacters(projectId)
        for (const change of results.summary.characterChanges) {
          const existing = novelStore.characters.find(c => c.name === change.character)
          if (existing) {
            await novelStore.saveCharacter({
              ...existing,
              projectId,
              id: existing.id,
              softState: {
                ...existing.softState,
                lastChange: change.change,
                lastChangeChapter: chapterNum
              },
              hardState: {
                ...existing.hardState,
                lastUpdatedChapter: chapterNum
              }
            })
          }
        }
      }

      await settingStore.loadEntities(projectId)
      await settingStore.loadRelations(projectId)
      await settingStore.loadChangeEvents(projectId)
      if (results.settingChanges?.length) {
        for (const change of results.settingChanges) {
          const entityType = change.entityType || 'character'
          const entityName = change.entityName || change.name || ''
          if (!entityName && change.changeType !== 'relationship') continue
          const existingEntity = settingStore.entities.find(e =>
            e.entityType === entityType && e.name === entityName
          )
          const payload = {
            entityType,
            entityId: existingEntity?.id || null,
            entityName,
            changeType: change.changeType || 'update_entity',
            fieldPath: change.fieldPath || (change.changeType === 'new_entity' ? 'summary' : ''),
            oldValue: change.oldValue || '',
            newValue: normalizeSettingChangeValue(change),
            chapterNum,
            evidence: change.evidence || '',
            confidence: change.confidence ?? 0.8,
            status: 'pending_review'
          }
          if (!hasDuplicatePendingChange(settingStore.changeEvents, payload)) {
            await settingStore.saveChangeEvent(projectId, payload)
          }
        }
      } else if (results.summary?.characterChanges?.length) {
        for (const change of results.summary.characterChanges) {
          const existingEntity = settingStore.entities.find(e =>
            e.entityType === 'character' && e.name === change.character
          )
          await settingStore.saveChangeEvent(projectId, {
            entityType: 'character',
            entityId: existingEntity?.id || null,
            entityName: change.character || '',
            changeType: 'chapter_state_change',
            fieldPath: '状态变化',
            oldValue: '',
            newValue: change.change || '',
            chapterNum,
            evidence: results.summary?.summary || '',
            confidence: 0.7,
            status: 'pending_review'
          })
        }
      }

      if (!results.settingChanges?.length && results.summary?.newElements?.characters?.length) {
        for (const charName of results.summary.newElements.characters) {
          const exists = settingStore.entities.find(e =>
            e.entityType === 'character' && e.name === charName
          )
          if (!exists) {
            await settingStore.saveChangeEvent(projectId, {
              entityType: 'character',
              entityName: charName,
              changeType: 'new_entity',
              fieldPath: '新增人物',
              newValue: `第 ${chapterNum} 章出现的新人物：${charName}`,
              chapterNum,
              evidence: results.summary?.summary || '',
              confidence: 0.65,
              status: 'pending_review'
            })
          }
        }
      }

      if (results.summary?.newElements?.characters?.length) {
        for (const charName of results.summary.newElements.characters) {
          const exists = novelStore.characters.find(c => c.name === charName)
          if (!exists) {
            await novelStore.saveCharacter({
              projectId,
              name: charName,
              role: 'supporting',
              hardState: { lastUpdatedChapter: chapterNum }
            })
          }
        }
      }

      const { useWriterStore } = await import('./writerStore')
      const writerStore = useWriterStore()
      const chapter = writerStore.chapters.find(c => c.chapterNum === chapterNum)
      if (chapter && results.summary) {
        const updatedChapter = await api.chapters.updateSummary(projectId, chapter.id, {
          summary: results.summary.summary || ''
        })
        Object.assign(chapter, updatedChapter || { summary: results.summary.summary || '' })
        if (writerStore.currentChapter?.id === chapter.id) {
          writerStore.currentChapter = { ...writerStore.currentChapter, ...chapter }
        }
      }

      if (requiredFailures.length) {
        results.requiredFailures = requiredFailures
      }

      return results
    } finally {
      processing.value = false
    }
  }

  return {
    processing,
    lastSummary,
    lastExtractions,
    lastAuditResult,
    lastStyleAnalysis,
    lastPacingAnalysis,
    lastSettingChanges,
    lastVolumeAuditResult,
    lastVolumeSummaryResult,
    styleAnalyzing,
    pacingAnalyzing,
    volumeAuditing,
    volumeSummarizing,
    generateSummary,
    extractFacts,
    auditChapter,
    analyzeStyle,
    analyzePacing,
    extractSettingChanges,
    auditVolume,
    summarizeVolume,
    processChapterFinalization
  }
})

function normalizeSettingChanges(changes, settingStore) {
  if (!Array.isArray(changes)) return []
  const seen = new Set()
  return changes
    .map(change => normalizeSettingChange(change, settingStore))
    .filter(Boolean)
    .filter(change => {
      const key = [
        change.entityType,
        change.entityName,
        change.changeType,
        change.fieldPath,
        normalizeSettingChangeValue(change)
      ].join('::')
      if (seen.has(key)) return false
      seen.add(key)
      return true
    })
}

function getCompletionText(result) {
  if (typeof result === 'string') return result
  if (Array.isArray(result)) {
    const block = result.find(item => item?.type === 'text')
    return block?.text || JSON.stringify(result)
  }
  if (typeof result?.content === 'string') return result.content
  if (result?.choices?.[0]?.message?.content) return result.choices[0].message.content
  return result ? JSON.stringify(result) : ''
}

function jsonOptions(provider, options = {}) {
  return provider?.supportsJSON === false
    ? options
    : { ...options, responseFormat: 'json' }
}

async function parseAuditResult(provider, text) {
  const parsed = parseJsonCandidates(text)
  for (const item of parsed) {
    const normalized = normalizeAuditResult(item)
    if (normalized) return normalized
  }

  if (String(text || '').trim()) {
    try {
      const repairResult = await chatCompletion(provider, [
        { role: 'system', content: '你是 JSON 修复器。只能输出合法 JSON，不要解释。' },
        { role: 'user', content: buildAuditRepairPrompt(text) }
      ], jsonOptions(provider, { maxTokens: 4096, temperature: 0 }))
      const repairedText = getCompletionText(repairResult)
      for (const item of parseJsonCandidates(repairedText)) {
        const normalized = normalizeAuditResult(item)
        if (normalized) return normalized
      }
    } catch (e) {
      console.warn('审稿 JSON 修复失败:', e.message)
    }
  }

  return buildFallbackAuditResult(text)
}

function normalizeAuditResult(value) {
  const payload = Array.isArray(value) ? { issues: value } : value
  if (!payload || typeof payload !== 'object') return null
  const rawIssues = Array.isArray(payload.issues)
    ? payload.issues
    : Array.isArray(payload.problems)
      ? payload.problems
      : []
  return {
    issues: rawIssues.map(normalizeAuditIssue).filter(Boolean),
    overallAssessment: String(payload.overallAssessment || payload.assessment || payload.summary || '本章审稿完成，未发现模型可结构化输出的总体评价。'),
    styleConsistency: String(payload.styleConsistency || payload.style || '暂无风格一致性评价。'),
    characterConsistency: String(payload.characterConsistency || payload.character || '暂无角色一致性评价。'),
    recommendations: normalizeStringList(payload.recommendations || payload.suggestions || payload.nextSteps)
  }
}

function normalizeAuditIssue(issue) {
  if (!issue || typeof issue !== 'object') return null
  return {
    severity: pickEnum(issue.severity, ['critical', 'major', 'minor', 'suggestion'], 'suggestion'),
    type: pickEnum(issue.type, [
      'contradiction',
      'character_inconsistency',
      'world_rule_violation',
      'pacing',
      'dialogue',
      'logic',
      'quality',
      'human_motivation',
      'emotional_logic',
      'ai_tone',
      'template_ending',
      'surface_emotion',
      'tool_character',
      'info_dump',
      'cliche_imagery'
    ], 'quality'),
    description: String(issue.description || issue.problem || issue.summary || '').trim(),
    location: String(issue.location || issue.evidence || issue.quote || '').trim(),
    suggestion: String(issue.suggestion || issue.fix || issue.advice || '').trim(),
    replacement: String(issue.replacement || issue.rewrite || issue.fixedText || issue.newText || '').trim(),
    reason: String(issue.reason || issue.why || '').trim()
  }
}

function buildFallbackAuditResult(rawText) {
  return {
    issues: [],
    overallAssessment: '审稿模型返回内容未能解析为结构化 JSON，本次未生成可保存的问题列表。建议重新审稿，或复制模型返回片段排查模型格式稳定性。',
    styleConsistency: '未能解析。',
    characterConsistency: '未能解析。',
    recommendations: ['重新执行本章审稿。', '如连续失败，建议切换审稿模型或降低章节长度后重试。'],
    rawText: String(rawText || '').slice(0, 1200)
  }
}

function pickEnum(value, allowed, fallback) {
  return allowed.includes(value) ? value : fallback
}

function normalizeStringList(value) {
  if (Array.isArray(value)) return value.map(item => String(item || '').trim()).filter(Boolean)
  if (typeof value === 'string') return value.split(/\n|；|;/).map(item => item.trim()).filter(Boolean)
  return []
}

function mergeStringLists(...values) {
  const seen = new Set()
  const merged = []
  for (const value of values) {
    for (const item of normalizeStringList(value)) {
      if (seen.has(item)) continue
      seen.add(item)
      merged.push(item)
    }
  }
  return merged
}

function parseFactExtractionText(text) {
  const parsed = parseJsonCandidates(text)
  for (const item of parsed) {
    const list = pickCanonFactList(item)
    if (Array.isArray(list)) {
      return { ok: true, facts: normalizeCanonFacts(list) }
    }
  }
  return { ok: false, facts: [] }
}

function pickCanonFactList(payload) {
  if (Array.isArray(payload)) return payload
  if (!payload || typeof payload !== 'object') return null
  const keys = ['facts', 'canonFacts', 'items', 'data', 'results']
  for (const key of keys) {
    if (Array.isArray(payload[key])) return payload[key]
  }
  for (const key of keys) {
    const nested = pickCanonFactList(payload[key])
    if (Array.isArray(nested)) return nested
  }
  if (payload.content || payload.factType || payload.evidence) return [payload]
  return null
}

function normalizeCanonFacts(facts) {
  const seen = new Set()
  return (Array.isArray(facts) ? facts : [])
    .map(normalizeCanonFact)
    .filter(Boolean)
    .filter(fact => {
      const key = `${fact.factType}::${fact.content}`
      if (seen.has(key)) return false
      seen.add(key)
      return true
    })
}

function normalizeCanonFact(fact) {
  if (!fact || typeof fact !== 'object') return null
  const content = String(fact.content || fact.summary || fact.fact || '').trim()
  if (!content) return null
  return {
    factType: pickEnum(fact.factType || fact.type, ['world', 'character', 'plot', 'relationship', 'timeline', 'style', 'setting'], 'plot'),
    content,
    relatedCharacters: normalizeStringList(fact.relatedCharacters || fact.characters),
    relatedPlotThreads: mergeStringLists(
      fact.relatedPlotThreads,
      fact.plotThreads,
      fact.threadTags,
      fact.tags
    ),
    evidence: String(fact.evidence || fact.quote || '').trim(),
    confidence: clampConfidence(fact.confidence)
  }
}

function extractSettingChangesPayload(text) {
  const parsed = parseJsonCandidates(text)
  for (const item of parsed) {
    const list = pickSettingChangeList(item)
    if (list.length) return list
  }
  return []
}

function pickSettingChangeList(payload) {
  if (Array.isArray(payload)) return payload
  if (!payload || typeof payload !== 'object') return []
  const keys = ['settingChanges', 'settings', 'changes', 'data', 'items', 'events', 'results']
  for (const key of keys) {
    if (Array.isArray(payload[key])) return payload[key]
  }
  for (const key of keys) {
    const nested = pickSettingChangeList(payload[key])
    if (nested.length) return nested
  }
  if (payload.entityName || payload.name || payload.changeType || payload.entityType) return [payload]
  return []
}

function parseJsonCandidates(text) {
  const clean = String(text || '')
    .replace(/```(?:json)?/gi, '')
    .replace(/```/g, '')
    .trim()
  const candidates = [clean, ...findBalancedJsonBlocks(clean)]
  const parsed = []
  const seen = new Set()
  for (const candidate of candidates) {
    const value = candidate.trim()
    if (!value || seen.has(value)) continue
    seen.add(value)
    try {
      parsed.push(JSON.parse(value))
    } catch {
      // Keep trying other balanced candidates.
    }
  }
  return parsed
}

function findBalancedJsonBlocks(text) {
  const blocks = []
  for (let i = 0; i < text.length; i++) {
    const opener = text[i]
    if (opener !== '{' && opener !== '[') continue
    const closer = opener === '{' ? '}' : ']'
    const stack = [closer]
    let inString = false
    let escaped = false
    for (let j = i + 1; j < text.length; j++) {
      const char = text[j]
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
          blocks.push(text.slice(i, j + 1))
          break
        }
      }
    }
  }
  return blocks
}

function normalizeSettingChange(change, settingStore) {
  if (!change || typeof change !== 'object') return null
  const entityType = normalizeEntityType(change.entityType)
  const changeType = normalizeChangeType(change.changeType)
  const entityName = String(change.entityName || change.name || '').trim()
  const relationValue = changeType === 'relationship' ? normalizeRelationValue(change.newValue) : null
  if (!entityName && !relationValue?.targetEntityName) return null

  const existing = settingStore.entities.find(entity =>
    entity.entityType === entityType && entity.name === entityName
  )
  const fieldPath = normalizeFieldPath(change.fieldPath, changeType)
  return {
    ...change,
    entityType,
    entityName,
    changeType: existing && changeType === 'new_entity' ? 'update_entity' : changeType,
    fieldPath,
    newValue: relationValue || change.newValue || '',
    confidence: clampConfidence(change.confidence),
    importance: Number(change.importance || 3)
  }
}

function normalizeEntityType(type) {
  return ['character', 'faction', 'location', 'power_system', 'technique', 'item'].includes(type)
    ? type
    : 'character'
}

function normalizeChangeType(type) {
  if (type === 'new_entity' || type === 'relationship') return type
  return 'update_entity'
}

function normalizeFieldPath(fieldPath, changeType) {
  if (changeType === 'relationship') return 'relationship'
  const value = String(fieldPath || '').trim()
  return value || (changeType === 'new_entity' ? 'summary' : 'notes')
}

function normalizeRelationValue(value) {
  if (!value) return null
  if (typeof value === 'string') {
    try {
      value = JSON.parse(value)
    } catch {
      return { summary: value }
    }
  }
  if (typeof value !== 'object') return null
  return {
    targetEntityName: String(value.targetEntityName || value.targetName || '').trim(),
    targetEntityType: normalizeEntityType(value.targetEntityType),
    relationType: value.relationType || '关系',
    stance: value.stance || '未知',
    summary: value.summary || ''
  }
}

function clampConfidence(value) {
  const number = Number(value)
  if (!Number.isFinite(number)) return 0.75
  return Math.min(1, Math.max(0, number))
}

function hasDuplicatePendingChange(events, payload) {
  return (events || []).some(event =>
    event.status === 'pending_review' &&
    event.entityType === payload.entityType &&
    event.entityName === payload.entityName &&
    event.changeType === payload.changeType &&
    event.fieldPath === payload.fieldPath &&
    String(event.newValue || '') === String(payload.newValue || '') &&
    Number(event.chapterNum || 0) === Number(payload.chapterNum || 0)
  )
}

function normalizeSettingChangeValue(change) {
  if (change.changeType === 'relationship') {
    return JSON.stringify(change.newValue || {}, null, 0)
  }

  if (change.changeType === 'new_entity') {
    return JSON.stringify({
      summary: change.summary || (typeof change.newValue === 'string' ? change.newValue : ''),
      category: change.category || '',
      importance: change.importance || 3,
      profile: change.profilePatch || {},
      tags: change.tags || []
    }, null, 0)
  }

  return typeof change.newValue === 'object'
    ? JSON.stringify(change.newValue, null, 0)
    : (change.newValue || '')
}

function buildVolumeAuditContext({
  projectInfo,
  volume,
  rawContext,
  bible,
  canonFacts,
  plotThreads,
  entities,
  relations
}) {
  const rangeChapters = rawContext?.chapters || []
  const keyNames = new Set((volume.keyCharacters || []).map(name => String(name).trim()).filter(Boolean))
  const relevantEntities = entities
    .filter(entity => {
      if (keyNames.size) return keyNames.has(entity.name)
      return Number(entity.importance || 0) >= 4
    })
    .slice(0, 12)
  const relevantEntityIds = new Set(relevantEntities.map(entity => entity.id))
  const relevantRelations = relations
    .filter(relation =>
      relevantEntityIds.has(relation.sourceEntityId) ||
      relevantEntityIds.has(relation.targetEntityId)
    )
    .slice(0, 16)

  return {
    projectTitle: projectInfo?.title || '未命名项目',
    projectGenre: projectInfo?.genre || '',
    volumeTitle: volume.title || `第 ${volume.volumeNum} 卷`,
    startChapter: volume.startChapter,
    endChapter: volume.endChapter,
    targetWords: volume.targetWords || 0,
    volumeGoal: volume.coreGoal || '',
    volumeConflict: volume.mainConflict || '',
    keyCharacters: volume.keyCharacters || [],
    bibleSummary: summarizeBible(bible),
    chapterSummaries: formatChapterSummaries(rangeChapters),
    chapterExcerpts: formatChapterExcerpts(rangeChapters),
    canonFacts: formatCanonFacts(canonFacts),
    settingSummary: formatEntities(relevantEntities),
    relationSummary: formatRelations(relevantRelations, entities),
    plotSummary: formatPlotThreads(plotThreads)
  }
}

function summarizeBible(bible) {
  if (!bible) return ''
  return [
    bible.premise ? `作品定位：${bible.premise}` : '',
    bible.themeBible ? `主题母题：${truncateText(bible.themeBible, 600)}` : '',
    bible.worldRules ? `世界规则：${truncateText(bible.worldRules, 800)}` : '',
    bible.styleBible ? `风格要求：${truncateText(bible.styleBible, 500)}` : ''
  ].filter(Boolean).join('\n')
}

function formatChapterSummaries(chapters) {
  if (!chapters.length) return ''
  return chapters.map(ch => {
    const summary = ch.summary || '暂无摘要'
    return `- 第 ${ch.chapterNum} 章《${ch.title || '未命名'}》 [${ch.status || 'unknown'} / ${ch.wordCount || 0}字]：${truncateText(summary, 180)}`
  }).join('\n')
}

function formatChapterExcerpts(chapters) {
  const selected = chapters
    .filter(ch => ch.finalContent || ch.summary)
    .slice(-6)
  if (!selected.length) return ''
  return selected.map(ch => {
    const content = ch.finalContent
      ? buildExcerpt(ch.finalContent)
      : truncateText(ch.summary || '', 300)
    return `### 第 ${ch.chapterNum} 章《${ch.title || '未命名'}》\n${content}`
  }).join('\n\n')
}

function formatCanonFacts(facts) {
  if (!facts.length) return ''
  return facts
    .slice(-24)
    .map(f => `- 第 ${f.chapterNum} 章 [${f.factType}] ${truncateText(f.content || '', 120)}`)
    .join('\n')
}

function formatEntities(entities) {
  if (!entities.length) return ''
  return entities.map(entity => {
    const profile = entity.profile || {}
    const highlight = [
      profile.realm ? `境界=${profile.realm}` : '',
      profile.faction ? `归属=${profile.faction}` : '',
      entity.category ? `类别=${entity.category}` : ''
    ].filter(Boolean).join('，')
    return `- [${entity.entityType}] ${entity.name}${highlight ? `（${highlight}）` : ''}：${truncateText(entity.summary || '暂无概要', 120)}`
  }).join('\n')
}

function formatRelations(relations, entities) {
  if (!relations.length) return ''
  const entityMap = new Map(entities.map(entity => [entity.id, entity.name]))
  return relations.map(relation => {
    const source = entityMap.get(relation.sourceEntityId) || '未知主体'
    const target = entityMap.get(relation.targetEntityId) || '未知客体'
    return `- ${source} -> ${target} [${relation.relationType || '关系'} / ${relation.stance || '未标注'}] ${truncateText(relation.summary || '', 100)}`
  }).join('\n')
}

function formatPlotThreads(plotThreads) {
  if (!plotThreads.length) return ''
  return plotThreads.slice(0, 20).map(thread => {
    return `- [${thread.status}] ${thread.title}：${truncateText(thread.content || '', 100)}`
  }).join('\n')
}

function formatAuditReport(report) {
  if (!report) return ''
  return [
    report.overallAssessment ? `总体评价：${report.overallAssessment}` : '',
    report.stageSummary ? `阶段判断：${report.stageSummary}` : '',
    report.characterArcReview ? `人物弧光：${report.characterArcReview}` : '',
    report.settingConsistency ? `设定一致性：${report.settingConsistency}` : '',
    report.foreshadowingReview ? `伏笔状态：${report.foreshadowingReview}` : '',
    report.pacingReview ? `节奏判断：${report.pacingReview}` : '',
    report.nextActionPlan?.length ? `下一步建议：${report.nextActionPlan.join('；')}` : ''
  ].filter(Boolean).join('\n')
}

function buildExcerpt(content) {
  const text = String(content || '').trim()
  if (!text) return '暂无正文'
  if (text.length <= 1800) return text
  return `${text.slice(0, 900)}\n...\n${text.slice(-700)}`
}

function truncateText(text, limit = 120) {
  const value = String(text || '').replace(/\s+/g, ' ').trim()
  if (value.length <= limit) return value
  return `${value.slice(0, limit)}...`
}
