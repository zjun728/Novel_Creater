import { defineStore } from 'pinia'
import { ref } from 'vue'

import { api } from '../api/db/client.js'
import { createLatestRequestGuard } from '../utils/latestRequest.js'

export const useMarketSourceStore = defineStore('market-sources', () => {
  const sources = ref([])
  const snapshotHistory = ref({})
  const snapshotDetails = ref({})
  const loading = ref(false)
  const sourceOperationId = ref('')
  const error = ref(null)
  const loadGuard = createLatestRequestGuard()

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
    error,
    loadSources,
    loadSource,
    loadSnapshotDetail,
    importManualSnapshot,
    refreshSource,
    sourceState,
  }
})
