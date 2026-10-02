import { computed, ref, shallowRef, toRaw } from 'vue'

import { mapWorkbenchNextAction } from '../projects/projectNextAction.js'
import { finalChapterPath as projectFinalChapterPath } from '../../router/projectRoutes.js'
import { generateId } from '../../utils/id.js'
import { sha256Text } from '../../utils/sha256Text.js'
import { effectiveReviewFindings } from '../../utils/reviewReference.js'


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
  decideFinding = unavailable('decideFinding'),
  disputeFinding = unavailable('disputeFinding'),
  disputeEvidence = unavailable('disputeEvidence'),
  confirm = unavailable('confirm'),
  cancel = unavailable('cancel'),
  revoke = unavailable('revoke'),
  getAttemptState = unavailable('getAttemptState'),
  commit = unavailable('commit'),
  onCommitted = async () => {},
  getProjectId = () => '',
  getSessionId = () => '',
  getChapterNumber = () => null,
  reloadPreparation = unavailable('reloadPreparation'),
  readFinalizedChapter = unavailable('readFinalizedChapter'),
  mapNextAction = mapWorkbenchNextAction,
  finalizedChapterPath = projectFinalChapterPath,
  idFactory = generateId,
} = {}) {
  const review = shallowRef(null)
  const result = shallowRef(null)
  const postFinalization = shallowRef(null)
  const postBusy = ref(false)
  const busy = ref(false)
  const error = ref('')
  const recoveryPending = ref(false)
  const commitUncertain = ref(false)
  let recoveryTarget = null
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
    const value = await idFactory()
    if (typeof value !== 'string' || !value) {
      throw new TypeError('finalization idempotency key is invalid')
    }
    return sha256Text(`finalization:${kind}:${value}`)
  }

  async function refreshCommittedWorkspace(target) {
    try {
      await onCommitted(target)
    } catch {
      // The server commit is already authoritative; a later page load retries this refresh.
    }
  }

  function committedContext(committed = null, fallback = null) {
    const projectId = fallback?.projectId || projectIdValue(getProjectId())
    const sessionId = fallback?.sessionId || projectIdValue(getSessionId())
    const resultChapterNumber = chapterNumberValue(committed?.chapterNumber)
    const chapterNumber = resultChapterNumber
      ?? fallback?.chapterNumber
      ?? chapterNumberValue(getChapterNumber())
    return projectId && chapterNumber ? Object.freeze({
      projectId,
      ...(sessionId ? { sessionId } : {}),
      chapterNumber,
    }) : null
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
        currentAction = mapNextAction(preparation.value, target.projectId)
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

  async function run(action, message, allowRecovery = false) {
    if (disposed || busy.value || (recoveryPending.value && !allowRecovery)) return false
    const token = generation
    const active = () => !disposed && token === generation
    busy.value = true
    error.value = ''
    try {
      const value = await action(active)
      return active() ? value : null
    } catch (failure) {
      if (!disposed && token === generation) {
        error.value = failure?.code === 'FinalizationPreflightConflict'
          ? '规划调整不符合当前定稿依据，请在未确认时放弃本次审查并重新审查。'
          : message
      }
      throw failure
    } finally {
      if (!disposed && token === generation) busy.value = false
    }
  }

  async function load() {
    return run(async active => {
      if (recoveryPending.value) {
        await reconcileRevocation(active)
        if (!active()) return null
      }
      const value = await getReview()
      if (!active()) return null
      review.value = value
      commitUncertain.value = false
      recoveryPending.value = false
      recoveryTarget = null
      if (value?.status !== 'committed') result.value = null
      return value
    }, '定稿审查状态加载失败，请刷新后重试。', true)
  }

  async function reconcileRevocation(active) {
    const target = recoveryTarget
    const state = await getAttemptState(target.attemptId)
    if (!active()) return null
    if (state?.attemptId !== target.attemptId
      || state.currentRevision !== target.expectedRevision
      || state.currentRevisionHash !== target.expectedRevisionHash
      || state.confirmedRevision !== target.expectedRevision
      || state.confirmedRevisionHash !== target.expectedRevisionHash
      || !['cancelled', 'awaiting_author', 'committed'].includes(state.status)) {
      throw new TypeError('revocation outcome is unresolved')
    }
    return state
  }

  async function revokeReview() {
    return run(async active => {
      if (primaryAction.value !== 'commit' || review.value?.status !== 'awaiting_author' || commitUncertain.value) {
        throw new TypeError('confirmed review revocation is unavailable')
      }
      const attemptId = review.value?.attemptId
      if (typeof attemptId !== 'string' || !attemptId) throw new TypeError('attempt is required')
      const command = currentRevision(review.value)
      recoveryTarget = { attemptId, ...command }
      try {
        await revoke(attemptId, command)
      } catch (failure) {
        if (!active()) return null
        const unknown = [0, 408, 502, 503, 504].includes(Number(failure?.status || 0))
        if (!unknown) {
          recoveryTarget = null
          // A concurrent commit may have won. Refresh its authoritative result.
          const current = await getReview()
          if (active()) review.value = current
          throw failure
        }
        recoveryPending.value = true
        const state = await reconcileRevocation(active)
        if (!active()) return null
        if (state.status !== 'cancelled') {
          const current = await getReview()
          if (active()) {
            review.value = current
            recoveryPending.value = false
            recoveryTarget = null
          }
          throw failure
        }
      }
      if (!active()) return null
      // Keep writes fenced if the successful POST's follow-up read is lost.
      recoveryTarget = { attemptId, ...command }
      recoveryPending.value = true
      const current = await getReview()
      if (!active()) return null
      review.value = current
      result.value = null
      recoveryPending.value = false
      recoveryTarget = null
      return current
    }, '撤销结果尚未确认，请刷新审查状态；不会自动重新审查。')
  }

  async function prepareCandidate(candidateValue) {
    const candidate = currentCandidate(candidateValue)
    return run(async active => {
      const idempotencyKey = await key('prepare')
      if (!active()) return null
      await prepare(candidate.id, {
        candidateHash: candidate.contentHash,
        expectedCanonRevision: candidate.canonRevision,
        expectedPlanningHash: candidate.planningHash,
        expectedOutlineHash: candidate.outlineHash,
        idempotencyKey,
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

  async function setFindingIgnored(findingId, ignored) {
    return run(async active => {
      const value = review.value
      const finding = value?.qualityReport?.findings?.find(item => item.id === findingId)
      if (value?.status !== 'awaiting_author' || finalized.value || value.confirmation || finding?.severity !== 'optional') throw new TypeError('finding decision unavailable')
      const next = await decideFinding({ ...currentRevision(value), attemptId: value.attemptId,
        qualityReportHash: value.qualityReport.contentHash,
        expectedDecisionsRevision: value.findingDecisions?.revision || 0, findingId, ignored })
      if (!active()) return null
      review.value = next
      return next
    }, '建议处理状态未能确认保存，请重新读取后再试。')
  }

  async function loadDisputeEvidence() {
    return run(async active => {
      const value = review.value
      if (value?.status !== 'awaiting_author' || value.confirmation || finalized.value) throw new TypeError('evidence unavailable')
      const result = await disputeEvidence(currentRevision(value))
      if (!active()) return null
      if (result.attemptId !== value.attemptId || result.candidateHash !== value.candidateHash) throw new TypeError('evidence changed')
      return result.records
    }, '依据读取失败，请重新读取审稿后重试。')
  }

  async function saveFindingDispute(data) {
    return run(async active => {
      const value = review.value
      if (value?.status !== 'awaiting_author' || value.confirmation || finalized.value) throw new TypeError('dispute unavailable')
      const next = await disputeFinding({ ...data, ...currentRevision(value), attemptId: value.attemptId,
        qualityReportHash: value.qualityReport.contentHash, expectedDecisionsRevision: value.findingDecisions?.revision || 0,
        eventId: await sha256Text(idFactory()) })
      if (!active()) return null
      review.value = next
      return next
    }, '作者处理尚未确认保存，请重新读取审稿核对结果后再试。')
  }

  async function confirmChangeSet() {
    return run(async active => {
      if (primaryAction.value !== 'confirm' || effectiveReviewFindings(review.value).some(item => item.severity === 'required')) {
        throw new TypeError('finalization confirmation is unavailable')
      }
      await confirm({ ...currentRevision(review.value), ...(review.value.findingDecisions?.disputeEvents?.length ? { expectedDecisionsRevisionPin: review.value.findingDecisions.revision } : {}) })
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
      const idempotencyKey = await key('commit')
      if (!active()) return null
      const command = {
        ...currentRevision(review.value),
        idempotencyKey,
      }
      try {
        const committed = await commit(command, commitTarget)
        if (!active()) return null
        committedTarget = committedContext(committed, commitTarget)
        result.value = committedTarget
          ? Object.freeze({ ...committed, chapterNumber: committedTarget.chapterNumber })
          : committed
        review.value = { ...review.value, status: 'committed' }
        await refreshCommittedWorkspace(committedTarget)
        await refreshPostFinalization(active)
        return result.value
      } catch (failure) {
        if (!active()) return null
        const unknown = [0, 408, 502, 503, 504].includes(Number(failure?.status || 0))
        if (!unknown) throw failure
        commitUncertain.value = true
        const recovered = await getReview()
        if (!active()) return null
        if (recovered?.status !== 'committed') throw failure
        commitUncertain.value = false
        review.value = recovered
        error.value = ''
        committedTarget = commitTarget
        await refreshCommittedWorkspace(committedTarget)
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
    recoveryTarget = null
    recoveryPending.value = false
    commitUncertain.value = false
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
    recoveryPending: computed(() => recoveryPending.value),
    canRevoke: computed(() => review.value?.status === 'awaiting_author'
      && primaryAction.value === 'commit' && !commitUncertain.value && !recoveryPending.value),
    hardBlocks,
    finalized,
    primaryAction,
    load,
    prepareCandidate,
    correctChangeSet,
    setFindingIgnored,
    loadDisputeEvidence,
    saveFindingDispute,
    confirmChangeSet,
    cancelReview,
    revokeReview,
    commitChapter,
    refreshPostFinalization,
    reset,
    dispose,
  }
}
