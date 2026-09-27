import { computed, reactive, ref, shallowRef } from 'vue'

export const ISSUE_CATEGORIES = Object.freeze({ time: '时间', location: '位置', character_state: '人物状态', rule: '规则', fact: '已发生事实' })
export const ISSUE_SEVERITIES = Object.freeze({ low: '低', medium: '中', high: '高' })
export const ISSUE_STATUSES = Object.freeze({ pending: '待处理', resolved: '已解决', ignored: '已忽略' })
const COPY = Object.freeze({
  ContinuityIssueNotFound: '问题记录不存在或已被删除，请重新读取列表。',
  ContinuityIssueConflict: '记录已被其他操作更新。请读取最新记录，核对后再次保存；你的处理说明已保留。',
  ContinuityIssueSourceInvalid: '来源章节尚未定稿或不属于当前项目，请核对章节。',
  ContinuityIssueInvalid: '问题内容不符合要求，请检查必填项和字数。',
  ContinuityIssueUnavailable: '暂时无法读取问题记录，请重试。',
  ProjectArchived: '项目已归档，问题记录仅可查看。你的未保存内容仍保留在表单中。',
  ProjectNotFound: '项目不存在或已被删除。',
})
const emptyForm = () => ({ category: 'fact', severity: 'medium', description: '', suggestion: '', futureTarget: '', sourceChapterNumber: '', status: 'pending', resolutionNote: '' })
const signature = value => JSON.stringify(value)
const textLength = value => [...value].length
const validText = (value, optional = false) => (optional && value === null) || (typeof value === 'string' && value.trim().length > 0 && textLength(value) <= 4000)
const positive = value => Number.isSafeInteger(value) && value > 0

export function parseContinuityIssue(value, projectId) {
  if (!value || typeof value.id !== 'string' || !value.id || value.projectId !== projectId
    || !Object.hasOwn(ISSUE_CATEGORIES, value.category) || !Object.hasOwn(ISSUE_SEVERITIES, value.severity)
    || !Object.hasOwn(ISSUE_STATUSES, value.status) || !validText(value.description)
    || !validText(value.suggestion, true) || !validText(value.futureTarget, true) || !validText(value.resolutionNote, true)
    || (value.status !== 'pending' && value.resolutionNote === null)
    || !Number.isSafeInteger(value.createdAt) || value.createdAt < 0 || !Number.isSafeInteger(value.updatedAt) || value.updatedAt < value.createdAt
    || (value.lifecycle !== undefined && !['active', 'archived'].includes(value.lifecycle))) throw new Error('Invalid issue response')
  const source = [value.sourceChapterNumber, value.sourceFinalizationId, value.sourceCanonRevision]
  if (!source.every(item => item === null) && !(positive(source[0]) && typeof source[1] === 'string' && source[1] && positive(source[2]))) throw new Error('Invalid issue source')
  return value
}

function normalizedText(value, optional = false) {
  const text = String(value ?? '').trim()
  if (optional && !text) return null
  if (!validText(text)) throw new Error('请填写问题说明；问题说明、建议、未来处理目标及处理说明各不超过 4000 字。')
  return text
}

