import { defineStore } from 'pinia'
import { computed, ref, shallowRef } from 'vue'

import { api } from '../api/db/client.js'
import { createLatestRequestGuard } from '../utils/latestRequest.js'

const CONTENT_HASH = /^[0-9a-f]{64}$/
const IDEMPOTENCY_KEY = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/

function publicError(error) {
  return {
    status: Number(error?.status || 0),
    code: String(error?.code || 'request_failed'),
    message: String(error?.message || '请求失败'),
    correlationId: String(error?.correlationId || ''),
  }
}

function requireProjectId(value) {
  const normalized = String(value || '')
  if (!normalized) throw new TypeError('projectId is required')
  return normalized
}

function requireChapterNumber(value) {
  const normalized = Number(value)
  if (!Number.isInteger(normalized) || normalized < 1) {
    throw new TypeError('chapterNumber is required')
  }
  return normalized
}

function requireWorkspace(workspace) {
  if (!workspace?.session?.id || !workspace?.workingDraft) {
    throw new TypeError('chapter session is required')
  }
  return workspace
}

function requireWorkingDraftCommand(command) {
  if (
    !command
    || !Number.isInteger(command.expectedRevision)
    || command.expectedRevision < 1
    || typeof command.expectedContentHash !== 'string'
    || !CONTENT_HASH.test(command.expectedContentHash)
    || typeof command.content !== 'string'
  ) {
    throw new TypeError('working draft command is required')
  }
  return Object.freeze({
    expectedRevision: command.expectedRevision,
    expectedContentHash: command.expectedContentHash,
    content: command.content,
  })
}

function requireCandidateCommand(command) {
  if (
    !command
    || !Number.isInteger(command.expectedWorkingDraftRevision)
    || command.expectedWorkingDraftRevision < 1
    || typeof command.expectedContentHash !== 'string'
    || !CONTENT_HASH.test(command.expectedContentHash)
    || typeof command.idempotencyKey !== 'string'
    || !IDEMPOTENCY_KEY.test(command.idempotencyKey)
  ) {
    throw new TypeError('candidate command is required')
  }
  return Object.freeze({
    expectedWorkingDraftRevision: command.expectedWorkingDraftRevision,
    expectedContentHash: command.expectedContentHash,
    idempotencyKey: command.idempotencyKey,
  })
}

const CANDIDATE_BASIS_FIELDS = Object.freeze([
  'outlineRevisionId',
  'outlineRevision',
  'outlineHash',
  'planningRevisionId',
  'planningRevision',
  'planningHash',
  'canonRevision',
  'projectionRevision',
  'projectionHash',
])
const CANDIDATE_PUBLIC_FIELDS = Object.freeze([
  'id',
  'projectId',
  'chapterSessionId',
  'workingDraftRevision',
  'content',
  'contentHash',
])
function candidateBasisIsSafe(candidate) {
  return (
    typeof candidate?.outlineRevisionId === 'string'
    && candidate.outlineRevisionId.length > 0
    && Number.isInteger(candidate.outlineRevision)
    && candidate.outlineRevision >= 1
    && typeof candidate.outlineHash === 'string'
    && CONTENT_HASH.test(candidate.outlineHash)
    && typeof candidate?.planningRevisionId === 'string'
    && candidate.planningRevisionId.length > 0
    && Number.isInteger(candidate.planningRevision)
    && candidate.planningRevision >= 1
    && typeof candidate.planningHash === 'string'
    && CONTENT_HASH.test(candidate.planningHash)
    && Number.isInteger(candidate.canonRevision)
    && candidate.canonRevision >= 0
    && Number.isInteger(candidate.projectionRevision)
    && candidate.projectionRevision >= 0
    && typeof candidate.projectionHash === 'string'
    && CONTENT_HASH.test(candidate.projectionHash)
  )
}

