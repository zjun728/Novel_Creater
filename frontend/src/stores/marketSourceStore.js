import { defineStore } from 'pinia'
import { ref } from 'vue'

import { api } from '../api/db/client.js'
import { createLatestRequestGuard } from '../utils/latestRequest.js'

const EMPTY_ANALYSIS = Object.freeze({
  status: 'idle',
  result: null,
  publicErrorCode: null,
})

export const useMarketSourceStore = defineStore('market-sources', () => {
  const sources = ref([])
  const snapshotHistory = ref({})
  const snapshotDetails = ref({})
  const loading = ref(false)
  const sourceOperationId = ref('')
  const scheduleConflictSourceId = ref('')
  const analysisState = ref({ ...EMPTY_ANALYSIS })
  const analysisProjectId = ref('')
  const analysisLoading = ref(false)
  const error = ref(null)
  const loadGuard = createLatestRequestGuard()
  const analysisGuard = createLatestRequestGuard()

  function activateProject(projectId) {
    const projectKey = String(projectId)
    if (analysisProjectId.value === projectKey) return projectKey
    analysisProjectId.value = projectKey
    analysisGuard.invalidate()
    analysisState.value = { ...EMPTY_ANALYSIS }
    analysisLoading.value = false
    return projectKey
  }

  function upsertSource(source) {
    const index = sources.value.findIndex(item => item.id === source.id)
    if (index < 0) sources.value = [...sources.value, source]
    else {
      sources.value = sources.value.map((item, position) => (
        position === index ? { ...item, ...source } : item
      ))
    }
  }

  function addSnapshot(sourceId, snapshot) {
    const history = snapshotHistory.value[sourceId] || []
    snapshotHistory.value = {
      ...snapshotHistory.value,
      [sourceId]: [
        snapshot,
        ...history.filter(item => item.id !== snapshot.id),
      ],
    }
    snapshotDetails.value = {
      ...snapshotDetails.value,
      [snapshot.id]: snapshot,
    }
  }

  async function loadSource(sourceId) {
    const source = await api.marketSources.get(sourceId)
    upsertSource(source)
    return source
  }

  async function loadSources() {
    const generation = loadGuard.begin()
    loading.value = true
    error.value = null
    try {
      const rows = await api.marketSources.list()
      const inventory = Array.isArray(rows) ? rows : []
      const histories = await Promise.all(inventory.map(async source => [
        source.id,
        await api.marketSources.snapshots(source.id),
      ]))
      if (loadGuard.isCurrent(generation)) {
        sources.value = inventory
        snapshotHistory.value = Object.fromEntries(histories.map(([id, items]) => [
          id,
          Array.isArray(items) ? items : [],
        ]))
      }
      return inventory
    } catch (failure) {
      if (loadGuard.isCurrent(generation)) error.value = failure
      throw failure
    } finally {
      if (loadGuard.isCurrent(generation)) loading.value = false
    }
  }

  async function loadSnapshotDetail(sourceId, snapshotId) {
    const detail = await api.marketSources.snapshot(sourceId, snapshotId)
    snapshotDetails.value = {
      ...snapshotDetails.value,
      [snapshotId]: detail,
    }
    return detail
  }

  async function sourceOperation(sourceId, operation) {
    sourceOperationId.value = sourceId
    error.value = null
    try {
      const snapshot = await operation()
      addSnapshot(sourceId, snapshot)
      try {
        await loadSource(sourceId)
      } catch {
        // The immutable snapshot remains usable when the status reread fails.
      }
      return snapshot
    } catch (failure) {
      error.value = failure
      try {
        await loadSource(sourceId)
      } catch {
        // Preserve and rethrow the original operation failure.
      }
      throw failure
    } finally {
      if (sourceOperationId.value === sourceId) sourceOperationId.value = ''
    }
  }

  function importManualSnapshot(sourceId, snapshot, idempotencyKey) {
    return sourceOperation(
      sourceId,
      () => api.marketSources.manualImport(sourceId, {
        snapshot,
        idempotencyKey,
      }),
    )
  }

  function refreshSource(sourceId, idempotencyKey) {
    return sourceOperation(
      sourceId,
      () => api.marketSources.refresh(sourceId, idempotencyKey),
    )
  }

  function scheduleExplanation(sourceId) {
    const source = sources.value.find(item => item.id === sourceId)
    if (!source) return '来源状态尚未加载。'
    if (source.policyStatus === 'manual_only') {
      return '该来源仅支持手动导入，当前没有可验证的自动刷新依据。'
    }
    if (source.policyStatus === 'disabled') {
      return '该来源已停用，不能安排自动刷新。'
    }
    if (!source.automaticRefreshAllowed) {
      return '自动刷新尚不可用，请使用手动导入。'
    }
    return ''
  }

  async function updateSchedule(sourceId, data) {
    const source = sources.value.find(item => item.id === sourceId)
    if (data.enabled && (
      !source
      || source.policyStatus !== 'verified_public'
      || source.automaticRefreshAllowed !== true
    )) {
      throw new Error(scheduleExplanation(sourceId))
    }
    sourceOperationId.value = sourceId
    scheduleConflictSourceId.value = ''
    try {
      const schedule = await api.marketSources.schedule(sourceId, data)
      upsertSource({
        id: sourceId,
        scheduleRevision: schedule.revision,
        scheduleEnabled: schedule.enabled,
        scheduleIntervalMinutes: schedule.intervalMinutes,
        scheduleNextRunAt: schedule.nextRunAt,
        policyStatus: schedule.policyStatus,
        scheduleRecoveryReason: schedule.recoveryReason,
      })
      return schedule
    } catch (failure) {
      if (Number(failure?.status) === 409) {
        scheduleConflictSourceId.value = sourceId
        await loadSource(sourceId)
      }
      error.value = failure
      throw failure
    } finally {
      if (sourceOperationId.value === sourceId) sourceOperationId.value = ''
    }
  }

  async function analyze(projectId, data) {
    const projectKey = activateProject(projectId)
    const generation = analysisGuard.begin()
    analysisLoading.value = true
    analysisState.value = { status: 'running', result: null, publicErrorCode: null }
    try {
      const result = await api.marketAnalyses.create(projectId, data)
      if (
        analysisProjectId.value !== projectKey
        || !analysisGuard.isCurrent(generation)
      ) return result
      if (result?.status === 'succeeded' && result.analysis) {
        analysisState.value = {
          status: 'available',
          result,
          publicErrorCode: null,
        }
      } else {
        analysisState.value = {
          status: 'failed',
          result: null,
          publicErrorCode: result?.publicErrorCode || 'MARKET_ANALYSIS_PROVIDER_FAILED',
        }
      }
      return result
    } catch (failure) {
      if (
        analysisProjectId.value !== projectKey
        || !analysisGuard.isCurrent(generation)
      ) throw failure
      const notReady = Number(failure?.status) === 422
        || failure?.code === 'MARKET_ANALYSIS_NOT_READY'
      analysisState.value = {
        status: notReady ? 'not-ready' : 'failed',
        result: null,
        publicErrorCode: notReady
          ? 'MARKET_ANALYSIS_NOT_READY'
          : (failure?.code || 'MARKET_ANALYSIS_PROVIDER_FAILED'),
      }
      throw failure
    } finally {
      if (
        analysisProjectId.value === projectKey
        && analysisGuard.isCurrent(generation)
      ) analysisLoading.value = false
    }
  }

  function sourceState(sourceId) {
    const source = sources.value.find(item => item.id === sourceId)
    if (!source) return { freshness: 'unavailable', source: null, snapshots: [] }
    let freshness = 'not-captured'
    if (source.lastSucceededAt && source.publicErrorCode) {
      freshness = 'available-with-later-failure'
    } else if (source.lastSucceededAt) {
      freshness = 'available'
    } else if (source.publicErrorCode) {
      freshness = 'failed'
    }
    return {
      freshness,
      source,
      snapshots: snapshotHistory.value[sourceId] || [],
    }
  }

  return {
    sources,
    snapshotHistory,
    snapshotDetails,
    loading,
    sourceOperationId,
    scheduleConflictSourceId,
    analysisState,
    analysisProjectId,
    analysisLoading,
    error,
    activateProject,
    loadSources,
    loadSource,
    loadSnapshotDetail,
    importManualSnapshot,
    refreshSource,
    updateSchedule,
    scheduleExplanation,
    analyze,
    sourceState,
  }
})
