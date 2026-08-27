import { computed, ref, shallowRef, toRaw } from 'vue'

import { mapProjectNextAction } from '../projects/projectNextAction.js'
import { finalChapterPath as projectFinalChapterPath } from '../../router/projectRoutes.js'
import { generateId } from '../../utils/id.js'
import { sha256Text } from '../../utils/sha256Text.js'


const HASH = /^[a-f0-9]{64}$/u

function unavailable(label) {
  return () => Promise.reject(new TypeError(`${label} is required`))
}

function currentRevision(review) {
  const revision = review?.changeSet?.revision
  const contentHash = review?.changeSet?.contentHash
  if (!Number.isInteger(revision) || revision < 1 || !HASH.test(contentHash || '')) {
    throw new TypeError('current finalization revision is required')
  }
  return { expectedRevision: revision, expectedRevisionHash: contentHash }
}

function currentCandidate(value) {
  if (
    !value
    || typeof value.id !== 'string'
    || !value.id
    || value.basisStatus !== 'current'
    || !HASH.test(value.contentHash || '')
    || !Number.isInteger(value.canonRevision)
    || value.canonRevision < 0
    || !HASH.test(value.planningHash || '')
    || !HASH.test(value.outlineHash || '')
  ) throw new TypeError('current Candidate is required')
  return value
}

function unavailableCurrentAction(mapNextAction) {
  try {
    return mapNextAction(null)
  } catch {
    return Object.freeze({ state: 'unavailable', label: '重新读取创作状态' })
  }
}

function projectIdValue(value) {
  if (typeof value !== 'string') return ''
  const projectId = value.trim()
  return projectId && !/\p{C}/u.test(projectId) ? projectId : ''
}

function chapterNumberValue(value) {
  return Number.isSafeInteger(value) && value > 0 ? value : null
}

function routePathValue(value) {
  return typeof value === 'string'
    && /^\/(?!\/)/u.test(value)
    && !/[\\\u0000-\u001f\u007f]/u.test(value)
    ? value
    : ''
}

