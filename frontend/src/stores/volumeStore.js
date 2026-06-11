import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '@/api/db/client'
import { chatCompletion } from '@/api/ai'
import {
  buildVolumePlanPrompt,
  buildVolumePlanRepairPrompt,
  buildVolumePlanSystemPrompt
} from '@/prompts/volumePlan'
import { useProjectStore } from './projectStore'
import { useProviderStore } from './providerStore'
import { useNovelStore } from './novelStore'
import { useSeedStore } from './seedStore'
import { useSettingStore } from './settingStore'

export const VOLUME_STATUS_OPTIONS = [
  { label: '规划中', value: 'planned' },
  { label: '创作中', value: 'active' },
  { label: '已完成', value: 'completed' },
  { label: '暂缓', value: 'paused' }
]

export const useVolumeStore = defineStore('volume', () => {
  const volumes = ref([])
  const loading = ref(false)
  const generating = ref(false)

  async function loadVolumes(projectId) {
    loading.value = true
    try {
      volumes.value = await api.volumes.list(projectId)
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

  async function saveStageSummary(projectId, volumeId, report) {
    const result = await api.volumes.saveSummary(projectId, volumeId, report)
    upsertVolume(result)
    sortVolumes()
    await refreshProject(projectId)
    return result
  }

  async function deleteVolume(projectId, volumeId) {
    await api.volumes.delete(projectId, volumeId)
    volumes.value = volumes.value.filter(v => v.id !== volumeId)
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
      const planned = await requestVolumePlan(provider, {
        project,
        seed,
        bible: novelStore.bible,
        settings: settingStore.entities
      })

      const normalized = normalizeGeneratedVolumes(planned, project)
      if (!normalized.length) {
        throw new Error('AI 没有返回可保存的分卷规划')
      }

      const created = []
      for (const volume of normalized) {
        created.push(await saveVolume(project.id, volume))
      }
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

async function resolveVolumePlanningProvider(projectId) {
  const providerStore = useProviderStore()
  await providerStore.ensureProvidersLoaded()
  const bindings = await providerStore.getBindings(projectId)
  const modelId = bindings?.outlineModelId || bindings?.brainstormModelId || bindings?.writingModelId
  const provider = modelId
    ? providerStore.providers.find(item => item.id === modelId)
    : providerStore.providers[0]
  if (!provider) throw new Error('请先在设置中配置大模型')
  return provider
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

async function requestVolumePlan(provider, context) {
  const messages = [
    { role: 'system', content: buildVolumePlanSystemPrompt() },
    { role: 'user', content: buildVolumePlanPrompt(context) }
  ]
  const result = await chatCompletion(provider, messages, jsonOptions(provider, { maxTokens: 6000, temperature: 0.45 }))
  const text = getCompletionText(result)
  let parsed = parseVolumePlan(text)

  if (!parsed?.volumes?.length && text.trim()) {
    const repair = await chatCompletion(provider, [
      { role: 'system', content: '你是 JSON 修复器。只输出合法 JSON，不要解释，不要 Markdown。' },
      { role: 'user', content: buildVolumePlanRepairPrompt(text, context.project) }
    ], jsonOptions(provider, { maxTokens: 5000, temperature: 0 }))
    parsed = parseVolumePlan(getCompletionText(repair))
  }

  if (!parsed?.volumes?.length) {
    throw new Error(`AI 没有返回可解析的分卷规划 JSON。返回片段：${String(text || '').slice(0, 300)}`)
  }
  return parsed.volumes
}

function parseVolumePlan(text) {
  const cleaned = String(text || '')
    .replace(/^\uFEFF/, '')
    .replace(/^```(?:json)?/i, '')
    .replace(/```$/i, '')
    .trim()
  const candidates = [
    cleaned,
    cleaned.match(/\{[\s\S]*\}/)?.[0],
    cleaned.match(/\[[\s\S]*\]/)?.[0]
  ].filter(Boolean)

  for (const candidate of candidates) {
    try {
      const parsed = JSON.parse(candidate)
      if (Array.isArray(parsed)) return { volumes: parsed }
      if (Array.isArray(parsed?.volumes)) return parsed
    } catch {}
  }
  return null
}

function normalizeGeneratedVolumes(items, project) {
  const targetChapters = Number(project?.targetChapters || 100)
  const targetWords = Number(project?.targetWords || 100000)
  const count = Math.max(1, items.length)
  const ranges = buildVolumeRanges(targetChapters, targetWords, count)

  return items
    .map((item, index) => {
      const range = ranges[index]
      return normalizeVolume({
        volumeNum: Number(item.volumeNum || item.volume_num || index + 1),
        title: item.title || `第 ${index + 1} 卷`,
        startChapter: range.startChapter,
        endChapter: range.endChapter,
        targetWords: range.targetWords,
        coreGoal: item.coreGoal || item.core_goal || '',
        mainConflict: item.mainConflict || item.main_conflict || '',
        keyCharacters: item.keyCharacters || item.key_characters || [],
        summary: item.summary || '',
        foreshadowingPlan: item.foreshadowingPlan || item.foreshadowing_plan || item.foreshadowing || [],
        unresolvedItems: item.unresolvedItems || item.unresolved_items || item.deferredItems || [],
        handoffPoint: item.handoffPoint || item.handoff_point || item.handoff || '',
        status: index === 0 ? 'active' : 'planned'
      })
    })
    .filter(volume =>
      volume.title &&
      volume.startChapter <= volume.endChapter &&
      (volume.coreGoal || volume.mainConflict || volume.summary)
    )
    .sort((a, b) => a.volumeNum - b.volumeNum)
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
    status: data.status || 'planned'
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
