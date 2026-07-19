import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '../api/db/client.js'
import { createLatestRequestGuard } from '../utils/latestRequest.js'

function immutableKey(id, revision, contentHash) {
  if (!id || !Number.isInteger(revision) || revision < 1 || !contentHash) {
    throw new TypeError('Immutable corpus identity requires id, revision, and content hash')
  }
  return `${id}\u0000${revision}\u0000${contentHash}`
}

function assertSourceIdentity(source, id, revision, contentHash) {
  if (
    source?.id !== id
    || source?.revision !== revision
    || source?.contentHash !== contentHash
  ) {
    throw new Error('Immutable corpus source revision changed; reload the source list')
  }
  return source
}

export const useCorpusStore = defineStore('corpus', () => {
  const discovery = ref(null)
  const sources = ref([])
  const fragmentPage = ref(null)
  const importRuns = ref({})
  const sourceDetails = ref({})
  const sourceVersions = ref({})
  const chapterLists = ref({})
  const loadingDiscovery = ref(false)
  const loadingSources = ref(false)
  const loadingFragments = ref(false)

  const discoveryGuard = createLatestRequestGuard()
  const sourceListGuard = createLatestRequestGuard()
  const fragmentGuard = createLatestRequestGuard()
  const importReadGenerations = new Map()

  function beginImportRead(importId) {
    const generation = (importReadGenerations.get(importId) || 0) + 1
    importReadGenerations.set(importId, generation)
    return generation
  }

  function invalidateSourceList() {
    sourceListGuard.invalidate()
    sources.value = []
    loadingSources.value = false
  }

  function commitImportRun(result) {
    if (!result?.importId) return
    importRuns.value[result.importId] = result
    if (result.status === 'succeeded') invalidateSourceList()
  }

  async function discover(params = {}) {
    const generation = discoveryGuard.begin()
    loadingDiscovery.value = true
    try {
      const result = await api.corpus.discovery(params)
      if (discoveryGuard.isCurrent(generation)) discovery.value = result
      return result
    } finally {
      if (discoveryGuard.isCurrent(generation)) loadingDiscovery.value = false
    }
  }

  async function loadSources(params = {}) {
    const generation = sourceListGuard.begin()
    loadingSources.value = true
    try {
      const result = await api.corpus.sources.list(params)
      const rows = result?.items || []
      if (sourceListGuard.isCurrent(generation)) sources.value = rows
      return rows
    } finally {
      if (sourceListGuard.isCurrent(generation)) loadingSources.value = false
    }
  }

  async function importSource(input) {
    const result = await api.corpus.imports.create(input)
    if (result?.importId) beginImportRead(result.importId)
    commitImportRun(result)
    return result
  }

  async function getImport(importId) {
    const generation = beginImportRead(importId)
    const result = await api.corpus.imports.get(importId)
    if (importReadGenerations.get(importId) === generation) commitImportRun(result)
    return result
  }

  async function getSource(sourceId, revision, contentHash) {
    const key = immutableKey(sourceId, revision, contentHash)
    if (sourceDetails.value[key]) return sourceDetails.value[key]
    const source = assertSourceIdentity(
      await api.corpus.sources.get(sourceId, { previewChars: 1200 }),
      sourceId,
      revision,
      contentHash,
    )
    sourceDetails.value[key] = source
    return source
  }

  async function loadVersions(
    sourceId,
    { cursor = null, limit = 50, force = false } = {},
  ) {
    if (!cursor && !force && sourceVersions.value[sourceId]) {
      return sourceVersions.value[sourceId]
    }
    const result = await api.corpus.sources.versions(sourceId, {
      cursor: cursor || undefined,
      limit,
    })
    const previous = cursor ? sourceVersions.value[sourceId]?.items || [] : []
    const seen = new Set(previous.map(item => `${item.id}:${item.revision}`))
    const items = [
      ...previous,
      ...(result?.items || []).filter(item => {
        const key = `${item.id}:${item.revision}`
        if (seen.has(key)) return false
        seen.add(key)
        return true
      }),
    ]
    const page = { items, nextCursor: result?.nextCursor ?? null }
    sourceVersions.value[sourceId] = page
    return page
  }

  function invalidateMutableSource(sourceId) {
    delete sourceVersions.value[sourceId]
    for (const key of Object.keys(sourceDetails.value)) {
      if (key.startsWith(`${sourceId}\u0000`)) delete sourceDetails.value[key]
    }
  }

  function commitLifecycleSource(result) {
    if (!result?.id) return result
    sources.value = sources.value.map(source => (
      source.id === result.id ? result : source
    ))
    invalidateMutableSource(result.id)
    return result
  }

  async function archiveSource(sourceId, expectedRevision) {
    return commitLifecycleSource(
      await api.corpus.sources.archive(sourceId, expectedRevision),
    )
  }

  async function restoreSource(sourceId, expectedRevision) {
    return commitLifecycleSource(
      await api.corpus.sources.restore(sourceId, expectedRevision),
    )
  }

  async function permanentlyDeleteSource(
    sourceId,
    expectedRevision,
    confirmPermanentDelete,
  ) {
    await api.corpus.sources.permanentlyDelete(
      sourceId,
      expectedRevision,
      confirmPermanentDelete,
    )
    sources.value = sources.value.filter(source => source.id !== sourceId)
    invalidateMutableSource(sourceId)
  }

  async function loadChapters(sourceId, revision, contentHash) {
    const key = immutableKey(sourceId, revision, contentHash)
    if (chapterLists.value[key]) return chapterLists.value[key]
    const result = await api.corpus.sources.chapters(sourceId)
    const rows = result?.items || []
    chapterLists.value[key] = rows
    return rows
  }

  async function loadFragments(chapterId, params = {}) {
    const generation = fragmentGuard.begin()
    loadingFragments.value = true
    try {
      const result = await api.corpus.chapters.fragments(chapterId, params)
      if (fragmentGuard.isCurrent(generation)) fragmentPage.value = result
      return result
    } finally {
      if (fragmentGuard.isCurrent(generation)) loadingFragments.value = false
    }
  }

  function clearFragments() {
    fragmentGuard.invalidate()
    fragmentPage.value = null
    loadingFragments.value = false
  }

  function toContractRef(source, selectionMode = 'author') {
    immutableKey(source?.id, source?.revision, source?.contentHash)
    if (selectionMode !== 'author' && selectionMode !== 'system') {
      throw new TypeError('Corpus selection mode must be author or system')
    }
    return Object.freeze({
      id: source.id,
      revision: source.revision,
      contentHash: source.contentHash,
      selectionMode,
    })
  }

  function invalidateQueryState() {
    discoveryGuard.invalidate()
    sourceListGuard.invalidate()
    discovery.value = null
    sources.value = []
    loadingDiscovery.value = false
    loadingSources.value = false
    clearFragments()
  }

  return {
    discovery,
    sources,
    fragmentPage,
    importRuns,
    sourceDetails,
    sourceVersions,
    chapterLists,
    loadingDiscovery,
    loadingSources,
    loadingFragments,
    discover,
    loadSources,
    importSource,
    getImport,
    getSource,
    loadVersions,
    archiveSource,
    restoreSource,
    permanentlyDeleteSource,
    loadChapters,
    loadFragments,
    clearFragments,
    toContractRef,
    invalidateSourceList,
    invalidateQueryState,
  }
})
