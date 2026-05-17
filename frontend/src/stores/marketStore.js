import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '@/api/db/client'
import { chatCompletion } from '@/api/ai'
import { useProviderStore } from './providerStore'
import { useProjectStore } from './projectStore'
import { useNovelStore } from './novelStore'
import { useSeedStore } from './seedStore'
import { buildMarketChatSystemPrompt, extractSeedsFromText } from '@/prompts/market'

export const useMarketStore = defineStore('market', () => {
  const items = ref([])
  const loading = ref(false)
  const scraping = ref(false)
  const chatMessages = ref([])
  const chatLoading = ref(false)

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
    chatMessages.value.push({ role: 'user', content: userMessage })
    chatLoading.value = true

    try {
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
        ...chatMessages.value
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
      const seedList = extractSeedsFromText(text)
      let createdSeeds = []
      let seedAction = ''
      if (seedList && Array.isArray(seedList)) {
        const seedStore = useSeedStore()
        await seedStore.loadSeeds(projectId)
        const selectedSeed = seedStore.seeds.find(seed => seed.status === 'selected')
        const wantsSeedUpdate = /(?:修改|更改|调整|优化|改成|换成|更新|覆盖|应用).{0,12}(?:种子|当前方向|当前设定|这个方向)/.test(userMessage)

        if (wantsSeedUpdate && selectedSeed && seedList.length > 0) {
          const [seedPatch] = seedList
          const updated = await seedStore.updateSeed({
            ...selectedSeed,
            ...seedPatch,
            id: selectedSeed.id,
            projectId: selectedSeed.projectId || selectedSeed.project_id || projectId,
            status: 'selected',
            source: selectedSeed.source || 'ai'
          })
          if (updated) {
            createdSeeds = [updated]
            seedAction = 'updated'
          }
        } else {
          for (const seed of seedList) {
            try {
              const created = await seedStore.createSeed(projectId, {
                ...seed,
                source: 'ai'
              })
              createdSeeds.push(created)
            } catch {
              // 跳过单个种子创建失败
            }
          }
          if (createdSeeds.length) seedAction = 'created'
        }
      }

      chatMessages.value.push({
        role: 'assistant',
        content: text,
        seeds: createdSeeds,
        seedAction
      })

      return { message: text, seeds: createdSeeds, seedAction }
    } catch (e) {
      chatMessages.value.push({
        role: 'assistant',
        content: `抱歉，请求失败：${e.message}`,
        seeds: []
      })
      return { message: '', seeds: [] }
    } finally {
      chatLoading.value = false
    }
  }

  function clearChat() {
    chatMessages.value = []
  }

  return {
    items,
    loading,
    scraping,
    chatMessages,
    chatLoading,
    loadItems,
    scrapeMarket,
    createItem,
    updateItem,
    deleteItem,
    analyzeItem,
    sendChatMessage,
    clearChat
  }
})
