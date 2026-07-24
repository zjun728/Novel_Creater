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

export const useChapterSessionStore = defineStore('chapterSession', () => {
  const projectId = ref('')
  const chapterNumber = ref(0)
  const workspace = shallowRef(null)
  const error = shallowRef(null)
  const loading = ref(false)
  const creating = ref(false)
  const savingDraft = ref(false)
  const savingCandidate = ref(false)
  const generatingDraft = ref(false)
  const loadGuard = createLatestRequestGuard()
  const createGuard = createLatestRequestGuard()
  const draftGuard = createLatestRequestGuard()
  const candidateGuard = createLatestRequestGuard()
  const generationGuard = createLatestRequestGuard()
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
    || generatingDraft.value
  ))
  const busy = computed(() => loading.value || writeBusy.value)

  function resetPendingFlags() {
    loading.value = false
    creating.value = false
    savingDraft.value = false
    savingCandidate.value = false
    generatingDraft.value = false
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
      generationGuard.invalidate()
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
    workspace.value = nextWorkspace
    error.value = null
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

  async function saveWorkingDraft(nextProjectId, content) {
    const {
      projectId: targetProjectId,
      chapterNumber: targetChapterNumber,
    } = enterContext(nextProjectId, chapterNumber.value)
    assertWriteAvailable()
    const current = requireWorkspace(workspace.value)
    const generation = draftGuard.begin()
    const targetStateGeneration = stateGeneration
    savingDraft.value = true
    try {
      const saved = await api.chapterSessions.saveWorkingDraft(
        targetProjectId,
        current.session.id,
        {
          expectedRevision: current.workingDraft.revision,
          content,
        },
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

  async function saveCandidate(nextProjectId) {
    const {
      projectId: targetProjectId,
      chapterNumber: targetChapterNumber,
    } = enterContext(nextProjectId, chapterNumber.value)
    assertWriteAvailable()
    const current = requireWorkspace(workspace.value)
    const generation = candidateGuard.begin()
    const targetStateGeneration = stateGeneration
    savingCandidate.value = true
    try {
      const saved = await api.chapterSessions.saveCandidate(
        targetProjectId,
        current.session.id,
        { expectedWorkingDraftRevision: current.workingDraft.revision },
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

  async function generateWorkingDraft(nextProjectId, authorInstruction = '') {
    const {
      projectId: targetProjectId,
      chapterNumber: targetChapterNumber,
    } = enterContext(nextProjectId, chapterNumber.value)
    assertWriteAvailable()
    const current = requireWorkspace(workspace.value)
    const generation = generationGuard.begin()
    const targetStateGeneration = stateGeneration
    generatingDraft.value = true
    try {
      const generated = await api.chapterSessions.generateWorkingDraft(
        targetProjectId,
        current.session.id,
        {
          expectedWorkingDraftRevision: current.workingDraft.revision,
          authorInstruction,
        },
      )
      if (isCurrent(
        generationGuard,
        generation,
        targetProjectId,
        targetChapterNumber,
        targetStateGeneration,
      )) {
        acceptWorkspace(generated)
      }
      return generated
    } catch (failure) {
      if (isCurrent(
        generationGuard,
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
        && generationGuard.isCurrent(generation)
      ) {
        generatingDraft.value = false
      }
    }
  }

  function invalidate() {
    stateGeneration += 1
    loadGuard.invalidate()
    createGuard.invalidate()
    draftGuard.invalidate()
    candidateGuard.invalidate()
    generationGuard.invalidate()
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
    generatingDraft,
    session,
    workingDraft,
    candidates,
    hasSession,
    writeBusy,
    busy,
    load,
    create,
    saveWorkingDraft,
    generateWorkingDraft,
    saveCandidate,
    invalidate,
  }
})