export function createFinalizationController({
  getReview = unavailable('getReview'),
  prepare = unavailable('prepare'),
  correct = unavailable('correct'),
  confirm = unavailable('confirm'),
  cancel = unavailable('cancel'),
  commit = unavailable('commit'),
  onCommitted = async () => {},
  getProjectId = () => '',
  getChapterNumber = () => null,
  reloadPreparation = unavailable('reloadPreparation'),
  readFinalizedChapter = unavailable('readFinalizedChapter'),
  mapNextAction = mapProjectNextAction,
  finalizedChapterPath = projectFinalChapterPath,
  idFactory = generateId,
} = {}) {
  const review = shallowRef(null)
  const result = shallowRef(null)
  const postFinalization = shallowRef(null)
  const postBusy = ref(false)
  const busy = ref(false)
  const error = ref('')
  let generation = 0
  let postGeneration = 0
  let disposed = false
  let committedTarget = null

  const hardBlocks = computed(() => (
    Array.isArray(review.value?.qualityReport?.deterministicBlocks)
      ? review.value.qualityReport.deterministicBlocks
      : []
  ))
  const finalized = computed(() => (
    review.value?.status === 'committed' || result.value !== null
  ))
  const primaryAction = computed(() => {
    if (finalized.value) return 'done'
    if (
      hardBlocks.value.length
      || ['failed', 'invalidated', 'cancelled'].includes(review.value?.status)
    ) return 'blocked'
    if (!review.value) return 'prepare'
    if (!review.value.changeSet) return 'blocked'
    const confirmation = review.value.confirmation
    return confirmation?.revision === review.value.changeSet.revision
      && confirmation?.contentHash === review.value.changeSet.contentHash
      ? 'commit'
      : 'confirm'
  })

  async function key(kind) {
    const value = idFactory()
    if (typeof value !== 'string' || !value) {
      throw new TypeError('finalization idempotency key is invalid')
    }
    return sha256Text(`finalization:${kind}:${value}`)
  }

  async function refreshCommittedWorkspace() {
    try {
      await onCommitted()
    } catch {
      // The server commit is already authoritative; a later page load retries this refresh.
    }
  }

  function committedContext(committed = null, fallback = null) {
    const projectId = fallback?.projectId || projectIdValue(getProjectId())
    const resultChapterNumber = chapterNumberValue(committed?.chapterNumber)
    const chapterNumber = resultChapterNumber
      ?? fallback?.chapterNumber
      ?? chapterNumberValue(getChapterNumber())
    return projectId && chapterNumber ? Object.freeze({ projectId, chapterNumber }) : null
  }

  async function refreshPostFinalization(active = () => !disposed) {
    const target = committedTarget
    if (!target || disposed) return null
    const token = generation
    const postToken = ++postGeneration
    postBusy.value = true
    postFinalization.value = Object.freeze({
      currentAction: unavailableCurrentAction(mapNextAction),
      finalizedChapterPath: '',
      finalizedChapterReadable: false,
    })
    const [preparation, chapter] = await Promise.allSettled([
      Promise.resolve().then(() => reloadPreparation(target.projectId)),
      Promise.resolve().then(() => (
        readFinalizedChapter(target.projectId, target.chapterNumber)
      )),
    ])
    if (
      !active()
      || disposed
      || token !== generation
      || postToken !== postGeneration
      || target !== committedTarget
    ) {
      return null
    }
    let currentAction = unavailableCurrentAction(mapNextAction)
    if (preparation.status === 'fulfilled') {
      try {
        currentAction = mapNextAction(preparation.value)
      } catch {
        currentAction = unavailableCurrentAction(mapNextAction)
      }
    }
    const readable = chapter.status === 'fulfilled'
      && chapter.value?.projectId === target.projectId
      && chapter.value?.chapter?.number === target.chapterNumber
    let path = ''
    if (readable) {
      try {
        const value = finalizedChapterPath(target.projectId, target.chapterNumber)
        path = routePathValue(value)
      } catch {
        path = ''
      }
    }
    postFinalization.value = Object.freeze({
      currentAction,
      finalizedChapterPath: path,
      finalizedChapterReadable: readable && Boolean(path),
    })
    postBusy.value = false
    return postFinalization.value
  }

  async function run(action, message) {
    if (disposed || busy.value) return false
    const token = generation
    const active = () => !disposed && token === generation
    busy.value = true
    error.value = ''
    try {
      const value = await action(active)
      return active() ? value : null
    } catch (failure) {
      if (!disposed && token === generation) error.value = message
      throw failure
    } finally {
      if (!disposed && token === generation) busy.value = false
    }
  }

  async function load() {
    return run(async active => {
      const value = await getReview()
      if (!active()) return null
      review.value = value
      if (value?.status !== 'committed') result.value = null
      return value
    }, '定稿审查状态加载失败，请刷新后重试。')
  }

  async function prepareCandidate(candidateValue) {
    const candidate = currentCandidate(candidateValue)
    return run(async active => {
      await prepare(candidate.id, {
        candidateHash: candidate.contentHash,
        expectedCanonRevision: candidate.canonRevision,
        expectedPlanningHash: candidate.planningHash,
        expectedOutlineHash: candidate.outlineHash,
        idempotencyKey: await key('prepare'),
      })
      if (!active()) return null
      const value = await getReview()
      if (!active()) return null
      review.value = value
      result.value = null
      return value
    }, '审查未完成，请刷新权威状态后重试。')
  }

  async function correctChangeSet(changeSet) {
    return run(async active => {
      if (primaryAction.value === 'blocked' || finalized.value) {
        throw new TypeError('finalization correction is unavailable')
      }
      await correct({
        ...currentRevision(review.value),
        changeSet: structuredClone(toRaw(changeSet)),
      })
      if (!active()) return null
      const value = await getReview()
      if (!active()) return null
      review.value = value
      return value
    }, '修正未保存，请刷新后重试。')
  }

  async function confirmChangeSet() {
    return run(async active => {
      if (primaryAction.value !== 'confirm') {
        throw new TypeError('finalization confirmation is unavailable')
      }
      await confirm(currentRevision(review.value))
      if (!active()) return null
      const value = await getReview()
      if (!active()) return null
      review.value = value
      return value
    }, '确认未完成，请刷新后重试。')
  }

  async function cancelReview() {
    return run(async active => {
      if (primaryAction.value !== 'confirm') {
        throw new TypeError('finalization cancellation is unavailable')
      }
      await cancel(currentRevision(review.value))
      if (!active()) return null
      const value = await getReview()
      if (!active()) return null
      review.value = value
      result.value = null
      return value
    }, '放弃审查未完成，请刷新后重试。')
  }

  async function commitChapter() {
    return run(async active => {
      if (primaryAction.value !== 'commit') {
        throw new TypeError('finalization commit is unavailable')
      }
      const commitTarget = committedContext()
      const command = {
        ...currentRevision(review.value),
        idempotencyKey: await key('commit'),
      }
      try {
        const committed = await commit(command)
        if (!active()) return null
        committedTarget = committedContext(committed, commitTarget)
        result.value = committedTarget
          ? Object.freeze({ ...committed, chapterNumber: committedTarget.chapterNumber })
          : committed
        review.value = { ...review.value, status: 'committed' }
        await refreshCommittedWorkspace()
        await refreshPostFinalization(active)
        return result.value
      } catch (failure) {
        if (!active()) return null
        const unknown = Number(failure?.status || 0) === 0
          || Number(failure?.status || 0) === 502
        if (!unknown) throw failure
        const recovered = await getReview()
        if (!active()) return null
        if (recovered?.status !== 'committed') throw failure
        review.value = recovered
        error.value = ''
        committedTarget = commitTarget
        await refreshCommittedWorkspace()
        await refreshPostFinalization(active)
        return null
      }
    }, '定稿结果未确认，请刷新后查看当前状态。')
  }

  function reset() {
    generation += 1
    postGeneration += 1
    review.value = null
    result.value = null
    postFinalization.value = null
    postBusy.value = false
    committedTarget = null
    busy.value = false
    error.value = ''
  }

  function dispose() {
    reset()
    disposed = true
  }

  return {
    review,
    result,
    postFinalization,
    postBusy: computed(() => postBusy.value),
    busy: computed(() => busy.value),
    error,
    hardBlocks,
    finalized,
    primaryAction,
    load,
    prepareCandidate,
    correctChangeSet,
    confirmChangeSet,
    cancelReview,
    commitChapter,
    refreshPostFinalization,
    reset,
    dispose,
  }
}
