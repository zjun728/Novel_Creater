import { defineStore } from 'pinia'
import { computed, ref, shallowRef } from 'vue'

import { api } from '../api/db/client.js'
import { createLatestRequestGuard } from '../utils/latestRequest.js'

function publicError(error) {
  return {
    status: Number(error?.status || 0),
    code: String(error?.code || 'request_failed'),
    message: String(error?.message || '请求失败'),
    correlationId: String(error?.correlationId || ''),
  }
}

export const usePlanningStore = defineStore('planning', () => {
  const projectId = ref('')
  const state = shallowRef(null)
  const error = shallowRef(null)
  const loading = ref(false)
  const creating = ref(false)
  const loadGuard = createLatestRequestGuard()
  const createGuard = createLatestRequestGuard()
  let stateGeneration = 0

  const hasPlanning = computed(() => state.value?.hasPlanning === true)
  const planningReady = computed(() => state.value?.planningReady === true)
  const activeVolume = computed(() => state.value?.activeVolume || null)
  const activeBlock = computed(() => state.value?.activeBlock || null)
  const stages = computed(() => (
    Array.isArray(state.value?.stages) ? [...state.value.stages] : []
  ))
  const sceneTasks = computed(() => (
    Array.isArray(state.value?.sceneTasks) ? [...state.value.sceneTasks] : []
  ))

  function enterProject(nextProjectId) {
    const normalized = String(nextProjectId || '')
    if (!normalized) throw new TypeError('projectId is required')
    if (projectId.value !== normalized) {
      stateGeneration += 1
      loadGuard.invalidate()
      createGuard.invalidate()
      state.value = null
      error.value = null
      loading.value = false
      creating.value = false
      projectId.value = normalized
    }
    return normalized
  }

  function isCurrent(guard, generation, targetProjectId, targetStateGeneration) {
    return projectId.value === targetProjectId
      && guard.isCurrent(generation)
      && stateGeneration === targetStateGeneration
  }

  async function load(nextProjectId) {
    const targetProjectId = enterProject(nextProjectId)
    const generation = loadGuard.begin()
    const targetStateGeneration = ++stateGeneration
    loading.value = true
    try {
      const loaded = await api.planning.get(targetProjectId)
      if (isCurrent(loadGuard, generation, targetProjectId, targetStateGeneration)) {
        state.value = loaded
        error.value = null
      }
      return loaded
    } catch (failure) {
      if (isCurrent(loadGuard, generation, targetProjectId, targetStateGeneration)) {
        error.value = publicError(failure)
      }
      throw failure
    } finally {
      if (projectId.value === targetProjectId && loadGuard.isCurrent(generation)) {
        loading.value = false
      }
    }
  }

  async function createInitial(nextProjectId, command) {
    const targetProjectId = enterProject(nextProjectId)
    const generation = createGuard.begin()
    const targetStateGeneration = ++stateGeneration
    creating.value = true
    try {
      const created = await api.planning.createInitial(targetProjectId, {
        expectedContractRevision: command.expectedContractRevision,
        idempotencyKey: command.idempotencyKey,
      })
      if (isCurrent(createGuard, generation, targetProjectId, targetStateGeneration)) {
        state.value = created
        error.value = null
      }
      return created
    } catch (failure) {
      if (isCurrent(createGuard, generation, targetProjectId, targetStateGeneration)) {
        error.value = publicError(failure)
      }
      throw failure
    } finally {
      if (projectId.value === targetProjectId && createGuard.isCurrent(generation)) {
        creating.value = false
      }
    }
  }

  function invalidate() {
    stateGeneration += 1
    loadGuard.invalidate()
    createGuard.invalidate()
  }

  return {
    projectId,
    state,
    error,
    loading,
    creating,
    hasPlanning,
    planningReady,
    activeVolume,
    activeBlock,
    stages,
    sceneTasks,
    load,
    createInitial,
    invalidate,
  }
})