export function createContinuityIssuesController({ api, makeId = () => globalThis.crypto.randomUUID() }) {
  const state = shallowRef({ status: 'idle', data: null, message: '' })
  const form = reactive(emptyForm())
  const mode = ref('')
  const selected = shallowRef(null)
  const operation = ref('idle')
  const message = ref('')
  const lifecycle = ref(null)
  const savedSignature = ref('')
  const readOnly = computed(() => lifecycle.value !== 'active')
  const busy = computed(() => ['saving', 'opening', 'reloading'].includes(operation.value))
  const formLocked = computed(() => readOnly.value || busy.value || (mode.value === 'create' && Boolean(pendingCreate)))
  const dirty = computed(() => Boolean(mode.value && (signature(form) !== savedSignature.value || operation.value === 'uncertain')))
  let projectId = ''
  let generation = 0
  let listGeneration = 0
  let detailGeneration = 0
  let pendingCreate = null
  const canCloseArchivedUncertain = computed(() => lifecycle.value === 'archived' && operation.value === 'uncertain' && Boolean(pendingCreate))
  let filters = { offset: 0, limit: 50 }
  let listAbort = null
  let lifecycleBarrier = 0

  function applyLifecycle(value, startedAt) {
    if (!value || (value === 'active' && startedAt !== lifecycleBarrier)) return
    lifecycle.value = value
    // Reads already in flight cannot undo a newly confirmed write barrier.
    if (value !== 'active') lifecycleBarrier += 1
  }

  function resetEditor() {
    detailGeneration += 1
    mode.value = ''; selected.value = null; operation.value = 'idle'; message.value = ''
    pendingCreate = null; Object.assign(form, emptyForm()); savedSignature.value = signature(form)
  }
  function hydrateEditor(item, preserveDraft = false, startedAt = lifecycleBarrier) {
    selected.value = item
    applyLifecycle(item.lifecycle, startedAt)
    if (!preserveDraft) {
      Object.assign(form, emptyForm(), { status: item.status, resolutionNote: item.resolutionNote || '' })
      savedSignature.value = signature(form)
    }
  }
  async function load(id, query = {}) {
    if (id !== projectId) {
      generation += 1; projectId = id; lifecycle.value = null; lifecycleBarrier = 0; resetEditor()
    }
    const token = ++listGeneration
    listAbort?.abort(); listAbort = new AbortController()
    const offset = query.offset ?? 0
    if (!Number.isSafeInteger(offset) || offset < 0 || (query.status && !Object.hasOwn(ISSUE_STATUSES, query.status))) return false
    filters = { ...(query.status ? { status: query.status } : {}), offset, limit: 50 }
    const requested = { ...filters }
    const startedAt = lifecycleBarrier
    state.value = { status: 'loading', data: null, message: '' }
    try {
      const result = await api.continuityIssues.list(id, requested, { signal: listAbort.signal })
      if (token !== listGeneration || id !== projectId) return false
      if (result?.projectId !== id || !['active', 'archived'].includes(result.lifecycle) || !Array.isArray(result.items)
        || result.items.length > 50 || new Set(result.items.map(item => item.id)).size !== result.items.length
        || (result.nextOffset !== null && (!Number.isSafeInteger(result.nextOffset) || result.nextOffset <= offset))) throw new Error('Invalid issue list')
      result.items.forEach(item => { parseContinuityIssue(item, id); if (requested.status && item.status !== requested.status) throw new Error('Invalid issue filter') })
      applyLifecycle(result.lifecycle, startedAt)
      state.value = { status: 'ready', data: result, message: '' }
      return true
    } catch (failure) {
      if (token !== listGeneration || id !== projectId) return false
      if (failure?.code === 'ProjectArchived') applyLifecycle('archived', startedAt)
      if (failure?.code === 'ProjectNotFound') applyLifecycle('missing', startedAt)
      state.value = { status: 'error', data: null, message: COPY[failure?.code] || '问题列表暂时无法读取，请重试。' }
      return false
    }
  }
  function beginCreate(sourceChapterNumber = null) {
    if (readOnly.value || busy.value || pendingCreate) return false
    resetEditor(); mode.value = 'create'
    form.sourceChapterNumber = positive(sourceChapterNumber) ? String(sourceChapterNumber) : ''
    savedSignature.value = signature(form)
    return true
  }
  async function open(id) {
    if (busy.value || pendingCreate) return false
    resetEditor(); operation.value = 'opening'
    const token = ++detailGeneration; const scope = generation; const currentProject = projectId
    const startedAt = lifecycleBarrier
    try {
      const item = parseContinuityIssue(await api.continuityIssues.get(currentProject, id), currentProject)
      if (token !== detailGeneration || scope !== generation) return false
      if (item.id !== id) throw new Error('Invalid issue id')
      mode.value = 'edit'; hydrateEditor(item, false, startedAt); operation.value = 'idle'; return true
    } catch (failure) {
      if (token !== detailGeneration || scope !== generation) return false
      operation.value = 'error'; message.value = COPY[failure?.code] || '问题详情暂时无法读取，请重试。'; return false
    }
  }
  function createPayload() {
    if (!Object.hasOwn(ISSUE_CATEGORIES, form.category) || !Object.hasOwn(ISSUE_SEVERITIES, form.severity)) throw new Error('请选择问题类别与严重程度。')
    const source = String(form.sourceChapterNumber ?? '').trim()
    if (source && (!/^[1-9]\d*$/.test(source) || !positive(Number(source)))) throw new Error('来源章节必须是已定稿章节的正整数编号。')
    return {
      id: makeId(), category: form.category, severity: form.severity,
      description: normalizedText(form.description), suggestion: normalizedText(form.suggestion, true), futureTarget: normalizedText(form.futureTarget, true),
      sourceChapterNumber: source ? Number(source) : null,
    }
  }
  async function save() {
    if (!mode.value || readOnly.value || busy.value || operation.value === 'conflict' || operation.value === 'create-conflict') return false
    const creating = mode.value === 'create'
    let payload
    try {
      if (creating) { pendingCreate ||= createPayload(); payload = { ...pendingCreate } }
      else {
        if (!Object.hasOwn(ISSUE_STATUSES, form.status)) throw new Error('请选择有效的处理状态。')
        payload = { status: form.status, resolutionNote: normalizedText(form.resolutionNote, form.status === 'pending'), expectedUpdatedAt: selected.value.updatedAt }
      }
    } catch (failure) { message.value = failure.message; return false }
    const scope = generation; const currentProject = projectId; const id = selected.value?.id
    const startedAt = lifecycleBarrier
    operation.value = 'saving'; message.value = ''
    try {
      const result = creating ? await api.continuityIssues.create(currentProject, payload) : await api.continuityIssues.update(currentProject, id, payload)
      if (scope !== generation) return false
      const item = parseContinuityIssue(result, currentProject)
      if (item.id !== (creating ? payload.id : id)) throw new Error('Invalid saved issue id')
      if (creating && Object.keys(payload).some(key => item[key] !== payload[key])) throw new Error('Invalid created issue fields')
      if (!creating && (item.updatedAt <= payload.expectedUpdatedAt || item.status !== payload.status || item.resolutionNote !== payload.resolutionNote)) throw new Error('Invalid updated issue result')
      pendingCreate = null; mode.value = 'edit'; hydrateEditor(item, false, startedAt); operation.value = 'idle'
      message.value = creating ? '问题记录已保存。' : '处理结论已保存。'
      await load(currentProject, filters)
      return true
    } catch (failure) {
      if (scope !== generation) return false
      if (['ProjectArchived', 'ProjectNotFound'].includes(failure?.code)) {
        applyLifecycle(failure.code === 'ProjectArchived' ? 'archived' : 'missing', startedAt); pendingCreate = null; operation.value = 'error'
      } else if (creating && ['ContinuityIssueSourceInvalid', 'ContinuityIssueInvalid'].includes(failure?.code)) {
        pendingCreate = null; operation.value = 'error'
      } else if (creating && failure?.code === 'ContinuityIssueConflict') {
        operation.value = 'create-conflict'; pendingCreate = null
      } else if (creating) {
        operation.value = 'uncertain'
        message.value = '创建结果暂未确认。表单已锁定，请重试确认；会使用同一编号和原内容，不会重复创建。'
        return false
      } else if (['ContinuityIssueInvalid', 'ContinuityIssueNotFound'].includes(failure?.code)) operation.value = 'error'
      else operation.value = 'conflict'
      message.value = creating && failure?.code === 'ContinuityIssueConflict'
        ? '问题编号与已有记录冲突，请关闭表单后重新创建。'
        : COPY[failure?.code] || '保存结果暂未确认。请读取最新记录，核对后再保存；你的处理说明已保留。'
      return false
    }
  }
  async function reloadSelected() {
    if (!selected.value || busy.value) return false
    const scope = generation; const token = ++detailGeneration; const id = selected.value.id; const currentProject = projectId
    const startedAt = lifecycleBarrier
    const wasConflict = operation.value === 'conflict'; operation.value = 'reloading'; message.value = ''
    try {
      const item = parseContinuityIssue(await api.continuityIssues.get(currentProject, id), currentProject)
      if (scope !== generation || token !== detailGeneration) return false
      if (item.id !== id) throw new Error('Invalid refreshed issue id')
      hydrateEditor(item, true, startedAt); operation.value = 'idle'
      message.value = '已读取最新记录。请对照当前结论，确认你的处理说明后再保存。'; return true
    } catch (failure) {
      if (scope !== generation || token !== detailGeneration) return false
      operation.value = wasConflict ? 'conflict' : 'error'; message.value = COPY[failure?.code] || '最新记录暂时无法读取，请重试。'; return false
    }
  }
  function cancel() { if (busy.value || pendingCreate) return false; resetEditor(); return true }
  async function closeArchivedUncertain(confirmClose) {
    if (!canCloseArchivedUncertain.value) return false
    const scope = generation
    if (!await confirmClose() || scope !== generation || !canCloseArchivedUncertain.value) return false
    resetEditor()
    message.value = '未确认表单已关闭。问题可能已经保存，请先核对已有记录。'
    return true
  }
  async function confirmLeave(confirmDiscard) {
    if (busy.value) { message.value = '正在确认操作结果，请等待后再离开。'; return false }
    return !dirty.value || Boolean(await confirmDiscard(operation.value === 'uncertain'))
  }
  function beforeUnload(event) { if (dirty.value || busy.value) { event.preventDefault(); event.returnValue = '' } }
  function dispose() { generation += 1; listGeneration += 1; detailGeneration += 1; listAbort?.abort() }
  return { state, form, mode, selected, operation, message, lifecycle, readOnly, busy, formLocked, dirty, canCloseArchivedUncertain, load, beginCreate, open, save, reloadSelected, cancel, closeArchivedUncertain, confirmLeave, beforeUnload, dispose }
}