function normalizeCandidate(candidate) {
  const source = candidate && typeof candidate === 'object' ? candidate : {}
  const basisStatus = source.basisStatus
  const basisIsSafe = (
    (basisStatus === 'current' || basisStatus === 'stale')
    && candidateBasisIsSafe(source)
  )
  const basis = Object.fromEntries(CANDIDATE_BASIS_FIELDS.map(field => [
    field,
    basisIsSafe ? source[field] : null,
  ]))
  return {
    ...Object.fromEntries(CANDIDATE_PUBLIC_FIELDS.map(field => [
      field,
      source[field],
    ])),
    ...basis,
    basisStatus: basisIsSafe ? basisStatus : 'stale',
  }
}

function normalizeWorkspace(nextWorkspace) {
  if (!nextWorkspace || typeof nextWorkspace !== 'object') return nextWorkspace
  return {
    ...nextWorkspace,
    candidates: Array.isArray(nextWorkspace.candidates)
      ? nextWorkspace.candidates.map(normalizeCandidate)
      : [],
  }
}

export const useChapterSessionStore = defineStore('chapterSession', () => {
  const projectId = ref('')
  const chapterNumber = ref(0)
  const workspace = shallowRef(null)
  const error = shallowRef(null)
  const loading = ref(false)
  const creating = ref(false)
  const savingDraft = ref(false)
  const savingCandidate = ref(false)
  const loadGuard = createLatestRequestGuard()
  const createGuard = createLatestRequestGuard()
  const draftGuard = createLatestRequestGuard()
  const candidateGuard = createLatestRequestGuard()
  const authoritativeEntryGuard = createLatestRequestGuard()
  let stateGeneration = 0

  const session = computed(() => workspace.value?.session || null)
  const workingDraft = computed(() => workspace.value?.workingDraft || null)
  const candidates = computed(() => (
    Array.isArray(workspace.value?.candidates) ? [...workspace.value.candidates] : []
  ))
  const hasSession = computed(() => Boolean(session.value?.id))
  const writeBusy = computed(() => (
    creating.value
    || savingDraft.value
    || savingCandidate.value
  ))
  const commandBusy = computed(() => (
    creating.value
    || savingCandidate.value
  ))
  const busy = computed(() => loading.value || writeBusy.value)

  function resetPendingFlags() {
    loading.value = false
    creating.value = false
    savingDraft.value = false
    savingCandidate.value = false
  }

  function assertWriteAvailable() {
    if (writeBusy.value) {
      throw new TypeError('chapter session write is already in progress')
    }
  }

  function enterContext(nextProjectId, nextChapterNumber) {
    const normalizedProjectId = requireProjectId(nextProjectId)
    const normalizedChapterNumber = requireChapterNumber(nextChapterNumber)
    if (
      projectId.value !== normalizedProjectId
      || chapterNumber.value !== normalizedChapterNumber
    ) {
      stateGeneration += 1
      loadGuard.invalidate()
      createGuard.invalidate()
      draftGuard.invalidate()
      candidateGuard.invalidate()
      authoritativeEntryGuard.invalidate()
      workspace.value = null
      error.value = null
      resetPendingFlags()
      projectId.value = normalizedProjectId
      chapterNumber.value = normalizedChapterNumber
    }
    return {
      projectId: normalizedProjectId,
      chapterNumber: normalizedChapterNumber,
    }
  }

  function isCurrent(
    guard,
    generation,
    targetProjectId,
    targetChapterNumber,
    targetStateGeneration,
  ) {
    return projectId.value === targetProjectId
      && chapterNumber.value === targetChapterNumber
      && guard.isCurrent(generation)
      && stateGeneration === targetStateGeneration
  }

  function acceptWorkspace(nextWorkspace) {
    workspace.value = normalizeWorkspace(nextWorkspace)
    error.value = null
  }

  function clearWorkspace() {
    workspace.value = null
    error.value = null
  }

  function workspaceMatchesAuthority(
    candidate,
    current,
    targetChapterNumber,
    expectedSessionId = null,
  ) {
    const sessionValue = candidate?.session
    const planning = current?.planningAuthority
    const projection = current?.canonProjectionAuthority
    const outline = current?.confirmedOutline
    const active = current?.activeSession
    const expectedPlanningRevisionId = (
      active?.planningRevisionId ?? planning?.planningRevisionId
    )
    const expectedPlanningRevision = active?.planningRevision ?? planning?.revision
    const expectedPlanningHash = active?.planningHash ?? planning?.contentHash
    const expectedOutlineRevisionId = (
      active?.outlineRevisionId ?? outline?.outlineRevisionId
    )
    const expectedOutlineRevision = active?.outlineRevision ?? outline?.revision
    const expectedOutlineHash = active?.outlineHash ?? outline?.contentHash
    return Boolean(
      sessionValue?.id
      && (!expectedSessionId || sessionValue.id === expectedSessionId)
      && sessionValue.chapterNum === targetChapterNumber
      && sessionValue.planningRevisionId === expectedPlanningRevisionId
      && sessionValue.planningRevision === expectedPlanningRevision
      && sessionValue.planningHash === expectedPlanningHash
      && sessionValue.chapterOutlineRevisionId === expectedOutlineRevisionId
      && sessionValue.chapterOutlineRevision === expectedOutlineRevision
      && sessionValue.chapterOutlineHash === expectedOutlineHash
      && (
        active
          ? (
            active.chapterSessionId === sessionValue.id
            && active.chapterNumber === sessionValue.chapterNum
            && active.planningRevisionId === sessionValue.planningRevisionId
            && active.planningRevision === sessionValue.planningRevision
            && active.planningHash === sessionValue.planningHash
            && active.outlineRevisionId === sessionValue.chapterOutlineRevisionId
            && active.outlineRevision === sessionValue.chapterOutlineRevision
            && active.outlineHash === sessionValue.chapterOutlineHash
          )
          : sessionValue.expectedCanonRevision === projection?.canonRevision
      )
    )
  }

  async function openAuthoritative(nextProjectId, nextChapterNumber) {
    const {
      projectId: targetProjectId,
      chapterNumber: targetChapterNumber,
    } = enterContext(nextProjectId, nextChapterNumber)
    const generation = authoritativeEntryGuard.begin()
    const targetStateGeneration = stateGeneration
    loading.value = true
    error.value = null
    try {
      const current = await api.chapterOutlines.current(targetProjectId)
      if (!isCurrent(
        authoritativeEntryGuard,
        generation,
        targetProjectId,
        targetChapterNumber,
        targetStateGeneration,
      )) return null
      if (
        current?.projectId !== targetProjectId
        || !Number.isInteger(current?.authoritativeChapterNumber)
        || current.authoritativeChapterNumber < 1
      ) {
        throw new TypeError('Invalid ChapterOutline authority state')
      }
      const routeMatches = (
        current.authoritativeChapterNumber === targetChapterNumber
      )
      const confirmed = current.confirmedOutline
      if (
        current.lifecycle === 'archived'
        || !routeMatches
        || !confirmed
      ) {
        clearWorkspace()
        return current
      }

      let loaded
      if (current.activeSession) {
        loaded = await api.chapterSessions.get(
          targetProjectId,
          targetChapterNumber,
        )
        if (!isCurrent(
          authoritativeEntryGuard,
          generation,
          targetProjectId,
          targetChapterNumber,
          targetStateGeneration,
        )) return null
        if (!workspaceMatchesAuthority(
          loaded,
          current,
          targetChapterNumber,
          current.activeSession.chapterSessionId,
        )) {
          throw new TypeError(
            'ChapterSession authority changed; refresh and retry',
          )
        }
      } else {
        if (
          confirmed.status !== 'current'
          || current.capabilities?.startSession !== true
        ) {
          clearWorkspace()
          return current
        }
        const planning = current.planningAuthority
        const projection = current.canonProjectionAuthority
        loaded = await api.chapterSessions.create(
          targetProjectId,
          targetChapterNumber,
          {
            chapterNumber: targetChapterNumber,
            expectedPlanningRevision: planning?.revision,
            expectedPlanningHash: planning?.contentHash,
            expectedOutlineRevision: confirmed.revision,
            expectedOutlineHash: confirmed.contentHash,
            expectedCanonRevision: projection?.canonRevision,
          },
        )
        if (!isCurrent(
          authoritativeEntryGuard,
          generation,
          targetProjectId,
          targetChapterNumber,
          targetStateGeneration,
        )) return null
        if (!workspaceMatchesAuthority(
          loaded,
          current,
          targetChapterNumber,
        )) {
          throw new TypeError(
            'ChapterSession authority changed; refresh and retry',
          )
        }
      }
      acceptWorkspace(loaded)
      return current
    } catch (failure) {
      if (isCurrent(
        authoritativeEntryGuard,
        generation,
        targetProjectId,
        targetChapterNumber,
        targetStateGeneration,
      )) {
        workspace.value = null
        error.value = publicError(failure)
      }
      throw failure
    } finally {
      if (
        projectId.value === targetProjectId
        && chapterNumber.value === targetChapterNumber
        && authoritativeEntryGuard.isCurrent(generation)
      ) {
        loading.value = false
      }
    }
  }

  async function load(nextProjectId, nextChapterNumber) {
    const {
      projectId: targetProjectId,
      chapterNumber: targetChapterNumber,
    } = enterContext(nextProjectId, nextChapterNumber)
    const generation = loadGuard.begin()
    const targetStateGeneration = stateGeneration
    loading.value = true
    try {
      const loaded = await api.chapterSessions.get(
        targetProjectId,
        targetChapterNumber,
      )
      if (isCurrent(
        loadGuard,
        generation,
        targetProjectId,
        targetChapterNumber,
        targetStateGeneration,
      )) {
        acceptWorkspace(loaded)
      }
      return loaded
    } catch (failure) {
      if (isCurrent(
        loadGuard,
        generation,
        targetProjectId,
        targetChapterNumber,
        targetStateGeneration,
      )) {
        error.value = publicError(failure)
      }
      throw failure
    } finally {
      if (
        projectId.value === targetProjectId
        && chapterNumber.value === targetChapterNumber
        && loadGuard.isCurrent(generation)
      ) {
        loading.value = false
      }
    }
  }

  async function create(nextProjectId, nextChapterNumber, command) {
    const {
      projectId: targetProjectId,
      chapterNumber: targetChapterNumber,
    } = enterContext(nextProjectId, nextChapterNumber)
    assertWriteAvailable()
    const generation = createGuard.begin()
    const targetStateGeneration = stateGeneration
    creating.value = true
    try {
      const created = await api.chapterSessions.create(
        targetProjectId,
        targetChapterNumber,
        {
          chapterNumber: command.chapterNumber,
          expectedPlanningRevision: command.expectedPlanningRevision,
          expectedPlanningHash: command.expectedPlanningHash,
          expectedOutlineRevision: command.expectedOutlineRevision,
          expectedOutlineHash: command.expectedOutlineHash,
          expectedCanonRevision: command.expectedCanonRevision,
        },
      )
      if (isCurrent(
        createGuard,
        generation,
        targetProjectId,
        targetChapterNumber,
        targetStateGeneration,
      )) {
        acceptWorkspace(created)
      }
      return created
    } catch (failure) {
      if (isCurrent(
        createGuard,
        generation,
        targetProjectId,
        targetChapterNumber,
        targetStateGeneration,
      )) {
        error.value = publicError(failure)
      }
      throw failure
    } finally {
      if (
        projectId.value === targetProjectId
        && chapterNumber.value === targetChapterNumber
        && createGuard.isCurrent(generation)
      ) {
        creating.value = false
      }
    }
  }

  async function saveWorkingDraft(nextProjectId, command) {
    const {
      projectId: targetProjectId,
      chapterNumber: targetChapterNumber,
    } = enterContext(nextProjectId, chapterNumber.value)
    assertWriteAvailable()
    const writeCommand = requireWorkingDraftCommand(command)
    const current = requireWorkspace(workspace.value)
    const generation = draftGuard.begin()
    const targetStateGeneration = stateGeneration
    savingDraft.value = true
    try {
      const saved = await api.chapterSessions.saveWorkingDraft(
        targetProjectId,
        current.session.id,
        writeCommand,
      )
      if (isCurrent(
        draftGuard,
        generation,
        targetProjectId,
        targetChapterNumber,
        targetStateGeneration,
      )) {
        acceptWorkspace(saved)
      }
      return saved
    } catch (failure) {
      if (isCurrent(
        draftGuard,
        generation,
        targetProjectId,
        targetChapterNumber,
        targetStateGeneration,
      )) {
        error.value = publicError(failure)
      }
      throw failure
    } finally {
      if (
        projectId.value === targetProjectId
        && chapterNumber.value === targetChapterNumber
        && draftGuard.isCurrent(generation)
      ) {
        savingDraft.value = false
      }
    }
  }

  async function saveCandidate(nextProjectId, command) {
    const {
      projectId: targetProjectId,
      chapterNumber: targetChapterNumber,
    } = enterContext(nextProjectId, chapterNumber.value)
    assertWriteAvailable()
    const writeCommand = requireCandidateCommand(command)
    const current = requireWorkspace(workspace.value)
    const generation = candidateGuard.begin()
    const targetStateGeneration = stateGeneration
    savingCandidate.value = true
    try {
      const saved = await api.chapterSessions.saveCandidate(
        targetProjectId,
        current.session.id,
        writeCommand,
      )
      if (isCurrent(
        candidateGuard,
        generation,
        targetProjectId,
        targetChapterNumber,
        targetStateGeneration,
      )) {
        acceptWorkspace(saved)
      }
      return saved
    } catch (failure) {
      if (isCurrent(
        candidateGuard,
        generation,
        targetProjectId,
        targetChapterNumber,
        targetStateGeneration,
      )) {
        error.value = publicError(failure)
      }
      throw failure
    } finally {
      if (
        projectId.value === targetProjectId
        && chapterNumber.value === targetChapterNumber
        && candidateGuard.isCurrent(generation)
      ) {
        savingCandidate.value = false
      }
    }
  }

  function operationContext(nextProjectId) {
    const context = enterContext(nextProjectId, chapterNumber.value)
    const current = requireWorkspace(workspace.value)
    return { projectId: context.projectId, sessionId: current.session.id }
  }

  async function createDraftOperation(nextProjectId, command) {
    const context = operationContext(nextProjectId)
    return api.chapterSessions.createDraftOperation(
      context.projectId,
      context.sessionId,
      command,
    )
  }

  async function readDraftOperation(nextProjectId, operationId) {
    const context = operationContext(nextProjectId)
    return api.chapterSessions.readDraftOperation(
      context.projectId,
      context.sessionId,
      operationId,
    )
  }

  async function listDraftOperationEvents(nextProjectId, operationId, afterSequence) {
    const context = operationContext(nextProjectId)
    return api.chapterSessions.listDraftOperationEvents(
      context.projectId,
      context.sessionId,
      operationId,
      afterSequence,
    )
  }

  function reloadCurrentWorkspace(nextProjectId) {
    return load(nextProjectId, chapterNumber.value)
  }

  function invalidate() {
    stateGeneration += 1
    loadGuard.invalidate()
    createGuard.invalidate()
    draftGuard.invalidate()
    candidateGuard.invalidate()
    authoritativeEntryGuard.invalidate()
    resetPendingFlags()
  }

  return {
    projectId,
    chapterNumber,
    workspace,
    error,
    loading,
    creating,
    savingDraft,
    savingCandidate,
    session,
    workingDraft,
    candidates,
    hasSession,
    writeBusy,
    commandBusy,
    busy,
    load,
    openAuthoritative,
    create,
    saveWorkingDraft,
    createDraftOperation,
    readDraftOperation,
    listDraftOperationEvents,
    reloadCurrentWorkspace,
    saveCandidate,
    invalidate,
  }
})
