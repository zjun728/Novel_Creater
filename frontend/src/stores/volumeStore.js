import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '@/api/db/client'
import { useProjectStore } from './projectStore'

export const VOLUME_STATUS_OPTIONS = [
  { label: '规划中', value: 'planned' },
  { label: '创作中', value: 'active' },
  { label: '已完成', value: 'completed' },
  { label: '暂缓', value: 'paused' }
]

export const useVolumeStore = defineStore('volume', () => {
  const volumes = ref([])
  const loading = ref(false)

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

  async function initializeByProject(project) {
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
        status: index === 0 ? 'active' : 'planned'
      })
      created.push(volume)
    }
    return created
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
    loadVolumes,
    saveVolume,
    saveAudit,
    saveStageSummary,
    deleteVolume,
    initializeByProject
  }
})

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
