import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '../api/db/client.js'
import { createLatestRequestGuard } from '../utils/latestRequest.js'

export const useSeedStore = defineStore('seed', () => {
  const seeds = ref([])
  const selectedSeed = ref(null)
  const readiness = ref({ seedReady: false, contractReady: false, reasons: [] })
  const loading = ref(false)
  const selectedLoading = ref(false)
  const refreshing = ref(false)
  const loadGuard = createLatestRequestGuard()
  const selectedGuard = createLatestRequestGuard()
  const refreshGuard = createLatestRequestGuard()
  const writeGuard = createLatestRequestGuard()
  let activeProjectId = null

  function resetProjectState() {
    seeds.value = []
    selectedSeed.value = null
    readiness.value = { seedReady: false, contractReady: false, reasons: [] }
    loading.value = false
    selectedLoading.value = false
    refreshing.value = false
  }

  function activateProject(projectId) {
    const projectKey = String(projectId)
    if (activeProjectId !== projectKey) {
      activeProjectId = projectKey
      loadGuard.invalidate()
      selectedGuard.invalidate()
      refreshGuard.invalidate()
      writeGuard.invalidate()
      resetProjectState()
    }
    return projectKey
  }

  function beginRead(projectId) {
    const projectKey = activateProject(projectId)
    writeGuard.invalidate()
    return projectKey
  }

  function beginWrite(projectId) {
    const projectKey = activateProject(projectId)
    invalidateReads()
    return { projectKey, requestGeneration: writeGuard.begin() }
  }

  function isCurrentWrite({ projectKey, requestGeneration }) {
    return activeProjectId === projectKey && writeGuard.isCurrent(requestGeneration)
  }

  function cancelRefresh() {
    refreshGuard.invalidate()
    refreshing.value = false
  }

  function invalidateReads() {
    loadGuard.invalidate()
    selectedGuard.invalidate()
    refreshGuard.invalidate()
    loading.value = false
    selectedLoading.value = false
    refreshing.value = false
  }

  function normalizeReadiness(result = {}) {
    return {
      seedReady: result.seedReady === true,
      contractReady: result.contractReady === true,
      reasons: Array.isArray(result.reasons) ? [...result.reasons] : [],
    }
  }

  function upsertSeed(seed) {
    const index = seeds.value.findIndex(item => item.id === seed.id)
    if (index === -1) {
      seeds.value = [...seeds.value, seed]
    } else {
      seeds.value = seeds.value.map((item, itemIndex) => itemIndex === index ? seed : item)
    }
  }

  async function loadSeeds(projectId) {
    const projectKey = beginRead(projectId)
    cancelRefresh()
    const requestGeneration = loadGuard.begin()
    seeds.value = []
    loading.value = true
    try {
      const rows = await api.seeds.list(projectId) || []
      if (
        activeProjectId === projectKey
        && loadGuard.isCurrent(requestGeneration)
      ) seeds.value = rows
      return rows
    } finally {
      if (loadGuard.isCurrent(requestGeneration)) loading.value = false
    }
  }

  async function loadSelectedSeed(projectId) {
    const projectKey = beginRead(projectId)
    cancelRefresh()
    const requestGeneration = selectedGuard.begin()
    selectedSeed.value = null
    readiness.value = { seedReady: false, contractReady: false, reasons: [] }
    selectedLoading.value = true
    try {
      const result = await api.seeds.selected(projectId) || {}
      if (
        activeProjectId === projectKey
        && selectedGuard.isCurrent(requestGeneration)
      ) {
        selectedSeed.value = result.selected || null
        readiness.value = normalizeReadiness(result)
      }
      return result
    } finally {
      if (selectedGuard.isCurrent(requestGeneration)) selectedLoading.value = false
    }
  }

  async function refresh(projectId) {
    const projectKey = beginRead(projectId)
    loadGuard.invalidate()
    selectedGuard.invalidate()
    loading.value = false
    selectedLoading.value = false
    const requestGeneration = refreshGuard.begin()
    refreshing.value = true
    try {
      const [rows, selectedResult] = await Promise.all([
        api.seeds.list(projectId),
        api.seeds.selected(projectId),
      ])
      const result = {
        seeds: rows || [],
        selected: selectedResult?.selected || null,
        readiness: normalizeReadiness(selectedResult),
      }
      if (
        activeProjectId === projectKey
        && refreshGuard.isCurrent(requestGeneration)
      ) {
        seeds.value = result.seeds
        selectedSeed.value = result.selected
        readiness.value = result.readiness
      }
      return result
    } finally {
      if (refreshGuard.isCurrent(requestGeneration)) {
        refreshing.value = false
      }
    }
  }

  async function createSeed(projectId, payload) {
    const writeState = beginWrite(projectId)
    const created = await api.seeds.create(projectId, payload)
    if (isCurrentWrite(writeState)) upsertSeed(created)
    return created
  }

  async function updateSeed(projectId, seedId, data) {
    const writeState = beginWrite(projectId)
    const updated = await api.seeds.update(projectId, seedId, data)
    if (!isCurrentWrite(writeState)) return updated
    upsertSeed(updated)
    if (selectedSeed.value?.id === updated.id) {
      selectedSeed.value = updated
      readiness.value = {
        seedReady: false,
        contractReady: false,
        reasons: ['selected_seed_status_not_reloaded'],
      }
    }
    return updated
  }

  async function deleteSeed(projectId, seedId, data) {
    const writeState = beginWrite(projectId)
    const result = await api.seeds.delete(projectId, seedId, data)
    if (!isCurrentWrite(writeState)) return result
    seeds.value = seeds.value.filter(seed => seed.id !== seedId)
    if (selectedSeed.value?.id === seedId) {
      selectedSeed.value = null
      readiness.value = { seedReady: false, contractReady: false, reasons: [] }
    }
    return result
  }

  async function selectSeed(projectId, data) {
    const writeState = beginWrite(projectId)
    const selected = await api.seeds.select(projectId, data)
    if (!isCurrentWrite(writeState)) return selected
    selectedSeed.value = selected
    seeds.value = seeds.value.map(seed => ({
      ...seed,
      isSelected: seed.id === selected.id,
      selectionRevision: selected.selectionRevision,
    }))
    upsertSeed(selected)
    readiness.value = {
      seedReady: false,
      contractReady: false,
      reasons: ['selected_seed_status_not_reloaded'],
    }
    return selected
  }

  function invalidateLoadSeeds() {
    loadGuard.invalidate()
    seeds.value = []
    loading.value = false
  }

  return {
    seeds,
    selectedSeed,
    readiness,
    loading,
    selectedLoading,
    refreshing,
    loadSeeds,
    loadSelectedSeed,
    refresh,
    createSeed,
    updateSeed,
    deleteSeed,
    selectSeed,
    invalidateLoadSeeds,
  }
})
