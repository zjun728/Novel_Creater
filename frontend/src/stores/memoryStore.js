import { defineStore } from 'pinia'
import { ref } from 'vue'
import { chatCompletion } from '@/api/ai'
import { useProviderStore } from './providerStore'
import { useNovelStore } from './novelStore'
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

export const useMemoryStore = defineStore('memory', () => {
  const processing = ref(false)
  const lastSummary = ref(null)
  const lastExtractions = ref([])
  const lastAuditResult = ref(null)
  const lastStyleAnalysis = ref(null)
  const lastPacingAnalysis = ref(null)
  const styleAnalyzing = ref(false)
  const pacingAnalyzing = ref(false)

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

  async function getProvider(projectId) {
    const providerStore = useProviderStore()
    await providerStore.ensureProvidersLoaded()
    const bindings = await providerStore.getBindings(projectId)
    const modelId = bindings?.summaryModelId || bindings?.writingModelId
    const provider = providerStore.providers.find(p => p.id === modelId) || providerStore.providers[0]
    if (!provider) throw new Error('请先在设置中配置模型')
    return provider
  }

  // === 章节摘要生成 ===
  async function generateSummary(projectId, chapterContent, chapterNum) {
    try {
      const provider = await getProvider(projectId)
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
      const provider = await getProvider(projectId)
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
      const provider = await getProvider(projectId)
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
    const provider = await getProvider(projectId)
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
    const provider = await getProvider(projectId)
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

  // === 批量处理：定稿后自动执行全部记忆提取 ===
  async function processChapterFinalization(projectId, chapterContent, chapterNum) {
    processing.value = true
    try {
      const results = { summary: null, facts: [], audit: null }

      try { results.summary = await generateSummary(projectId, chapterContent, chapterNum) } catch (e) { console.warn('摘要生成失败:', e.message) }
      try { results.facts = await extractFacts(projectId, chapterContent, chapterNum) } catch (e) { console.warn('事实提取失败:', e.message) }
      try { results.audit = await auditChapter(projectId, chapterContent, chapterNum) } catch (e) { console.warn('审稿失败:', e.message) }

      const novelStore = useNovelStore()
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
    styleAnalyzing,
    pacingAnalyzing,
    generateSummary,
    extractFacts,
    auditChapter,
    analyzeStyle,
    analyzePacing,
    processChapterFinalization
  }
})
