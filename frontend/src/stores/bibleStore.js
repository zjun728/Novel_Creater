import { computed, ref, shallowRef } from 'vue'
import { defineStore } from 'pinia'

import { api } from '../api/db/client.js'
import { createLatestRequestGuard } from '../utils/latestRequest.js'

const BIBLE_SCALAR_FIELDS = [
  'premiseAndPromise', 'powerOrProgressionSystem', 'protagonist',
  'toneAndNarrativeBoundaries',
]
const BIBLE_ARRAY_FIELDS = [
  'worldRules', 'coreCast', 'factions', 'longTermConflicts',
  'relationshipDynamics', 'continuityGuardrails', 'openDesignQuestions',
]
const BASIS_FIELDS = [
  'selectionRevision', 'seedId', 'seedRevisionId', 'seedHash', 'contractRevision',
  'creationContractId', 'creationHash', 'styleContractId', 'styleHash',
  'bindingRevisionId', 'bindingHash', 'policyVersion',
]

function publicError(error) {
  return {
    status: Number(error?.status || 0),
    code: String(error?.code || 'request_failed'),
    message: String(error?.message || '请求失败'),
    correlationId: String(error?.correlationId || ''),
  }
}

function publicBible(value) {
  if (!value || typeof value !== 'object') return null
  const result = {}
  for (const field of BIBLE_SCALAR_FIELDS) result[field] = value[field]
  for (const field of BIBLE_ARRAY_FIELDS) {
    result[field] = Array.isArray(value[field])
      ? value[field].map(item => ({ id: item?.id, text: item?.text }))
      : []
  }
  return result
}

function publicBasis(value) {
  if (!value || typeof value !== 'object') return null
  const result = {}
  for (const field of BASIS_FIELDS) result[field] = value[field]
  return result
}

function publicDraft(value) {
  if (!value || typeof value !== 'object') return null
  return {
    projectId: value.projectId,
    lifecycle: value.lifecycle,
    status: value.status,
    draftId: value.draftId,
    draftVersion: value.draftVersion,
    baseHeadRevision: value.baseHeadRevision,
    contentHash: value.contentHash,
    // A missing server draft is meaningful state. The UI controller may create a local first draft.
    draft: publicBible(value.draft),
    basis: publicBasis(value.basis),
    canEdit: value.canEdit === true,
    canConfirm: value.canConfirm === true,
    reasons: Array.isArray(value.reasons) ? [...value.reasons] : [],
    createdAt: value.createdAt,
    updatedAt: value.updatedAt,
  }
}

function publicRevision(value) {
  if (!value || typeof value !== 'object') return null
  return {
    projectId: value.projectId,
    lifecycle: value.lifecycle,
    status: value.status,
    bibleRevisionId: value.bibleRevisionId,
    revision: value.revision,
    contentHash: value.contentHash,
    bible: publicBible(value.bible),
    basis: publicBasis(value.basis),
    canEdit: value.canEdit === true,
    reasons: Array.isArray(value.reasons) ? [...value.reasons] : [],
    confirmedAt: value.confirmedAt,
  }
}

function publicGenerationAttempt(value) {
  if (!value || typeof value !== 'object') return null
  return {
    id: value.id,
    projectId: value.projectId,
    status: value.status,
    attemptVersion: value.attemptVersion,
    providerId: value.providerId,
    modelNameSnapshot: value.modelNameSnapshot,
    inputManifestHash: value.inputManifestHash,
    resultHash: value.resultHash ?? null,
    publicErrorCode: value.publicErrorCode ?? null,
    createdAt: value.createdAt,
    completedAt: value.completedAt ?? null,
  }
}

function denied(code) {
  return Object.assign(new Error('Bible write is not allowed'), { code })
}

