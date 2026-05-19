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
  buildExtractionPrompt
} from '@/prompts/extraction'
import {
  buildAuditSystemPrompt,
  buildAuditPrompt
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
  buildSettingExtractionPrompt
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
      const result = await chatCompletion(provider, messages, { maxTokens: 2048, temperature: 0.3 })
      const facts = parseAIJson(result)
      const factList = Array.isArray(facts) ? facts : (facts.facts || [facts])
      lastExtractions.value = factList
      return factList
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
      const result = await chatCompletion(provider, messages, { maxTokens: 2048, temperature: 0.3 })
      const data = parseAIJson(result)
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

      const messages = [
        { role: 'system', content: buildSettingExtractionSystemPrompt() },
        { role: 'user', content: buildSettingExtractionPrompt(chapterContent, chapterNum, settingStore.entities) }
      ]
      const result = await chatCompletion(provider, messages, { maxTokens: 3072, temperature: 0.25 })
      const parsed = parseAIJson(result)
      const changes = Array.isArray(parsed) ? parsed : (parsed.changes || parsed.settingChanges || [])
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

  // === 批量处理：定稿后自动执行全部记忆提取 ===
  async function processChapterFinalization(projectId, chapterContent, chapterNum) {
    processing.value = true
    try {
      const results = { summary: null, facts: [], settingChanges: [], audit: null }

      try { results.summary = await generateSummary(projectId, chapterContent, chapterNum) } catch (e) { console.warn('摘要生成失败:', e.message) }
      try { results.facts = await extractFacts(projectId, chapterContent, chapterNum) } catch (e) { console.warn('事实提取失败:', e.message) }
      try { results.settingChanges = await extractSettingChanges(projectId, chapterContent, chapterNum) } catch (e) { console.warn('设定变更提取失败:', e.message) }
      try { results.audit = await auditChapter(projectId, chapterContent, chapterNum) } catch (e) { console.warn('审稿失败:', e.message) }

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
      if (results.settingChanges?.length) {
        for (const change of results.settingChanges) {
          const entityType = change.entityType || 'character'
          const entityName = change.entityName || change.name || ''
          if (!entityName && change.changeType !== 'relationship') continue
          const existingEntity = settingStore.entities.find(e =>
            e.entityType === entityType && e.name === entityName
          )
          await settingStore.saveChangeEvent(projectId, {
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
          })
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
        chapter.summary = results.summary.summary || ''
        await writerStore.updateChapter(chapter)
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
