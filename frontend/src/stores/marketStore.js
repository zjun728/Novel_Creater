import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '@/api/db/client'
import { chatCompletion } from '@/api/ai'
import { useProviderStore } from './providerStore'
import { useProjectStore } from './projectStore'
import { useNovelStore } from './novelStore'
import { useSeedStore } from './seedStore'
import { buildMarketChatSystemPrompt, extractSeedsFromText } from '@/prompts/market'
import { buildSeedRepairPrompt } from '@/prompts/seed'
import {
  buildMarketDirectionPrompt,
  buildMarketDirectionRepairPrompt,
  buildFallbackMarketDirections,
  extractMarketDirections
} from '@/prompts/marketDirections'

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

function hasSeedIntent(text) {
  return /(?:生成|创建|新增|保存|输出|整理|给我|做|产出).{0,24}(?:种子|创作种子|候选种子|完整种子|seed)/i.test(text)
    || /保存为候选种子|完整\s*JSON\s*数组/i.test(text)
}

export const useMarketStore = defineStore('market', () => {
  const items = ref([])
  const loading = ref(false)
  const scraping = ref(false)
  const chatMessages = ref([])
  const chatLoading = ref(false)
  const directionReports = ref([])
  const currentDirections = ref([])
  const directionsLoading = ref(false)
  const chatDraft = ref('')

  // === Market Items CRUD ===

  async function loadItems(projectId) {
    loading.value = true
    try {
      items.value = await api.market.list(projectId) || []
    } catch (e) {
      items.value = []
    } finally {
      loading.value = false
    }
  }

  async function scrapeMarket(projectId, keywords) {
    scraping.value = true
    try {
      const result = await api.market.scrape({ keywords, projectId })
      if (result?.items?.length) {
        // 重新加载，因为 scrape 返回的 items 可能缺少部分字段
        await loadItems(projectId)
      }
      return result
    } finally {
      scraping.value = false
    }
  }

  // === AI 顾问聊天记录 ===

  async function loadChatMessages(projectId) {
    try {
      const rows = await api.market.chat.list(projectId)
      chatMessages.value = (rows || []).map(row => ({
        id: row.id,
        role: row.role,
        content: row.content || '',
        createdAt: row.createdAt,
        ...(row.metadata || {})
      }))
    } catch (e) {
      console.warn('加载选题顾问聊天记录失败:', e.message)
      chatMessages.value = []
    }
  }

  async function persistChatMessage(projectId, message) {
    const metadata = {}
    if (message.seeds?.length) metadata.seeds = message.seeds
    if (message.seedAction) metadata.seedAction = message.seedAction
    if (message.seedError) metadata.seedError = message.seedError

    const saved = await api.market.chat.create({
      projectId,
      role: message.role,
      content: message.content || '',
      metadata
    })
    Object.assign(message, {
      id: saved?.id || message.id,
      createdAt: saved?.createdAt || message.createdAt
    })
    return saved
  }

  async function createItem(data) {
    try {
      const item = await api.market.create(data)
      items.value.unshift(item)
      return item
    } catch (e) {
      console.error('创建选题项目失败:', e.message)
      throw e
    }
  }

  async function updateItem(id, data) {
    try {
      const result = await api.market.update(id, data)
      const idx = items.value.findIndex(i => i.id === id)
      if (idx !== -1) items.value[idx] = result
      return result
    } catch (e) {
      console.error('更新选题项目失败:', e.message)
      throw e
    }
  }

  async function deleteItem(id) {
    try {
      await api.market.delete(id)
      items.value = items.value.filter(i => i.id !== id)
    } catch (e) {
      console.error('删除选题项目失败:', e.message)
      throw e
    }
  }

  // === AI 分析单本 ===

  async function analyzeItem(itemId) {
    const item = items.value.find(i => i.id === itemId)
    if (!item) return null

    const providerStore = useProviderStore()
    await providerStore.ensureProvidersLoaded()
    const provider = providerStore.providers[0]
    if (!provider) throw new Error('请先在设置中配置模型')

    const messages = [
      {
        role: 'system',
        content: `你是一位网文市场分析师。请分析以下小说在市场中的表现，用200字以内总结：
1. 核心卖点是什么
2. 目标读者画像
3. 为什么能火（或为什么不火）
4. 可以借鉴的创作方向`
      },
      {
        role: 'user',
        content: `书名：${item.title}\n平台：${item.platform}\n分类：${item.category}\n作者：${item.author}\n简介：${item.intro}\n标签：${Array.isArray(item.tags) ? item.tags.join('、') : (item.tags || '')}`
      }
    ]

    try {
      const result = await chatCompletion(provider, messages, { maxTokens: 1024, temperature: 0.7 })

      let text = ''
      if (typeof result === 'string') text = result
      else if (result?.content) text = result.content
      else if (result?.choices?.[0]?.message?.content) text = result.choices[0].message.content

      await updateItem(itemId, { aiSummary: text })
      return text
    } catch (e) {
      console.error('AI分析选题失败:', e.message)
      throw e
    }
  }

  // === AI 聊天 ===

  async function buildChatContext(projectId) {
    const projectStore = useProjectStore()
    const novelStore = useNovelStore()
    const seedStore = useSeedStore()

    try {
      await Promise.all([
        novelStore.loadBible(projectId),
        seedStore.loadSeeds(projectId)
      ])
    } catch (e) {
      console.warn('加载聊天上下文部分失败:', e.message)
    }

    return {
      project: projectStore.currentProject,
      bible: novelStore.bible,
      seeds: seedStore.seeds,
      marketItems: items.value
    }
  }

  async function sendChatMessage(projectId, userMessage) {
    const userEntry = { role: 'user', content: userMessage, seeds: [] }
    chatMessages.value.push(userEntry)
    chatLoading.value = true

    try {
      await persistChatMessage(projectId, userEntry)

      const context = await buildChatContext(projectId)
      const systemPrompt = buildMarketChatSystemPrompt(context)

      const providerStore = useProviderStore()
      await providerStore.ensureProvidersLoaded()
      let bindings
      try {
        bindings = await providerStore.getBindings(projectId)
      } catch {
        bindings = null
      }

      const modelId = bindings?.marketModelId
        || bindings?.brainstormModelId
        || bindings?.writingModelId

      const provider = modelId
        ? providerStore.providers.find(p => p.id === modelId)
        : providerStore.providers[0]

      if (!provider) throw new Error('请先在设置中配置模型')

      const messages = [
        { role: 'system', content: systemPrompt },
        ...chatMessages.value.map(({ role, content }) => ({ role, content }))
      ]

      const result = await chatCompletion(provider, messages, {
        maxTokens: 4096,
        temperature: 0.9
      })

      let text = ''
      if (typeof result === 'string') text = result
      else if (result?.content) text = result.content
      else if (result?.choices?.[0]?.message?.content) text = result.choices[0].message.content

      // 尝试提取种子。明确要求修改当前种子时，应用到已选种子；否则另存为候选种子。
      const requestedSeed = hasSeedIntent(userMessage)
      let seedList = extractSeedsFromText(text)
      let repairText = ''
      if (!seedList.length && requestedSeed && text.trim()) {
        try {
          const repairResult = await chatCompletion(provider, [
            {
              role: 'system',
              content: '你是 JSON 修复器。你只能输出合法 JSON，不要输出解释、Markdown 或额外文字。'
            },
            {
              role: 'user',
              content: buildSeedRepairPrompt(text)
            }
          ], jsonOptions(provider, {
            maxTokens: 4096,
            temperature: 0.2
          }))
          repairText = getCompletionText(repairResult)
          seedList = extractSeedsFromText(repairText)
        } catch (e) {
          repairText = `种子 JSON 修复失败：${e.message}`
        }
      }

      let createdSeeds = []
      let seedAction = ''
      let seedError = ''
      const seedErrors = []
      if (seedList.length) {
        const seedStore = useSeedStore()
        await seedStore.loadSeeds(projectId)
        const selectedSeed = seedStore.seeds.find(seed => seed.status === 'selected')
        const wantsSeedUpdate = /(?:修改|更改|调整|优化|改成|换成|更新|覆盖|应用).{0,24}(?:种子|当前种子|最新种子|这个种子|当前方向|当前设定|这个方向)/.test(userMessage)
          || /(?:种子|当前种子|最新种子).{0,24}(?:修改|更改|调整|优化|改成|换成|更新|覆盖|应用)/.test(userMessage)

        if (wantsSeedUpdate && selectedSeed && seedList.length > 0) {
          const [seedPatch] = seedList
          const nonEmptyPatch = Object.fromEntries(
            Object.entries(seedPatch).filter(([, value]) => value !== '')
          )
          try {
            const updated = await seedStore.updateSeed({
              ...selectedSeed,
              ...nonEmptyPatch,
              id: selectedSeed.id,
              projectId: selectedSeed.projectId || selectedSeed.project_id || projectId,
              status: 'selected',
              source: selectedSeed.source || 'ai'
            })
            if (updated) {
              createdSeeds = [updated]
              seedAction = 'updated'
            }
          } catch (e) {
            seedErrors.push(e.message)
          }
        } else if (wantsSeedUpdate && !selectedSeed) {
          seedError = '当前没有已选中的创作种子，无法更新。请先在“创作种子”页选择一个种子，或使用“生成新种子”。'
        } else {
          for (const seed of seedList) {
            try {
              const created = await seedStore.createSeed(projectId, {
                ...seed,
                source: 'ai'
              })
              createdSeeds.push(created)
            } catch (e) {
              seedErrors.push(e.message)
            }
          }
          if (createdSeeds.length) seedAction = 'created'
        }

        if (seedErrors.length) {
          seedError = createdSeeds.length
            ? `部分种子保存失败：${seedErrors[0]}`
            : `AI 已返回种子 JSON，但保存失败：${seedErrors[0]}`
        }

        if (createdSeeds.length) {
          await seedStore.loadSeeds(projectId)
        }
      } else if (requestedSeed) {
        const raw = snippet(repairText) || snippet(text)
        seedError = `AI 已回复，但没有解析到可保存的种子 JSON${raw ? `。返回片段：${raw}` : ''}`
      }

      const assistantEntry = {
        role: 'assistant',
        content: text,
        seeds: createdSeeds,
        seedAction,
        seedError
      }
      chatMessages.value.push(assistantEntry)
      await persistChatMessage(projectId, assistantEntry)

      return { message: text, seeds: createdSeeds, seedAction, seedError }
    } catch (e) {
      const assistantEntry = {
        role: 'assistant',
        content: `抱歉，请求失败：${e.message}`,
        seeds: []
      }
      chatMessages.value.push(assistantEntry)
      try {
        await persistChatMessage(projectId, assistantEntry)
      } catch (saveError) {
        console.warn('保存失败消息失败:', saveError.message)
      }
      return { message: '', seeds: [] }
    } finally {
      chatLoading.value = false
    }
  }

  async function clearChat(projectId) {
    if (projectId) {
      await api.market.chat.clear(projectId)
    }
    chatMessages.value = []
  }

  function setChatDraft(text) {
    chatDraft.value = text || ''
  }

  function clearChatDraft() {
    chatDraft.value = ''
  }

  // === 市场方向建议 ===

  async function loadDirectionReports(projectId) {
    try {
      const reports = await api.market.directions.list(projectId)
      directionReports.value = reports || []
      currentDirections.value = directionReports.value[0]?.contentJson || []
    } catch (e) {
      console.warn('加载选题方向建议失败:', e.message)
      directionReports.value = []
      currentDirections.value = []
    }
  }

  async function generateMarketDirections(projectId, keywords = '') {
    directionsLoading.value = true
    try {
      const providerStore = useProviderStore()
      await providerStore.ensureProvidersLoaded()
      let bindings
      try {
        bindings = await providerStore.getBindings(projectId)
      } catch {
        bindings = null
      }

      const modelId = bindings?.marketModelId
        || bindings?.brainstormModelId
        || bindings?.writingModelId

      const provider = modelId
        ? providerStore.providers.find(p => p.id === modelId)
        : providerStore.providers[0]

      if (!provider) throw new Error('请先在设置中配置模型')

      const projectStore = useProjectStore()
      const prompt = buildMarketDirectionPrompt({
        project: projectStore.currentProject,
        keywords,
        items: items.value
      })

      const result = await chatCompletion(provider, [
        { role: 'system', content: '你是资深网文选题策划编辑，只输出用户要求的 JSON。' },
        { role: 'user', content: prompt }
      ], jsonOptions(provider, {
        maxTokens: 4096,
        temperature: 0.75
      }))

      const text = getCompletionText(result)
      let directions = extractMarketDirections(text)
      let repairText = ''
      if (!directions.length && text.trim()) {
        const repairResult = await chatCompletion(provider, [
          {
            role: 'system',
            content: '你是 JSON 修复器。你只能输出合法 JSON，不要输出解释、Markdown 或额外文字。'
          },
          {
            role: 'user',
            content: buildMarketDirectionRepairPrompt(text)
          }
        ], jsonOptions(provider, {
          maxTokens: 4096,
          temperature: 0.2
        }))
        repairText = getCompletionText(repairResult)
        directions = extractMarketDirections(repairText)
      }
      if (!directions.length) {
        const raw = snippet(repairText) || snippet(text)
        directions = buildFallbackMarketDirections({
          project: projectStore.currentProject,
          keywords,
          items: items.value
        })
        if (!directions.length) {
          throw new Error(`AI 没有返回可解析的方向建议 JSON${raw ? `。返回片段：${raw}` : ''}`)
        }
        console.warn(`AI 方向建议解析失败，已使用本地保守方向。${raw ? `返回片段：${raw}` : ''}`)
      }

      currentDirections.value = directions
      const saved = await api.market.directions.create({
        projectId,
        keywords,
        contentJson: directions
      })
      if (saved) {
        directionReports.value = [saved, ...directionReports.value].slice(0, 5)
      }
      return directions
    } finally {
      directionsLoading.value = false
    }
  }

  return {
    items,
    loading,
    scraping,
    chatMessages,
    chatLoading,
    directionReports,
    currentDirections,
    directionsLoading,
    chatDraft,
    loadItems,
    scrapeMarket,
    createItem,
    updateItem,
    deleteItem,
    analyzeItem,
    loadChatMessages,
    sendChatMessage,
    clearChat,
    setChatDraft,
    clearChatDraft,
    loadDirectionReports,
    generateMarketDirections
  }
})
