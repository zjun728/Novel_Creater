import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { api } from '../api/db/client.js'
import { createLatestRequestGuard } from '../utils/latestRequest.js'

const EMPTY_READINESS = Object.freeze({
  seedReady: false,
  contractReady: false,
  reasons: [],
})

function normalizedReadiness(result = {}) {
  return {
    seedReady: result.seedReady === true,
    contractReady: result.contractReady === true,
    reasons: Array.isArray(result.reasons) ? [...result.reasons] : [],
  }
}

function selectedRows(rows, activeSelection) {
  const selectedId = activeSelection?.seedId ?? null
  return (Array.isArray(rows) ? rows : []).map(seed => ({
    ...seed,
    isSelected: selectedId != null && seed.id === selectedId,
    selectionRevision: Number(activeSelection?.selectionRevision ?? seed.selectionRevision ?? 0),
  }))
}

export const useSeedStore = defineStore('seed', () => {
  const seeds = ref([])
  const activeSelection = ref(null)
  const readiness = ref({ ...EMPTY_READINESS })
  const loading = ref(false)
  const refreshing = ref(false)
  const mutationBusy = ref(false)
  const inspirationBusy = ref(false)
  const error = ref(null)
  const loadGuard = createLatestRequestGuard()
  const writeGuard = createLatestRequestGuard()
  const inspirationGuard = createLatestRequestGuard()
  let activeProjectId = ''
  const mutationTokens = new Set()

  const selectedSeed = computed(() => activeSelection.value?.seed ?? null)
  const selectionRevision = computed(() => Number(
    activeSelection.value?.selectionRevision ?? 0,
  ))
  const nextAction = computed(() => (
    activeSelection.value
      ? { key: 'continue-contract', label: '继续创作契约' }
      : { key: 'select-seed', label: '选定一个创作种子' }
  ))

  function activate(projectId) {
    const key = String(projectId)
    if (activeProjectId === key) return key
    activeProjectId = key
    loadGuard.invalidate()
    writeGuard.invalidate()
    inspirationGuard.invalidate()
    seeds.value = []
    activeSelection.value = null
    readiness.value = { ...EMPTY_READINESS }
    loading.value = false
    refreshing.value = false
    mutationTokens.clear()
    mutationBusy.value = false
    inspirationBusy.value = false
    error.value = null
    return key
  }

  function beginMutation(projectId) {
    const projectKey = activate(projectId)
    loadGuard.invalidate()
    loading.value = false
    refreshing.value = false
    const generation = writeGuard.begin()
    mutationTokens.add(generation)
    mutationBusy.value = true
    error.value = null
    return { projectKey, generation }
  }

  function mutationCurrent(state) {
    return activeProjectId === state.projectKey
      && writeGuard.isCurrent(state.generation)
  }

  function finishMutation(state) {
    if (activeProjectId !== state.projectKey) return
    mutationTokens.delete(state.generation)
    mutationBusy.value = mutationTokens.size > 0
  }

  function upsert(seed) {
    const index = seeds.value.findIndex(item => item.id === seed.id)
    if (index < 0) seeds.value = [...seeds.value, seed]
    else seeds.value = seeds.value.map((item, position) => (
      position === index ? seed : item
    ))
  }

  function applySelection(seed) {
    const revision = Number(seed.selectionRevision || 0)
    activeSelection.value = {
      projectId: seed.projectId,
      selectionRevision: revision,
      seedId: seed.id,
      seedRevisionId: seed.revisionId,
      seedHash: seed.contentHash,
      selectedAt: null,
      updatedAt: null,
      seed: { ...seed, isSelected: true },
    }
    seeds.value = selectedRows(seeds.value, activeSelection.value)
    upsert({ ...seed, isSelected: true, selectionRevision: revision })
    readiness.value = {
      seedReady: false,
      contractReady: false,
      reasons: ['creation_contract_missing'],
    }
  }

  async function refresh(projectId) {
    const projectKey = activate(projectId)
    const generation = loadGuard.begin()
    loading.value = true
    refreshing.value = true
    error.value = null
    try {
      const [rows, selectedResult] = await Promise.all([
        api.seeds.list(projectId),
        api.seeds.selected(projectId),
      ])
      const result = {
        seeds: Array.isArray(rows) ? rows : [],
        activeSelection: selectedResult?.activeSelection ?? null,
        readiness: normalizedReadiness(selectedResult),
      }
      if (activeProjectId === projectKey && loadGuard.isCurrent(generation)) {
        activeSelection.value = result.activeSelection
        seeds.value = selectedRows(result.seeds, result.activeSelection)
        readiness.value = result.readiness
      }
      return result
    } catch (failure) {
      if (activeProjectId === projectKey && loadGuard.isCurrent(generation)) {
        error.value = failure
      }
      throw failure
    } finally {
      if (loadGuard.isCurrent(generation)) {
        loading.value = false
        refreshing.value = false
      }
    }
  }

  async function loadSeeds(projectId) {
    const result = await refresh(projectId)
    return result.seeds
  }

  async function loadSelectedSeed(projectId) {
    await refresh(projectId)
    return {
      activeSelection: activeSelection.value,
      seedReady: readiness.value.seedReady,
      contractReady: readiness.value.contractReady,
      reasons: [...readiness.value.reasons],
    }
  }

  async function mutate(projectId, command, apply) {
    const state = beginMutation(projectId)
    try {
      const result = await command()
      if (mutationCurrent(state)) apply?.(result)
      return result
    } catch (failure) {
      if (mutationCurrent(state)) error.value = failure
      throw failure
    } finally {
      finishMutation(state)
    }
  }

  function createSeed(projectId, payload, options = {}) {
    return mutate(
      projectId,
      () => api.seeds.create(projectId, payload, options),
      created => upsert(created),
    )
  }

  function updateSeed(projectId, seedId, data) {
    return mutate(
      projectId,
      () => api.seeds.update(projectId, seedId, data),
      updated => {
        upsert(updated)
        if (activeSelection.value?.seedId === updated.id) applySelection(updated)
      },
    )
  }

  function selectSeed(projectId, data) {
    return mutate(
      projectId,
      () => api.seeds.select(projectId, data),
      applySelection,
    )
  }

  function archiveSeed(projectId, seedId, data) {
    return mutate(
      projectId,
      () => api.seeds.archive(projectId, seedId, data),
      upsert,
    )
  }

  function restoreSeed(projectId, seedId, data) {
    return mutate(
      projectId,
      () => api.seeds.restore(projectId, seedId, data),
      upsert,
    )
  }

  function permanentlyDeleteSeed(projectId, seedId, data) {
    return mutate(
      projectId,
      () => api.seeds.delete(projectId, seedId, data),
      () => {
        seeds.value = seeds.value.filter(seed => seed.id !== seedId)
      },
    )
  }

  const deleteSeed = permanentlyDeleteSeed

  async function requestInspiration(projectId, data) {
    const projectKey = activate(projectId)
    const generation = inspirationGuard.begin()
    inspirationBusy.value = true
    error.value = null
    try {
      return await api.seeds.inspiration(projectId, data)
    } catch (failure) {
      if (
        activeProjectId === projectKey
        && inspirationGuard.isCurrent(generation)
      ) error.value = failure
      throw failure
    } finally {
      if (
        activeProjectId === projectKey
        && inspirationGuard.isCurrent(generation)
      ) inspirationBusy.value = false
    }
  }

  function invalidateLoadSeeds() {
    loadGuard.invalidate()
    seeds.value = []
    loading.value = false
    refreshing.value = false
  }

  return {
    seeds,
    activeSelection,
    selectedSeed,
    selectionRevision,
    readiness,
    nextAction,
    loading,
    selectedLoading: loading,
    refreshing,
    mutationBusy,
    inspirationBusy,
    error,
    activateProject: activate,
    loadSeeds,
    loadSelectedSeed,
    refresh,
    createSeed,
    updateSeed,
    selectSeed,
    archiveSeed,
    restoreSeed,
    permanentlyDeleteSeed,
    deleteSeed,
    requestInspiration,
    invalidateLoadSeeds,
  }
})
