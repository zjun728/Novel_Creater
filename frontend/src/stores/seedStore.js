import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '@/api/db/client'
import { chatCompletion } from '@/api/ai'
import { buildSeedSystemPrompt, buildSeedUserPrompt } from '@/prompts/seed'
import { useProviderStore } from './providerStore'

export const useSeedStore = defineStore('seed', () => {
  const seeds = ref([])
  const loading = ref(false)
  const generating = ref(false)

  async function loadSeeds(projectId) {
    loading.value = true
    try {
      seeds.value = await api.seeds.list(projectId)
    } catch (e) {
      console.error('加载种子列表失败:', e.message)
      throw e
    } finally {
      loading.value = false
    }
  }

  async function createSeed(projectId, data) {
    try {
      const seed = await api.seeds.create(projectId, data)
      seeds.value.push(seed)
      return seed
    } catch (e) {
      console.error('创建种子失败:', e.message)
      throw e
    }
  }

  async function updateSeed(seed) {
    try {
      const pid = seed.projectId || seed.project_id
      const updated = await api.seeds.update(pid, seed.id, seed)
      const idx = seeds.value.findIndex(s => s.id === seed.id)
      if (idx !== -1) seeds.value[idx] = updated
      return updated
    } catch (e) {
      console.error('更新种子失败:', e.message)
      throw e
    }
  }

  async function deleteSeed(id) {
    try {
      const seed = seeds.value.find(s => s.id === id)
      if (!seed) return
      const pid = seed.projectId || seed.project_id
      await api.seeds.delete(pid, id)
      seeds.value = seeds.value.filter(s => s.id !== id)
    } catch (e) {
      console.error('删除种子失败:', e.message)
      throw e
    }
  }

  async function selectSeed(seed) {
    try {
      const pid = seed.projectId || seed.project_id
      seed.status = 'selected'
      await api.seeds.update(pid, seed.id, { status: 'selected' })
      for (const s of seeds.value) {
        if (s.id !== seed.id && s.status === 'selected') {
          s.status = 'archived'
          await api.seeds.update(pid, s.id, { status: 'archived' })
        }
      }
      const idx = seeds.value.findIndex(s => s.id === seed.id)
      if (idx !== -1) seeds.value[idx] = seed
    } catch (e) {
      console.error('选择种子失败:', e.message)
      throw e
    }
  }

  async function generateSeeds(projectId, input) {
    generating.value = true
    try {
      const providerStore = useProviderStore()
      await providerStore.ensureProvidersLoaded()
      const bindings = await providerStore.getBindings(projectId)
      const modelId = bindings?.brainstormModelId || bindings?.writingModelId
      const provider = providerStore.providers.find(p => p.id === modelId) || providerStore.providers[0]
      if (!provider) throw new Error('请先在设置中配置模型')

      const messages = [
        { role: 'system', content: buildSeedSystemPrompt() },
        { role: 'user', content: buildSeedUserPrompt(input) }
      ]

      const result = await chatCompletion(provider, messages, { maxTokens: 4096, temperature: 0.9 })
      let text = ''
      if (typeof result === 'string') text = result
      else if (result?.content) text = result.content
      else if (result?.choices?.[0]?.message?.content) text = result.choices[0].message.content

      const jsonMatch = text.match(/\[[\s\S]*\]/)
      if (!jsonMatch) throw new Error('AI 返回格式不正确')

      const seedList = JSON.parse(jsonMatch[0])
      const created = []
      for (const item of seedList) {
        const seed = await createSeed(projectId, { ...item, source: 'ai' })
        created.push(seed)
      }
      return created
    } catch (e) {
      console.error('生成种子失败:', e.message)
      throw e
    } finally {
      generating.value = false
    }
  }

  return {
    seeds,
    loading,
    generating,
    loadSeeds,
    createSeed,
    updateSeed,
    deleteSeed,
    selectSeed,
    generateSeeds
  }
})
