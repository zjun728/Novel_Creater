import { computed, ref, shallowRef } from 'vue'
import { defineStore } from 'pinia'

import { api } from '../api/db/client.js'
import { ApiError } from '../api/db/api-error.js'
import { createLatestRequestGuard } from '../utils/latestRequest.js'
import { unicodeScalarLength } from '../utils/unicodeScalarText.js'

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
const BIBLE_AUTHOR_FIELDS = [
  ['premiseAndPromise', '作品承诺', 'scalar'],
  ['worldRules', '世界规则', 'list'],
  ['powerOrProgressionSystem', '力量／成长体系', 'scalar'],
  ['protagonist', '主角', 'scalar'],
  ['coreCast', '核心人物', 'list'],
  ['factions', '势力', 'list'],
  ['longTermConflicts', '长期冲突', 'list'],
  ['relationshipDynamics', '关系动力', 'list'],
  ['toneAndNarrativeBoundaries', '基调与叙事边界', 'scalar'],
  ['continuityGuardrails', '连贯性护栏', 'list'],
  ['openDesignQuestions', '开放设计问题', 'list'],
]
const GENERATION_ATTEMPT_FIELDS = [
  'id', 'projectId', 'status', 'attemptVersion', 'providerId', 'modelNameSnapshot',
  'inputManifestHash', 'resultHash', 'publicErrorCode', 'createdAt', 'completedAt',
]
const GENERATION_STATUSES = new Set(['reserved', 'running', 'succeeded', 'failed', 'outcome_unknown'])
const HASH_PATTERN = /^[0-9a-f]{64}$/u
const ITEM_ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/u
const hasOwn = (value, key) => Object.prototype.hasOwnProperty.call(value, key)

function invalidResponse() {
  return new ApiError({ code: 'invalid_response', message: '服务返回了无效响应' })
}

function validText(value, maximum) {
  if (typeof value !== 'string' || value.length === 0 || value !== value.trim()) return false
  try { return unicodeScalarLength(value) <= maximum } catch { return false }
}

function authorTextIssue(value, label) {
  if (typeof value !== 'string' || !value.trim()) return `请先补全“${label}”：填写有效文本。`
  try {
    if (unicodeScalarLength(value.trim()) > 4_000) return `“${label}”不能超过 4000 个字符。`
  } catch { return `“${label}”包含无效字符，请重新输入。` }
  return ''
}

// Mirrors backend/domain/bibles.py for author-entered payloads without normalizing them.
export function validateBiblePayload(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return { valid: false, message: '请先建立完整的创作圣经文档。' }
  }
  const expectedFields = BIBLE_AUTHOR_FIELDS.map(([field]) => field)
  if (Object.keys(value).length !== expectedFields.length || expectedFields.some(field => !hasOwn(value, field))) {
    return { valid: false, message: '创作圣经包含无法识别的字段，请刷新页面后重试。' }
  }
  for (const [field, label, type] of BIBLE_AUTHOR_FIELDS) {
    if (type === 'scalar') {
      const message = authorTextIssue(value[field], label)
      if (message) return { valid: false, field, message }
      continue
    }
    const items = value[field]
    if (!Array.isArray(items) || items.length < 1) return { valid: false, field, message: `请先补全“${label}”：至少填写 1 条有效内容。` }
    if (items.length > 20) return { valid: false, field, message: `“${label}”最多填写 20 条。` }
    const ids = new Set()
    for (let index = 0; index < items.length; index += 1) {
      const item = items[index]
      if (!item || typeof item !== 'object' || Array.isArray(item)
        || Object.keys(item).length !== 2 || !hasOwn(item, 'id') || !hasOwn(item, 'text')) {
        return { valid: false, field, message: `“${label}”第 ${index + 1} 条包含无法识别的字段，请删除后重新新增。` }
      }
      const id = typeof item?.id === 'string' ? item.id.trim() : ''
      if (!ITEM_ID_PATTERN.test(id)) return { valid: false, field, message: `“${label}”第 ${index + 1} 条的标识格式无效，请删除后重新新增。` }
      if (ids.has(id)) return { valid: false, field, message: `“${label}”中的标识不能重复，请删除重复条目。` }
      ids.add(id)
      const message = authorTextIssue(item?.text, `${label}第 ${index + 1} 条`)
      if (message) return { valid: false, field, message }
    }
  }
  return { valid: true, message: '' }
}

function strictProposalBible(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw invalidResponse()
  const result = {}
  for (const field of BIBLE_SCALAR_FIELDS) {
    if (!hasOwn(value, field) || !validText(value[field], 4_000)) throw invalidResponse()
    result[field] = value[field]
  }
  for (const field of BIBLE_ARRAY_FIELDS) {
    if (!hasOwn(value, field) || !Array.isArray(value[field]) || value[field].length < 1 || value[field].length > 20) throw invalidResponse()
    const ids = new Set()
    result[field] = value[field].map(item => {
      if (!item || typeof item !== 'object' || Array.isArray(item)
        || !hasOwn(item, 'id') || !hasOwn(item, 'text')
        || typeof item.id !== 'string' || !ITEM_ID_PATTERN.test(item.id)
        || !validText(item.text, 4_000) || ids.has(item.id)) throw invalidResponse()
      ids.add(item.id)
      return { id: item.id, text: item.text }
    })
  }
  return result
}

