import { ref, shallowRef, watch } from 'vue'

const hash = value => typeof value === 'string' && /^[a-f0-9]{64}$/u.test(value)
const key = (entityId, fieldPath) => JSON.stringify([entityId, fieldPath])

export function createFinalizationHistory({ getProjectId, getSessionId, getReview, getCandidates, readHistory }) {
  const reference = shallowRef(null)
  const loading = ref(false)
  const canRead = ref(false)
  let generation = 0
  let disposed = false
  let currentIdentity = null

  function identity() {
    const review = getReview()
    const candidate = getCandidates().find(item => item.id === review?.candidateId && item.contentHash === review?.candidateHash)
    const projectId = getProjectId()
    const chapterSessionId = getSessionId()
    if (!projectId || !chapterSessionId || !review?.attemptId || !review?.candidateId
      || !hash(review.candidateHash) || !hash(review.changeSet?.contentHash)
      || !Number.isSafeInteger(review.changeSet?.revision) || review.changeSet.revision < 1
      || !Number.isSafeInteger(candidate?.canonRevision) || candidate.canonRevision < 0
      || !Array.isArray(review.changeSet.payload?.canonEvents) || !review.changeSet.payload.canonEvents.length) return null
    return { projectId, chapterSessionId, attemptId: review.attemptId,
      candidateId: review.candidateId, candidateHash: review.candidateHash, canonRevision: candidate.canonRevision,
      expectedRevision: review.changeSet.revision, expectedRevisionHash: review.changeSet.contentHash }
  }

  async function refresh() {
    const target = currentIdentity
    const token = ++generation
    if (disposed || !target) return null
    loading.value = true
    try {
      const { projectId, chapterSessionId, ...command } = target
      const value = await readHistory(projectId, chapterSessionId, command)
      if (disposed || token !== generation) return null
      if (!value || Object.entries(target).some(([field, expected]) => value[field] !== expected)) {
        throw new TypeError('history identity changed')
      }
      // Even a valid response cannot introduce keys outside the saved review.
      const saved = new Set(getReview().changeSet.payload.canonEvents.map(item => key(item.entityId, item.fieldPath)))
      if (!Array.isArray(value.items) || value.items.length !== saved.size
        || value.items.some(item => !saved.delete(key(item.entityId, item.fieldPath)))) {
        throw new TypeError('invalid saved history keys')
      }
      reference.value = value
      return value
    } catch {
      if (!disposed && token === generation) reference.value = null
      return null
    } finally {
      if (!disposed && token === generation) loading.value = false
    }
  }

  const stop = watch(() => JSON.stringify(identity()), value => {
    generation += 1
    currentIdentity = JSON.parse(value)
    reference.value = null
    loading.value = false
    canRead.value = Boolean(currentIdentity)
    if (currentIdentity) void refresh()
  }, { immediate: true, flush: 'sync' })

  function lookup(entityId, fieldPath) {
    const item = reference.value?.items.find(value => value.entityId === entityId && value.fieldPath === fieldPath)
    if (item) return item
    if (entityId === null) return { state: 'not_applicable', reason: 'global' }
    if (getReview()?.changeSet?.payload?.entities?.some(entity => entity.id === entityId)) {
      return { state: 'not_applicable', reason: 'new_entity' }
    }
    if (!getReview()?.changeSet?.payload?.canonEvents?.some(item => item.entityId === entityId && item.fieldPath === fieldPath)) {
      return { state: 'not_loaded' }
    }
    return { state: loading.value ? 'loading' : 'unavailable' }
  }

  function dispose() {
    disposed = true
    generation += 1
    stop()
    reference.value = null
    loading.value = false
  }
  return { reference, loading, canRead, refresh, lookup, dispose }
}
