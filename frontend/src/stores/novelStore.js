import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '@/api/db/client'
import { chatCompletion } from '@/api/ai'
import {
  buildBibleFromSeedPrompt,
  buildBibleFromSeedRepairPrompt,
  buildBibleFromSeedSystemPrompt,
  extractBibleFromText,
  normalizeBiblePayload
} from '@/prompts/bibleFromSeed'
import {
  buildGlobalAuditSystemPrompt,
  buildGlobalAuditPrompt
} from '@/prompts/globalAudit'
import { useProviderStore } from './providerStore'
import { useProjectStore } from './projectStore'

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

function snippet(text) {
  return (text || '')
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, 220)
}

function parseGlobalAuditJson(text) {
  if (!text) return null
  try {
    return JSON.parse(text)
  } catch {
    const match = String(text).match(/\{[\s\S]*\}/)
    if (!match) return null
    try {
      return JSON.parse(match[0])
    } catch {
      return null
    }
  }
}

export const useNovelStore = defineStore('novel', () => {
  const bible = ref(null)
  const outline = ref(null)
  const characters = ref([])
  const plotThreads = ref([])
  const canonFacts = ref([])
  const possibilityCards = ref([])
  const globalAuditReports = ref([])
  const globalAuditing = ref(false)
  const loading = ref(false)
  const generatingBible = ref(false)

  // === 创作圣经 ===
  async function loadBible(projectId) {
    loading.value = true
    try {
      bible.value = await api.bible.get(projectId)
      return bible.value
    } catch (e) {
      console.error('加载创作圣经失败:', e.message)
      throw e
    } finally {
      loading.value = false
    }
  }

  async function saveBible(projectId, data) {
    loading.value = true
    try {
      const result = await api.bible.save(projectId, normalizeBiblePayload(data))
      bible.value = result
      await refreshProject(projectId)
      return result
    } catch (e) {
      console.error('保存创作圣经失败:', e.message)
      throw e
    } finally {
      loading.value = false
    }
  }

  async function deleteBible(projectId) {
    loading.value = true
    try {
      await api.bible.delete(projectId)
      bible.value = null
      await refreshProject(projectId)
    } catch (e) {
      console.error('删除创作圣经失败:', e.message)
      throw e
    } finally {
      loading.value = false
    }
  }

  async function loadGlobalAudits(projectId) {
    loading.value = true
    try {
      globalAuditReports.value = await api.globalAudits.list(projectId)
      return globalAuditReports.value
    } catch (e) {
      console.error('加载全局审稿报告失败:', e.message)
      throw e
    } finally {
      loading.value = false
    }
  }

  async function generateGlobalAudit(project, context) {
    if (!project?.id) throw new Error('项目不存在')
    globalAuditing.value = true
    try {
      const providerStore = useProviderStore()
      await providerStore.ensureProvidersLoaded()
      const bindings = await providerStore.getBindings(project.id)
      const modelId = bindings?.auditModelId || bindings?.summaryModelId || bindings?.writingModelId
      const provider = modelId
        ? providerStore.providers.find(p => p.id === modelId)
        : providerStore.providers[0]
      if (!provider) throw new Error('请先在设置中配置模型')

      const result = await chatCompletion(provider, [
        { role: 'system', content: buildGlobalAuditSystemPrompt() },
        { role: 'user', content: buildGlobalAuditPrompt(context) }
      ], jsonOptions(provider, {
        maxTokens: 4096,
        temperature: 0.25
      }))

      const text = getCompletionText(result)
      const report = parseGlobalAuditJson(text)
      if (!report) {
        throw new Error(`AI 没有返回可解析的全局审稿 JSON${text ? `。返回片段：${snippet(text)}` : ''}`)
      }

      const saved = await api.globalAudits.create(project.id, {
        reportType: 'global',
        title: `${project.title || '项目'} ${context?.auditScopeLabel || '全书'}审稿`,
        report
      })
      globalAuditReports.value.unshift(saved)
      await refreshProject(project.id)
      return saved
    } finally {
      globalAuditing.value = false
    }
  }

  async function deleteGlobalAudit(projectId, reportId) {
    await api.globalAudits.delete(projectId, reportId)
    globalAuditReports.value = globalAuditReports.value.filter(report => report.id !== reportId)
  }

  async function generateBibleFromSeed(projectId, seed, options = {}) {
    if (!seed) throw new Error('请先选择一个创作种子')
    generatingBible.value = true
    try {
      const existingBible = await loadBible(projectId)
      if (existingBible) {
        throw new Error('当前项目已有创作圣经，不能从种子重复生成并覆盖。请在创作圣经页局部编辑。')
      }

      const providerStore = useProviderStore()
      await providerStore.ensureProvidersLoaded()
      const bindings = await providerStore.getBindings(projectId)
      const modelId = bindings?.brainstormModelId || bindings?.writingModelId
      const provider = modelId
        ? providerStore.providers.find(p => p.id === modelId)
        : providerStore.providers[0]

      if (!provider) throw new Error('请先在设置中配置模型')

      const result = await chatCompletion(provider, [
        { role: 'system', content: buildBibleFromSeedSystemPrompt() },
        { role: 'user', content: buildBibleFromSeedPrompt(seed, options) }
      ], jsonOptions(provider, {
        maxTokens: 4096,
        temperature: 0.45
      }))

      const text = getCompletionText(result)
      let bibleData = extractBibleFromText(text)
      let repairText = ''

      if (!bibleData && text.trim()) {
        const repairResult = await chatCompletion(provider, [
          {
            role: 'system',
            content: '你是 JSON 修复器。你只能输出合法 JSON，不要输出解释、Markdown 或额外文字。'
          },
          {
            role: 'user',
            content: buildBibleFromSeedRepairPrompt(text)
          }
        ], jsonOptions(provider, {
          maxTokens: 4096,
          temperature: 0.2
        }))
        repairText = getCompletionText(repairResult)
        bibleData = extractBibleFromText(repairText)
      }

      if (!bibleData) {
        const raw = snippet(repairText) || snippet(text)
        throw new Error(`AI 没有返回可解析的创作圣经 JSON${raw ? `。返回片段：${raw}` : ''}`)
      }

      return await saveBible(projectId, normalizeBiblePayload(bibleData))
    } finally {
      generatingBible.value = false
    }
  }

  // === 滚动大纲 ===
  async function loadOutline(projectId) {
    loading.value = true
    try {
      outline.value = await api.outline.get(projectId)
      return outline.value
    } catch (e) {
      console.error('加载大纲失败:', e.message)
      throw e
    } finally {
      loading.value = false
    }
  }

  async function saveOutline(projectId, data) {
    loading.value = true
    try {
      const result = await api.outline.save(projectId, data)
      outline.value = result
      return result
    } catch (e) {
      console.error('保存大纲失败:', e.message)
      throw e
    } finally {
      loading.value = false
    }
  }

  // === 角色 ===
  async function loadCharacters(projectId) {
    loading.value = true
    try {
      characters.value = await api.characters.list(projectId)
      return characters.value
    } catch (e) {
      console.error('加载角色失败:', e.message)
      throw e
    } finally {
      loading.value = false
    }
  }

  async function saveCharacter(data) {
    try {
      const pid = data.projectId || data.project_id
      if (data.id) {
        const updated = await api.characters.update(pid, data.id, data)
        const idx = characters.value.findIndex(c => c.id === data.id)
        if (idx !== -1) characters.value[idx] = updated
      } else {
        const created = await api.characters.create(pid, data)
        characters.value.push(created)
      }
    } catch (e) {
      console.error('保存角色失败:', e.message)
      throw e
    }
  }

  async function deleteCharacter(id) {
    try {
      const ch = characters.value.find(c => c.id === id)
      if (!ch) return
      const pid = ch.projectId || ch.project_id
      await api.characters.delete(pid, id)
      characters.value = characters.value.filter(c => c.id !== id)
    } catch (e) {
      console.error('删除角色失败:', e.message)
      throw e
    }
  }

  // === 伏笔 ===
  async function loadPlotThreads(projectId) {
    loading.value = true
    try {
      plotThreads.value = await api.plotThreads.list(projectId)
      return plotThreads.value
    } catch (e) {
      console.error('加载伏笔失败:', e.message)
      throw e
    } finally {
      loading.value = false
    }
  }

  async function savePlotThread(data) {
    try {
      const pid = data.projectId || data.project_id
      if (data.id) {
        const updated = await api.plotThreads.update(pid, data.id, data)
        const idx = plotThreads.value.findIndex(t => t.id === data.id)
        if (idx !== -1) plotThreads.value[idx] = updated
      } else {
        const created = await api.plotThreads.create(pid, data)
        plotThreads.value.push(created)
      }
    } catch (e) {
      console.error('保存伏笔失败:', e.message)
      throw e
    }
  }

  async function deletePlotThread(id) {
    try {
      const t = plotThreads.value.find(t => t.id === id)
      if (!t) return
      const pid = t.projectId || t.project_id
      await api.plotThreads.delete(pid, id)
      plotThreads.value = plotThreads.value.filter(t => t.id !== id)
    } catch (e) {
      console.error('删除伏笔失败:', e.message)
      throw e
    }
  }

  // === Canon 事实 ===
  async function loadCanonFacts(projectId) {
    loading.value = true
    try {
      canonFacts.value = await api.canonFacts.list(projectId)
      return canonFacts.value
    } catch (e) {
      console.error('加载Canon事实失败:', e.message)
      throw e
    } finally {
      loading.value = false
    }
  }

  async function saveCanonFact(data) {
    try {
      const pid = data.projectId || data.project_id
      if (data.id) {
        const updated = await api.canonFacts.update(pid, data.id, data)
        const idx = canonFacts.value.findIndex(f => f.id === data.id)
        if (idx !== -1) canonFacts.value[idx] = updated
      } else {
        const created = await api.canonFacts.create(pid, data)
        canonFacts.value.push(created)
      }
    } catch (e) {
      console.error('保存Canon事实失败:', e.message)
      throw e
    }
  }

  async function confirmCanonFact(id) {
    try {
      const fact = canonFacts.value.find(f => f.id === id)
      if (fact) {
        const pid = fact.projectId || fact.project_id
        fact.status = 'accepted'
        await api.canonFacts.update(pid, id, { status: 'accepted' })
      }
    } catch (e) {
      console.error('确认Canon事实失败:', e.message)
      throw e
    }
  }

  async function rejectCanonFact(id) {
    try {
      const fact = canonFacts.value.find(f => f.id === id)
      if (fact) {
        const pid = fact.projectId || fact.project_id
        fact.status = 'rejected'
        await api.canonFacts.update(pid, id, { status: 'rejected' })
      }
    } catch (e) {
      console.error('拒绝Canon事实失败:', e.message)
      throw e
    }
  }

  // === 可能性池 ===
  async function loadPossibilityCards(projectId) {
    loading.value = true
    try {
      possibilityCards.value = await api.possibilityCards.list(projectId)
      return possibilityCards.value
    } catch (e) {
      console.error('加载可能性池失败:', e.message)
      throw e
    } finally {
      loading.value = false
    }
  }

  async function savePossibilityCard(data) {
    try {
      const pid = data.projectId || data.project_id
      const created = await api.possibilityCards.create(pid, data)
      possibilityCards.value.push(created)
    } catch (e) {
      console.error('保存可能性卡片失败:', e.message)
      throw e
    }
  }

  async function deletePossibilityCard(id) {
    try {
      const card = possibilityCards.value.find(c => c.id === id)
      if (!card) return
      const pid = card.projectId || card.project_id
      await api.possibilityCards.delete(pid, id)
      possibilityCards.value = possibilityCards.value.filter(c => c.id !== id)
    } catch (e) {
      console.error('删除可能性卡片失败:', e.message)
      throw e
    }
  }

  return {
    bible,
    outline,
    characters,
    plotThreads,
    canonFacts,
    possibilityCards,
    globalAuditReports,
    loading,
    generatingBible,
    globalAuditing,
    loadBible,
    saveBible,
    deleteBible,
    generateBibleFromSeed,
    loadGlobalAudits,
    generateGlobalAudit,
    deleteGlobalAudit,
    loadOutline,
    saveOutline,
    loadCharacters,
    saveCharacter,
    deleteCharacter,
    loadPlotThreads,
    savePlotThread,
    deletePlotThread,
    loadCanonFacts,
    saveCanonFact,
    confirmCanonFact,
    rejectCanonFact,
    loadPossibilityCards,
    savePossibilityCard,
    deletePossibilityCard
  }
})

async function refreshProject(projectId) {
  try {
    const projectStore = useProjectStore()
    if (projectStore.currentProject?.id === projectId) {
      await projectStore.openProject(projectId)
    }
  } catch {
    // Project metadata refresh should not block the primary action.
  }
}
