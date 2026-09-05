import { defineStore } from 'pinia'
import { ref } from 'vue'

import { api } from '../api/db/client.js'
import { marketSnapshotMatchesSource } from '../application/market/marketContracts.js'
import { createLatestRequestGuard } from '../utils/latestRequest.js'

export const useMarketSourceStore = defineStore('market-sources', () => {
  const sources = ref([])
  const snapshotHistory = ref({})
  const snapshotDetails = ref({})
  const snapshotDetailFailures = ref({})
  const loading = ref(false)
  const sourceOperationTokens = ref({})
  const error = ref(null)
  const loadGuard = createLatestRequestGuard()
  const sourceGuards = new Map()
  const detailGuards = new Map()
  const historyGuards = new Map()
  const mutationEpochs = new Map()
  const sourceOperationGenerations = new Map()
  const sourceKey = (sourceId, snapshotId) => JSON.stringify([sourceId, snapshotId])
  const bumpMutation = sourceId => mutationEpochs.set(sourceId, (mutationEpochs.get(sourceId) || 0) + 1)

  function trusted(value) {
    if (!value || typeof value !== 'object' || !Object.isFrozen(value)) {
      throw new TypeError('Market API client must return a frozen DTO')
    }
    return value
  }

  function upsertSource(source) {
    trusted(source)
    const index = sources.value.findIndex(item => item.id === source.id)
    if (index < 0) sources.value = [...sources.value, source]
    else {
      sources.value = sources.value.map((item, position) => (
        position === index ? source : item
      ))
    }
  }

  function addSnapshot(sourceId, snapshot) {
    const parsed = trusted(snapshot)
    if (parsed.sourceId !== sourceId) throw new TypeError('Market snapshot source mismatch')
    snapshotDetails.value = {
      ...snapshotDetails.value,
      [sourceKey(sourceId, parsed.id)]: parsed,
    }
    const { entries, ...summary } = parsed
    const fallback = Object.freeze(summary)
    const prior = snapshotHistory.value[sourceId] || []
    snapshotHistory.value = {
      ...snapshotHistory.value,
      [sourceId]: Object.freeze([
        fallback,
        ...prior.filter(item => item.id !== parsed.id),
      ]),
    }
  }

  function reconcileSnapshotSuccess(sourceId, snapshot) {
    const source = sources.value.find(item => item.id === sourceId)
    if (!source) return
    upsertSource(Object.freeze({
      ...source,
      refreshStatus: 'idle',
      lastSucceededAt: snapshot.capturedAt,
      lastSnapshotId: snapshot.id,
      publicErrorCode: null,
    }))
  }

  function beginSourceOperation(sourceId) {
    const generation = (sourceOperationGenerations.get(sourceId) || 0) + 1
    sourceOperationGenerations.set(sourceId, generation)
    sourceOperationTokens.value = {
      ...sourceOperationTokens.value,
      [sourceId]: generation,
    }
    return generation
  }

  function isCurrentSourceOperation(sourceId, generation) {
    return sourceOperationGenerations.get(sourceId) === generation
  }

  function finishSourceOperation(sourceId, generation) {
    if (!isCurrentSourceOperation(sourceId, generation)) return
    const { [sourceId]: ignored, ...remaining } = sourceOperationTokens.value
    sourceOperationTokens.value = remaining
  }

  function isSourceBusy(sourceId) {
    return Object.hasOwn(sourceOperationTokens.value, sourceId)
  }

  async function readSource(sourceId, canCommit) {
    bumpMutation(sourceId)
    const guard = sourceGuards.get(sourceId) || createLatestRequestGuard()
    sourceGuards.set(sourceId, guard)
    const generation = guard.begin()
    const source = trusted(await api.marketSources.get(sourceId))
    if (source.id !== sourceId) throw new TypeError('Market source identity mismatch')
    if (!guard.isCurrent(generation) || !canCommit()) return source
    upsertSource(source)
    return source
  }

  function loadSource(sourceId) {
    return readSource(sourceId, () => true)
  }

  async function loadHistory(sourceId, canCommit = () => true) {
    bumpMutation(sourceId)
    const guard = historyGuards.get(sourceId) || createLatestRequestGuard()
    historyGuards.set(sourceId, guard)
    const generation = guard.begin()
    const history = await api.marketSources.snapshots(sourceId)
    if (!Array.isArray(history) || !Object.isFrozen(history)) throw new TypeError('Market API client must return a frozen DTO')
    history.forEach(item => { trusted(item); if (item.sourceId !== sourceId) throw new TypeError('Market snapshot source mismatch') })
    if (guard.isCurrent(generation) && canCommit()) {
      snapshotHistory.value = { ...snapshotHistory.value, [sourceId]: history }
    }
    return history
  }

  async function loadSources() {
    const generation = loadGuard.begin()
    const startEpochs = new Map(mutationEpochs)
    loading.value = true
    error.value = null
    try {
      const inventory = await api.marketSources.list()
      if (!Array.isArray(inventory) || !Object.isFrozen(inventory)) throw new TypeError('Market API client must return a frozen DTO')
      inventory.forEach(trusted)
      const histories = await Promise.all(inventory.map(async source => [
        source.id,
        await api.marketSources.snapshots(source.id),
      ]))
      for (const [sourceId, history] of histories) {
        if (!Array.isArray(history) || !Object.isFrozen(history)) throw new TypeError('Market API client must return a frozen DTO')
        history.forEach(item => { trusted(item); if (item.sourceId !== sourceId) throw new TypeError('Market snapshot source mismatch') })
      }
      if (loadGuard.isCurrent(generation)) {
        // Atomic newest-bulk commit: stale reads never touch per-source guards.
        for (const source of inventory) {
          if ((mutationEpochs.get(source.id) || 0) !== (startEpochs.get(source.id) || 0)) {
            continue
          }
          const sourceGuard = sourceGuards.get(source.id) || createLatestRequestGuard()
          sourceGuards.set(source.id, sourceGuard)
          sourceGuard.begin()
          const historyGuard = historyGuards.get(source.id) || createLatestRequestGuard()
          historyGuards.set(source.id, historyGuard)
          historyGuard.begin()
        }
        const existing = new Map(sources.value.map(source => [source.id, source]))
        sources.value = inventory.map(source => (
          (mutationEpochs.get(source.id) || 0) === (startEpochs.get(source.id) || 0)
            ? source : (existing.get(source.id) || source)
        ))
        snapshotHistory.value = histories.reduce((next, [sourceId, history]) => (
          (mutationEpochs.get(sourceId) || 0) === (startEpochs.get(sourceId) || 0)
            ? { ...next, [sourceId]: history } : next
        ), snapshotHistory.value)
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
    const key = sourceKey(sourceId, snapshotId)
    const identityGuard = detailGuards.get(key) || createLatestRequestGuard()
    detailGuards.set(key, identityGuard)
    const generation = identityGuard.begin()
    try {
      const detail = trusted(await api.marketSources.snapshot(sourceId, snapshotId))
      if (detail.sourceId !== sourceId || detail.id !== snapshotId) {
        throw new TypeError('Market snapshot identity mismatch')
      }
      if (identityGuard.isCurrent(generation)) {
        snapshotDetails.value = {
          ...snapshotDetails.value,
          [key]: detail,
        }
        const { [key]: ignored, ...remainingFailures } = snapshotDetailFailures.value
        snapshotDetailFailures.value = remainingFailures
      }
      return detail
    } catch (failure) {
      if (identityGuard.isCurrent(generation)) {
        snapshotDetailFailures.value = {
          ...snapshotDetailFailures.value,
          [key]: failure,
        }
      }
      throw failure
    }
  }

  async function sourceOperation(sourceId, operation) {
    bumpMutation(sourceId)
    const generation = beginSourceOperation(sourceId)
    const isCurrent = () => isCurrentSourceOperation(sourceId, generation)
    error.value = null
    try {
      const snapshot = trusted(await operation())
      if (!isCurrent()) return snapshot
      addSnapshot(sourceId, snapshot)
      reconcileSnapshotSuccess(sourceId, snapshot)
      try {
        await loadHistory(sourceId, isCurrent)
      } catch {
        // Snapshot detail remains authoritative if history reread fails.
      }
      if (!isCurrent()) return snapshot
      try {
        await readSource(sourceId, isCurrent)
      } catch {
        // The immutable snapshot remains usable when the status reread fails.
      }
      return snapshot
    } catch (failure) {
      if (isCurrent()) {
        error.value = failure
        try {
          await readSource(sourceId, isCurrent)
        } catch {
          // Preserve and rethrow the original operation failure.
        }
      }
      throw failure
    } finally {
      finishSourceOperation(sourceId, generation)
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
    const snapshots = (snapshotHistory.value[sourceId] || [])
      .filter(snapshot => marketSnapshotMatchesSource(snapshot, source))
    let freshness = 'not-captured'
    if (snapshots.length && source.publicErrorCode) {
      freshness = 'available-with-later-failure'
    } else if (snapshots.length) {
      freshness = 'available'
    } else if (source.publicErrorCode) {
      freshness = 'failed'
    }
    return {
      freshness,
      source,
      snapshots,
    }
  }

  return {
    sources,
    snapshotHistory,
    snapshotDetails,
    snapshotDetailFailures,
    loading,
    error,
    loadSources,
    loadSource,
    loadSnapshotDetail,
    importManualSnapshot,
    refreshSource,
    isSourceBusy,
    sourceState,
  }
})