function publicProposalAttempt(value, expectedProjectId) {
  try {
    if (!value || typeof value !== 'object' || Array.isArray(value)
      || GENERATION_ATTEMPT_FIELDS.some(field => !hasOwn(value, field))) throw invalidResponse()
    const attempt = Object.fromEntries(GENERATION_ATTEMPT_FIELDS.map(field => [field, value[field]]))
    if (!validText(attempt.id, 64) || attempt.projectId !== expectedProjectId
      || !GENERATION_STATUSES.has(attempt.status)
      || !Number.isSafeInteger(attempt.attemptVersion) || attempt.attemptVersion < 1
      || !validText(attempt.providerId, 64) || !validText(attempt.modelNameSnapshot, 160)
      || typeof attempt.inputManifestHash !== 'string' || !HASH_PATTERN.test(attempt.inputManifestHash)
      || !Number.isSafeInteger(attempt.createdAt) || attempt.createdAt < 0) throw invalidResponse()
    const pending = attempt.status === 'reserved' || attempt.status === 'running'
    const succeeded = attempt.status === 'succeeded'
    const failed = attempt.status === 'failed' || attempt.status === 'outcome_unknown'
    if ((succeeded ? !(typeof attempt.resultHash === 'string' && HASH_PATTERN.test(attempt.resultHash)) : attempt.resultHash !== null)
      || (failed ? !validText(attempt.publicErrorCode, 64) : attempt.publicErrorCode !== null)
      || (pending ? attempt.completedAt !== null : !Number.isSafeInteger(attempt.completedAt) || attempt.completedAt < 0)) throw invalidResponse()
    const hasProposal = hasOwn(value, 'proposal')
    if (succeeded !== hasProposal) throw invalidResponse()
    if (succeeded) attempt.proposal = strictProposalBible(value.proposal)
    return publicGenerationAttempt(attempt)
  } catch (failure) {
    if (failure instanceof ApiError && failure.code === 'invalid_response') throw failure
    throw invalidResponse()
  }
}

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
  const result = {
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
  if (value.status === 'succeeded' && value.proposal != null) {
    result.proposal = publicBible(value.proposal)
  }
  return result
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
  const proposing = ref(false)
  const historyLoading = ref(false)
  const dirty = ref(false)
  const generationAttempt = shallowRef(null)
  const proposalAttempt = shallowRef(null)
  const readOnly = ref(false)
  const headHydrated = ref(false)
  const loadGuard = createLatestRequestGuard()
  const writeGuard = createLatestRequestGuard()
  const historyGuard = createLatestRequestGuard()
  const generationGuard = createLatestRequestGuard()
  const proposalGuard = createLatestRequestGuard()
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
      loadGuard.invalidate(); writeGuard.invalidate(); historyGuard.invalidate(); generationGuard.invalidate(); proposalGuard.invalidate()
      projectId.value = next; head.value = null; draft.value = null; history.value = []
      headHydrated.value = false
      historyNextBeforeRevision.value = null; historyDetail.value = null; generationAttempt.value = null; proposalAttempt.value = null; error.value = null
      conflict.value = null; dirty.value = false; loading.value = false; saving.value = false
      confirming.value = false; generating.value = false; proposing.value = false; historyLoading.value = false
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
    } else if (kind === 'propose') {
      if (draft.value?.canEdit !== true) throw denied('bible_edit_denied')
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

  async function propose(nextProjectId, command = {}) {
    const targetProject = enterProject(nextProjectId)
    const key = String(command.idempotencyKey || '')
    if (!key) throw new TypeError('idempotencyKey is required')
    assertWritable('propose')
    const scope = String(command.scope || '')
    if (scope !== 'whole' && (dirty.value || draft.value?.draft == null || Number(draft.value?.draftVersion || 0) < 1)) {
      throw denied(dirty.value ? 'bible_proposal_dirty' : 'bible_proposal_draft_missing')
    }
    const requestGeneration = proposalGuard.begin()
    const targetStateGeneration = stateGeneration
    proposing.value = true; error.value = null
    try {
      const response = await api.bible.propose(targetProject, {
        scope,
        authorInstructions: String(command.authorInstructions || ''),
        expectedDraftVersion: Number(draft.value?.draftVersion ?? 0),
        expectedHeadRevision: Number(head.value?.revision || 0),
        idempotencyKey: key,
      })
      const attempt = publicProposalAttempt(response?.attempt, targetProject)
      if (current(proposalGuard, requestGeneration, targetProject, targetStateGeneration)) {
        proposalAttempt.value = attempt
      }
      return attempt
    } catch (failure) {
      if (current(proposalGuard, requestGeneration, targetProject, targetStateGeneration)) {
        error.value = publicError(failure)
        if (Number(failure?.status) === 409) conflict.value = publicError(failure)
      }
      throw failure
    } finally {
      if (current(proposalGuard, requestGeneration, targetProject, targetStateGeneration)) {
        proposing.value = false
      }
    }
  }

  function clearProposal() {
    proposalGuard.invalidate()
    proposalAttempt.value = null
    proposing.value = false
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
    loading, saving, confirming, generating, proposing, historyLoading, dirty, readOnly, headHydrated,
    generationAttempt, proposalAttempt, baselineLocked, canEdit, canConfirm, reasons, load, edit, save, confirm,
    generate, propose, clearProposal, loadAttempt, loadHistory, loadHistoryDetail,
    setReadOnly, clearHistory,
  }
})
