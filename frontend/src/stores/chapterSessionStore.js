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

function requireWorkspace(workspace) {
  if (!workspace?.session?.id || !workspace?.workingDraft) {
    throw new TypeError('chapter session is required')
  }
  return workspace
}

export const useChapterSessionStore = defineStore('chapterSession', () => {
  const projectId = ref('')
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
  let stateGeneration = 0

  const session = computed(() => workspace.value?.session || null)
  const workingDraft = computed(() => workspace.value?.workingDraft || null)
  const candidates = computed(() => (
    Array.isArray(workspace.value?.candidates) ? [...workspace.value.candidates] : []
  ))
  const hasSession = computed(() => Boolean(session.value?.id))

  function enterProject(nextProjectId) {
    const normalized = requireProjectId(nextProjectId)
    if (projectId.value !== normalized) {
      stateGeneration += 1
      loadGuard.invalidate()
      createGuard.invalidate()
      draftGuard.invalidate()
      candidateGuard.invalidate()
      workspace.value = null
      error.value = null
      loading.value = false
      creating.value = false
      savingDraft.value = false
      savingCandidate.value = false
      projectId.value = normalized
    }
    return normalized
  }

  function isCurrent(guard, generation, targetProjectId, targetStateGeneration) {
    return projectId.value === targetProjectId
      && guard.isCurrent(generation)
      && stateGeneration === targetStateGeneration
  }

  function acceptWorkspace(nextWorkspace) {
    workspace.value = nextWorkspace
    error.value = null
  }

  async function load(nextProjectId) {
    const targetProjectId = enterProject(nextProjectId)
    const generation = loadGuard.begin()
    const targetStateGeneration = ++stateGeneration
    loading.value = true
    try {
      const loaded = await api.chapterSessions.current(targetProjectId)
      if (isCurrent(loadGuard, generation, targetProjectId, targetStateGeneration)) {
        acceptWorkspace(loaded)
      }
      return loaded
    } catch (failure) {
      if (isCurrent(loadGuard, generation, targetProjectId, targetStateGeneration)) {
        error.value = publicError(failure)
      }
      throw failure
    } finally {
      if (projectId.value === targetProjectId && loadGuard.isCurrent(generation)) {
        loading.value = false
      }
    }
  }

  async function create(nextProjectId, command) {
    const targetProjectId = enterProject(nextProjectId)
    const generation = createGuard.begin()
    const targetStateGeneration = ++stateGeneration
    creating.value = true
    try {
      const created = await api.chapterSessions.create(targetProjectId, {
        expectedStoryBlockRevision: command.expectedStoryBlockRevision,
        expectedCanonRevision: command.expectedCanonRevision,
      })
      if (isCurrent(createGuard, generation, targetProjectId, targetStateGeneration)) {
        acceptWorkspace(created)
      }
      return created
    } catch (failure) {
      if (isCurrent(createGuard, generation, targetProjectId, targetStateGeneration)) {
        error.value = publicError(failure)
      }
      throw failure
    } finally {
      if (projectId.value === targetProjectId && createGuard.isCurrent(generation)) {
        creating.value = false
      }
    }
  }

  async function saveWorkingDraft(nextProjectId, content) {
    const targetProjectId = enterProject(nextProjectId)
    const current = requireWorkspace(workspace.value)
    const generation = draftGuard.begin()
    const targetStateGeneration = ++stateGeneration
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
      if (isCurrent(draftGuard, generation, targetProjectId, targetStateGeneration)) {
        acceptWorkspace(saved)
      }
      return saved
    } catch (failure) {
      if (isCurrent(draftGuard, generation, targetProjectId, targetStateGeneration)) {
        error.value = publicError(failure)
      }
      throw failure
    } finally {
      if (projectId.value === targetProjectId && draftGuard.isCurrent(generation)) {
        savingDraft.value = false
      }
    }
  }

  async function saveCandidate(nextProjectId) {
    const targetProjectId = enterProject(nextProjectId)
    const current = requireWorkspace(workspace.value)
    const generation = candidateGuard.begin()
    const targetStateGeneration = ++stateGeneration
    savingCandidate.value = true
    try {
      const saved = await api.chapterSessions.saveCandidate(
        targetProjectId,
        current.session.id,
        { expectedWorkingDraftRevision: current.workingDraft.revision },
      )
      if (isCurrent(candidateGuard, generation, targetProjectId, targetStateGeneration)) {
        acceptWorkspace(saved)
      }
      return saved
    } catch (failure) {
      if (isCurrent(candidateGuard, generation, targetProjectId, targetStateGeneration)) {
        error.value = publicError(failure)
      }
      throw failure
    } finally {
      if (projectId.value === targetProjectId && candidateGuard.isCurrent(generation)) {
        savingCandidate.value = false
      }
    }
  }

  function invalidate() {
    stateGeneration += 1
    loadGuard.invalidate()
    createGuard.invalidate()
    draftGuard.invalidate()
    candidateGuard.invalidate()
  }

  return {
    projectId,
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
    load,
    create,
    saveWorkingDraft,
    saveCandidate,
    invalidate,
  }
})
