import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '@/api/db/client'
import { chatCompletion } from '@/api/ai'
import {
  buildCompactSeedRetryPrompt,
  buildSeedRepairPrompt,
  buildSeedSystemPrompt,
  buildSeedUserPrompt
} from '@/prompts/seed'
import { extractSeedsFromText, isSavableSeed, normalizeSeedPayload } from '@/utils/seedParser'
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
      const payload = normalizeSeedPayload(data)
      if (!isSavableSeed(payload)) {
        throw new Error('种子内容不完整，至少需要题材，并包含一句话、主角、欲望、核心矛盾、开局钩子或情绪价值中的 3 项')
      }
      const shouldAutoSelect = !seeds.value.some(seed => seed.status === 'selected')
      const seed = await api.seeds.create(projectId, payload)
      let saved = seed
      if (shouldAutoSelect) {
        saved = await api.seeds.update(projectId, seed.id, { status: 'selected' })
      }
      seeds.value.push(saved)
      return saved
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
      await refreshProject(pid)
    } catch (e) {
      console.error('删除种子失败:', e.message)
      throw e
    }
  }

  async function clearSeeds(projectId) {
    try {
      await api.seeds.clear(projectId)
      seeds.value = []
      await refreshProject(projectId)
    } catch (e) {
      console.error('清空种子失败:', e.message)
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
      const directSeeds = extractSeedsFromText([
        input?.idea || '',
        input?.genre || '',
        input?.stylePreference || '',
        input?.forbidden || ''
      ].filter(Boolean).join('\n\n'))
      if (directSeeds.length) {
        const created = []
        for (const item of directSeeds) {
          const seed = await createSeed(projectId, { ...item, source: 'user' })
          created.push(seed)
        }
        return created
      }

      const providerStore = useProviderStore()
      const provider = await providerStore.resolveTaskProvider({
        projectId,
        bindingKeys: ['brainstormModelId', 'writingModelId'],
        taskName: 'seed_generation'
      })

      const messages = [
        { role: 'system', content: buildSeedSystemPrompt() },
        { role: 'user', content: buildSeedUserPrompt(input) }
      ]

      const result = await chatCompletion(provider, messages, jsonOptions(provider, { maxTokens: 6000, temperature: 0.85 }))
      const text = getCompletionText(result)

      let seedList = extractSeedsFromText(text)
      let repairText = ''
      let compactText = ''
      if (!seedList.length && text.trim()) {
        const repairResult = await chatCompletion(provider, [
          {
            role: 'system',
            content: '你是 JSON 修复器。你只能输出合法 JSON，不要输出解释、Markdown 或额外文字。'
          },
          {
            role: 'user',
            content: buildSeedRepairPrompt(text)
          }
        ], jsonOptions(provider, { maxTokens: 6000, temperature: 0.2 }))
        repairText = getCompletionText(repairResult)
        seedList = extractSeedsFromText(repairText)
      }

      if (!seedList.length) {
        const compactResult = await chatCompletion(provider, [
          {
            role: 'system',
            content: '你是小说种子结构化助手。你只能输出合法 JSON，不要输出解释、Markdown 或额外文字。'
          },
          {
            role: 'user',
            content: buildCompactSeedRetryPrompt({
              input,
              rawText: [text, repairText].filter(Boolean).join('\n\n')
            })
          }
        ], jsonOptions(provider, { maxTokens: 6000, temperature: 0.35 }))
        compactText = getCompletionText(compactResult)
        seedList = extractSeedsFromText(compactText)
      }

      if (!seedList.length) {
        const raw = snippet(compactText) || snippet(repairText) || snippet(text)
        throw new Error(`AI 返回格式不正确：没有解析到可保存的种子 JSON${raw ? `。返回片段：${raw}` : ''}`)
      }

      const created = []
      for (const item of seedList) {
        const seed = await createSeed(projectId, { ...item, source: 'ai' })
        created.push(seed)
      }
      if (!created.length) throw new Error('AI 返回了种子，但保存失败')
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
    clearSeeds,
    selectSeed,
    generateSeeds
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