export const useBibleStore = defineStore('bible', () => {
  const projectId = ref('')
  const head = shallowRef(null)
  const draft = shallowRef(null)
  const history = ref([])
  const historyNextBeforeRevision = ref(null)
  const historyDetail = shallowRef(null)
  const error = shallowRef(null)
  const conflict = shallowRef(null)
  const loading = ref(false)
  const saving = ref(false)
  const confirming = ref(false)
  const generating = ref(false)
  const historyLoading = ref(false)
  const dirty = ref(false)
  const generationAttempt = shallowRef(null)
  const readOnly = ref(false)
  const headHydrated = ref(false)
  const loadGuard = createLatestRequestGuard()
  const writeGuard = createLatestRequestGuard()
  const historyGuard = createLatestRequestGuard()
  const generationGuard = createLatestRequestGuard()
  const confirmCommands = new Map()
  let stateGeneration = 0
  let editGeneration = 0

  const baselineLocked = computed(() => headHydrated.value && Number(head.value?.revision || 0) > 0)
  const canEdit = computed(() => headHydrated.value && !readOnly.value && !baselineLocked.value && draft.value?.canEdit === true)
  const canConfirm = computed(() => headHydrated.value && !readOnly.value && !baselineLocked.value && draft.value?.canConfirm === true)
  const reasons = computed(() => {
    const draftReasons = draft.value?.reasons || []
    return [...(draftReasons.length > 0 ? draftReasons : head.value?.reasons || [])]
  })

  function enterProject(nextProjectId, options = {}) {
    const next = String(nextProjectId || '')
    if (!next) throw new TypeError('projectId is required')
    if (projectId.value !== next) {
      stateGeneration += 1
      editGeneration += 1
      loadGuard.invalidate(); writeGuard.invalidate(); historyGuard.invalidate(); generationGuard.invalidate()
      projectId.value = next; head.value = null; draft.value = null; history.value = []
      headHydrated.value = false
      historyNextBeforeRevision.value = null; historyDetail.value = null; generationAttempt.value = null; error.value = null
      conflict.value = null; dirty.value = false; loading.value = false; saving.value = false
      confirming.value = false; generating.value = false; historyLoading.value = false
    }
    if (options.readOnly !== undefined) readOnly.value = options.readOnly === true
    return next
  }

  function current(guard, requestGeneration, targetProject, targetStateGeneration) {
    return projectId.value === targetProject
      && stateGeneration === targetStateGeneration
      && guard.isCurrent(requestGeneration)
  }

  function assertWritable(kind) {
    if (!headHydrated.value) throw denied('bible_hydration_unknown')
    if (readOnly.value || baselineLocked.value || draft.value?.lifecycle === 'archived' || head.value?.lifecycle === 'archived') throw denied('bible_read_only')
    if (kind === 'edit' || kind === 'save') {
      if (draft.value?.canEdit !== true) throw denied('bible_edit_denied')
    } else if (kind === 'generate') {
      if (draft.value?.canEdit !== true) throw denied('bible_edit_denied')
      if (dirty.value) throw denied('bible_generation_dirty')
    } else if (kind === 'confirm' && draft.value?.canConfirm !== true) throw denied('bible_confirm_denied')
  }

  async function load(nextProjectId, options = {}) {
    const targetProject = enterProject(nextProjectId, options)
    const requestGeneration = loadGuard.begin()
    const targetStateGeneration = ++stateGeneration
    loading.value = true
    headHydrated.value = false
    try {
      const [loadedHead, loadedDraft] = await Promise.all([
        api.bible.head(targetProject), api.bible.draft.get(targetProject),
      ])
      if (current(loadGuard, requestGeneration, targetProject, targetStateGeneration)) {
        head.value = publicRevision(loadedHead)
        draft.value = publicDraft(loadedDraft)
        headHydrated.value = true
        error.value = null; conflict.value = null; dirty.value = false
      }
      return { head: publicRevision(loadedHead), draft: publicDraft(loadedDraft) }
    } catch (failure) {
      if (current(loadGuard, requestGeneration, targetProject, targetStateGeneration)) error.value = publicError(failure)
      throw failure
    } finally {
      if (current(loadGuard, requestGeneration, targetProject, targetStateGeneration)) loading.value = false
    }
  }

  function edit(nextBible) {
    assertWritable('edit')
    if (!draft.value) throw denied('bible_draft_missing')
    editGeneration += 1
    draft.value = { ...draft.value, draft: publicBible(nextBible) }
    dirty.value = true; conflict.value = null
  }

  async function save(nextProjectId, nextBible) {
    const targetProject = enterProject(nextProjectId)
    assertWritable('save')
    if (nextBible !== undefined) edit(nextBible)
    const requestGeneration = writeGuard.begin()
    const targetStateGeneration = stateGeneration
    const savedEditGeneration = editGeneration
    saving.value = true; error.value = null
    try {
      const saved = publicDraft(await api.bible.draft.save(targetProject, {
        expectedDraftVersion: Number(draft.value.draftVersion ?? 0),
        draft: draft.value.draft,
      }))
      if (current(writeGuard, requestGeneration, targetProject, targetStateGeneration) && editGeneration === savedEditGeneration) {
        draft.value = saved; dirty.value = false; conflict.value = null
      }
      return saved
    } catch (failure) {
      if (current(writeGuard, requestGeneration, targetProject, targetStateGeneration)) {
        error.value = publicError(failure)
        if (Number(failure?.status) === 409) conflict.value = publicError(failure)
      }
      throw failure
    } finally {
      if (current(writeGuard, requestGeneration, targetProject, targetStateGeneration)) saving.value = false
    }
  }

  function confirm(nextProjectId, command) {
    const targetProject = enterProject(nextProjectId)
    const key = String(command?.idempotencyKey || '')
    if (!key) throw new TypeError('idempotencyKey is required')
    assertWritable('confirm')
    const draftVersion = Number(draft.value?.draftVersion)
    const headRevision = Number(head.value?.revision || 0)
    const commandKey = `${targetProject}:${key}:${draftVersion}:${headRevision}`
    if (confirmCommands.has(commandKey)) return confirmCommands.get(commandKey)
    const targetStateGeneration = stateGeneration
    const promise = (async () => {
      confirming.value = true; error.value = null
      try {
        const confirmed = publicRevision(await api.bible.confirm(targetProject, {
          idempotencyKey: key,
          expectedDraftVersion: draftVersion,
          expectedHeadRevision: headRevision,
        }))
        if (projectId.value === targetProject && stateGeneration === targetStateGeneration) {
          head.value = confirmed; draft.value = null; dirty.value = false; conflict.value = null
        }
        return confirmed
      } catch (failure) {
        if (projectId.value === targetProject && stateGeneration === targetStateGeneration) error.value = publicError(failure)
        // A rejected request is never safe to replay as the old promise. The controller retains
        // the idempotency key for outcome-unknown retries, so the next call performs a real POST.
        confirmCommands.delete(commandKey)
        throw failure
      } finally {
        if (projectId.value === targetProject && stateGeneration === targetStateGeneration) confirming.value = false
      }
    })()
    confirmCommands.set(commandKey, promise)
    return promise
  }

  async function generate(nextProjectId, command = {}) {
    const targetProject = enterProject(nextProjectId)
    const key = String(command.idempotencyKey || '')
    if (!key) throw new TypeError('idempotencyKey is required')
    assertWritable('generate')
    const requestGeneration = generationGuard.begin()
    const targetStateGeneration = stateGeneration
    generating.value = true; error.value = null
    try {
      const response = await api.bible.generate(targetProject, {
        authorInstructions: String(command.authorInstructions || ''),
        expectedDraftVersion: Number(draft.value?.draftVersion ?? 0),
        expectedHeadRevision: Number(head.value?.revision || 0),
        idempotencyKey: key,
      })
      const attempt = publicGenerationAttempt(response?.attempt)
      if (current(generationGuard, requestGeneration, targetProject, targetStateGeneration)) {
        generationAttempt.value = attempt
      }
      if (
        attempt?.status === 'succeeded'
        && current(generationGuard, requestGeneration, targetProject, targetStateGeneration)
      ) {
        headHydrated.value = false
        const [loadedHead, loadedDraft] = await Promise.all([
          api.bible.head(targetProject),
          api.bible.draft.get(targetProject),
        ])
        if (current(generationGuard, requestGeneration, targetProject, targetStateGeneration)) {
          head.value = publicRevision(loadedHead)
          draft.value = publicDraft(loadedDraft)
          headHydrated.value = true
          dirty.value = false
          conflict.value = null
        }
      }
      return attempt
    } catch (failure) {
      if (current(generationGuard, requestGeneration, targetProject, targetStateGeneration)) {
        error.value = publicError(failure)
      }
      throw failure
    } finally {
      if (current(generationGuard, requestGeneration, targetProject, targetStateGeneration)) {
        generating.value = false
      }
    }
  }

  async function loadAttempt(nextProjectId, attemptId) {
    const targetProject = enterProject(nextProjectId)
    const requestGeneration = generationGuard.begin()
    const targetStateGeneration = stateGeneration
    try {
      const attempt = publicGenerationAttempt(
        await api.bible.generationAttempt(targetProject, attemptId),
      )
      if (current(generationGuard, requestGeneration, targetProject, targetStateGeneration)) {
        generationAttempt.value = attempt
      }
      return attempt
    } catch (failure) {
      if (current(generationGuard, requestGeneration, targetProject, targetStateGeneration)) {
        error.value = publicError(failure)
      }
      throw failure
    }
  }

  async function loadHistory(nextProjectId, params = {}) {
    const targetProject = enterProject(nextProjectId)
    const requestGeneration = historyGuard.begin(); const targetStateGeneration = stateGeneration
    historyLoading.value = true
    try {
      const page = await api.bible.history(targetProject, {
        limit: params.limit, beforeRevision: params.beforeRevision,
      })
      const items = Array.isArray(page?.items) ? page.items.map(publicRevision) : []
      if (current(historyGuard, requestGeneration, targetProject, targetStateGeneration)) {
        history.value = params.append === true ? [...history.value, ...items] : items
        historyNextBeforeRevision.value = page?.nextBeforeRevision ?? null
      }
      return { items, nextBeforeRevision: page?.nextBeforeRevision ?? null }
    } catch (failure) {
      if (current(historyGuard, requestGeneration, targetProject, targetStateGeneration)) error.value = publicError(failure)
      throw failure
    } finally {
      if (current(historyGuard, requestGeneration, targetProject, targetStateGeneration)) historyLoading.value = false
    }
  }

  async function loadHistoryDetail(nextProjectId, revision) {
    const targetProject = enterProject(nextProjectId)
    const requestGeneration = historyGuard.begin(); const targetStateGeneration = stateGeneration
    historyLoading.value = true
    try {
      const result = publicRevision(await api.bible.historyDetail(targetProject, revision))
      if (current(historyGuard, requestGeneration, targetProject, targetStateGeneration)) historyDetail.value = result
      return result
    } catch (failure) {
      if (current(historyGuard, requestGeneration, targetProject, targetStateGeneration)) error.value = publicError(failure)
      throw failure
    } finally {
      if (current(historyGuard, requestGeneration, targetProject, targetStateGeneration)) historyLoading.value = false
    }
  }

  function setReadOnly(value) { readOnly.value = value === true }
  function clearHistory() { historyGuard.invalidate(); history.value = []; historyNextBeforeRevision.value = null; historyDetail.value = null }

  return {
    projectId, head, draft, history, historyNextBeforeRevision, historyDetail, error, conflict,
    loading, saving, confirming, generating, historyLoading, dirty, readOnly, headHydrated,
    generationAttempt, baselineLocked, canEdit, canConfirm, reasons, load, edit, save, confirm,
    generate, loadAttempt, loadHistory, loadHistoryDetail,
    setReadOnly, clearHistory,
  }
})
