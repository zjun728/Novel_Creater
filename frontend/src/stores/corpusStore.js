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

  async function loadSources() {
    const generation = sourceListGuard.begin()
    loadingSources.value = true
    try {
      const result = await api.corpus.sources.list()
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
    chapterLists,
    loadingDiscovery,
    loadingSources,
    loadingFragments,
    discover,
    loadSources,
    importSource,
    getImport,
    getSource,
    loadChapters,
    loadFragments,
    clearFragments,
    toContractRef,
    invalidateSourceList,
    invalidateQueryState,
  }
})
