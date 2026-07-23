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
    draft: publicBible(value.draft),
    basis: publicBasis(value.basis),
    canEdit: value.canEdit === true,
    canConfirm: value.canConfirm === true,
    canClone: value.canClone === true,
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
    canClone: value.canClone === true,
    reasons: Array.isArray(value.reasons) ? [...value.reasons] : [],
    confirmedAt: value.confirmedAt,
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
  const cloning = ref(false)
  const historyLoading = ref(false)
  const dirty = ref(false)
  const readOnly = ref(false)
  const loadGuard = createLatestRequestGuard()
  const writeGuard = createLatestRequestGuard()
  const historyGuard = createLatestRequestGuard()
  const confirmCommands = new Map()
  let stateGeneration = 0
  let editGeneration = 0

  const canEdit = computed(() => !readOnly.value && draft.value?.canEdit === true)
  const canConfirm = computed(() => !readOnly.value && draft.value?.canConfirm === true)
  const canClone = computed(() => !readOnly.value && (draft.value?.canClone === true || head.value?.canClone === true))
  const reasons = computed(() => [...(draft.value?.reasons || head.value?.reasons || [])])

  function enterProject(nextProjectId, options = {}) {
    const next = String(nextProjectId || '')
    if (!next) throw new TypeError('projectId is required')
    if (projectId.value !== next) {
      stateGeneration += 1
      editGeneration += 1
      loadGuard.invalidate(); writeGuard.invalidate(); historyGuard.invalidate()
      projectId.value = next; head.value = null; draft.value = null; history.value = []
      historyNextBeforeRevision.value = null; historyDetail.value = null; error.value = null
      conflict.value = null; dirty.value = false; loading.value = false; saving.value = false
      confirming.value = false; cloning.value = false; historyLoading.value = false
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
    if (readOnly.value || draft.value?.lifecycle === 'archived' || head.value?.lifecycle === 'archived') throw denied('bible_read_only')
    if (kind === 'edit' || kind === 'save') {
      if (draft.value?.canEdit !== true) throw denied('bible_edit_denied')
    } else if (kind === 'confirm' && draft.value?.canConfirm !== true) throw denied('bible_confirm_denied')
    else if (kind === 'clone' && draft.value?.canClone !== true && head.value?.canClone !== true) throw denied('bible_clone_denied')
  }

  async function load(nextProjectId, options = {}) {
    const targetProject = enterProject(nextProjectId, options)
    const requestGeneration = loadGuard.begin()
    const targetStateGeneration = ++stateGeneration
    loading.value = true
    try {
      const [loadedHead, loadedDraft] = await Promise.all([
        api.bible.head(targetProject), api.bible.draft.get(targetProject),
      ])
      if (current(loadGuard, requestGeneration, targetProject, targetStateGeneration)) {
        head.value = publicRevision(loadedHead)
        draft.value = publicDraft(loadedDraft)
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
        expectedDraftVersion: draft.value.draftVersion,
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
    const commandKey = `${targetProject}:${key}`
    if (confirmCommands.has(commandKey)) return confirmCommands.get(commandKey)
    assertWritable('confirm')
    const targetStateGeneration = stateGeneration
    const promise = (async () => {
      confirming.value = true; error.value = null
      try {
        const confirmed = publicRevision(await api.bible.confirm(targetProject, {
          idempotencyKey: key,
          expectedDraftVersion: draft.value.draftVersion,
          expectedHeadRevision: head.value?.revision,
        }))
        if (projectId.value === targetProject && stateGeneration === targetStateGeneration) {
          head.value = confirmed; draft.value = null; dirty.value = false; conflict.value = null
        }
        return confirmed
      } catch (failure) {
        if (projectId.value === targetProject && stateGeneration === targetStateGeneration) error.value = publicError(failure)
        throw failure
      } finally {
        if (projectId.value === targetProject && stateGeneration === targetStateGeneration) confirming.value = false
      }
    })()
    confirmCommands.set(commandKey, promise)
    return promise
  }

  async function clone(nextProjectId, source) {
    const targetProject = enterProject(nextProjectId)
    assertWritable('clone')
    const requestGeneration = writeGuard.begin(); const targetStateGeneration = stateGeneration
    cloning.value = true; error.value = null
    try {
      const cloned = publicDraft(await api.bible.draft.clone(targetProject, source))
      if (current(writeGuard, requestGeneration, targetProject, targetStateGeneration)) {
        draft.value = cloned; dirty.value = false; conflict.value = null
      }
      return cloned
    } catch (failure) {
      if (current(writeGuard, requestGeneration, targetProject, targetStateGeneration)) error.value = publicError(failure)
      throw failure
    } finally {
      if (current(writeGuard, requestGeneration, targetProject, targetStateGeneration)) cloning.value = false
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
    const result = publicRevision(await api.bible.historyDetail(targetProject, revision))
    if (current(historyGuard, requestGeneration, targetProject, targetStateGeneration)) historyDetail.value = result
    return result
  }

  function setReadOnly(value) { readOnly.value = value === true }
  function clearHistory() { historyGuard.invalidate(); history.value = []; historyNextBeforeRevision.value = null; historyDetail.value = null }

  return {
    projectId, head, draft, history, historyNextBeforeRevision, historyDetail, error, conflict,
    loading, saving, confirming, cloning, historyLoading, dirty, readOnly, canEdit, canConfirm,
    canClone, reasons, load, edit, save, confirm, clone, loadHistory, loadHistoryDetail,
    setReadOnly, clearHistory,
  }
})
