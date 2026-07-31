import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import { reactive } from 'vue'

import { bibleReasonLabel, createBibleWorkspaceController } from '../../src/application/bible/bibleWorkspaceController.js'

test('Bible workspace controller has no clone command branch', async () => {
  const source = await readFile(new URL('../../src/application/bible/bibleWorkspaceController.js', import.meta.url), 'utf8')
  assert.doesNotMatch(source, /cloneRevision|store\.clone|cloneSource/)
})

const emptyBible = () => ({
  premiseAndPromise: '', powerOrProgressionSystem: '', protagonist: '', toneAndNarrativeBoundaries: '',
  worldRules: [], coreCast: [], factions: [], longTermConflicts: [], relationshipDynamics: [],
  continuityGuardrails: [], openDesignQuestions: [],
})
const bible = () => ({ ...emptyBible(), premiseAndPromise: 'promise', worldRules: [{ id: 'world-1', text: 'rule' }] })
const revision = number => ({ revision: number, bible: bible(), canClone: true })

function error(status, message = 'failed') { return Object.assign(new Error(message), { status }) }
function deferred() {
  let resolve; let reject
  const promise = new Promise((onResolve, onReject) => { resolve = onResolve; reject = onReject })
  return { promise, resolve, reject }
}

function makeStore(overrides = {}) {
  const calls = { load: [], edit: [], save: [], confirm: [], generate: [], clone: [], history: [], detail: [] }
  const state = reactive({
    draft: { draftVersion: 2, draft: bible(), canEdit: true, canConfirm: true, canClone: true, reasons: [] },
    head: revision(7), history: [revision(7)], historyNextBeforeRevision: 6, historyDetail: null,
    loading: false, saving: false, confirming: false, generating: false, cloning: false, historyLoading: false,
    generationAttempt: null, baselineLocked: false,
    dirty: false, readOnly: false, canEdit: true, canConfirm: true, canClone: true, reasons: [],
    ...overrides,
  })
  return Object.assign(state, {
    calls,
    async load(projectId) { calls.load.push(projectId); return { draft: state.draft, head: state.head } },
    edit(value) { calls.edit.push(value); state.draft = { ...state.draft, draft: value }; state.dirty = true },
    async save(projectId, value) { calls.save.push([projectId, value]); state.dirty = false; return state.draft },
    async confirm(projectId, command) { calls.confirm.push([projectId, command]); state.draft = null; state.head = revision(8); return state.head },
    async generate(projectId, command) {
      calls.generate.push([projectId, command])
      state.generationAttempt = { id: `attempt-${calls.generate.length}`, status: 'succeeded' }
      state.draft = { ...state.draft, draftVersion: state.draft.draftVersion + 1, draft: { ...bible(), premiseAndPromise: 'generated' } }
      return state.generationAttempt
    },
    async clone(projectId, source) { calls.clone.push([projectId, source]); state.draft = { draftVersion: 3, draft: bible(), canEdit: true, canConfirm: true, canClone: true, reasons: [] }; return state.draft },
    async loadHistory(projectId, params) { calls.history.push([projectId, params]); return { items: state.history, nextBeforeRevision: state.historyNextBeforeRevision } },
    async loadHistoryDetail(projectId, itemRevision) { calls.detail.push([projectId, itemRevision]); state.historyDetail = revision(itemRevision); return state.historyDetail },
  })
}

function controller(store, options = {}) {
  return createBibleWorkspaceController({
    store, projectId: () => 'project-1', isArchived: () => false,
    keyFactory: (() => { let n = 0; return () => `key-${++n}` })(), ...options,
  })
}

test('the public frontend Bible reason contract maps every supported code intentionally', () => {
  const codes = ['selection_missing', 'seed_missing', 'contract_missing', 'contract_not_ready', 'contract_revision_replaced', 'contract_basis_invalid', 'contract_unavailable', 'selection_revision_changed', 'seed_identity_changed', 'seed_revision_changed', 'seed_generation_changed', 'contract_revision_changed', 'creation_contract_changed', 'style_contract_changed', 'bible_policy_changed', 'bible_head_changed', 'bible_revision_replaced', 'project_archived']
  for (const code of codes) assert.doesNotMatch(bibleReasonLabel(code), new RegExp(`（${code}）`))
})

test('late project operations cannot publish working state, errors, focus, or dialogs into a newer hydrate generation', async () => {
  const saveA = deferred(); const historyA = deferred(); let currentProject = 'A'; const focus = []
  const store = makeStore()
  store.load = async project => {
    store.calls.load.push(project)
    store.draft = { draftVersion: 1, draft: { ...bible(), premiseAndPromise: `${project} BODY` }, canEdit: true, canConfirm: true, canClone: true, reasons: [] }
    store.head = { ...revision(1), bible: { ...bible(), premiseAndPromise: `${project} HEAD` } }
  }
  store.save = async project => project === 'A' ? saveA.promise : store.draft
  store.loadHistory = async project => project === 'A' ? historyA.promise : { items: [], nextBeforeRevision: null }
  const workspace = createBibleWorkspaceController({ store, projectId: () => currentProject, focusError: () => focus.push('error'), keyFactory: () => 'key' })
  await workspace.hydrate(); workspace.edit({ ...workspace.working.value, premiseAndPromise: 'A LOCAL' })
  const oldSave = workspace.save(); const oldHistory = workspace.openHistory()
  currentProject = 'B'; await workspace.hydrate()
  saveA.resolve({ draft: { ...bible(), premiseAndPromise: 'A SAVED' } }); historyA.reject(error(500, 'A raw secret'))
  await oldSave; await oldHistory
  assert.equal(workspace.working.value.premiseAndPromise, 'B BODY')
  assert.equal(workspace.errorSummary.value, null); assert.equal(workspace.recoveryCommand.value, null); assert.deepEqual(focus, []); assert.equal(workspace.historyOpen.value, false)
})

for (const confirmOutcome of ['success', 'failure']) {
  test(`late confirmation ${confirmOutcome} stays fenced from the newer project`, async () => {
    const confirmA = deferred(); let currentProject = 'A'; const focus = []
    const store = makeStore()
    store.load = async project => {
      store.draft = { draftVersion: 1, draft: { ...bible(), premiseAndPromise: `${project} BODY` }, canEdit: true, canConfirm: true, canClone: true, reasons: [] }
      store.head = revision(1)
    }
    store.confirm = async project => project === 'A' ? confirmA.promise : revision(2)
    const workspace = createBibleWorkspaceController({ store, projectId: () => currentProject, focusError: () => focus.push('error'), focusStatus: () => focus.push('status'), keyFactory: () => 'key' })
    await workspace.hydrate(); workspace.openConfirm()
    const oldConfirm = workspace.confirm()
    currentProject = 'B'; await workspace.hydrate()
    if (confirmOutcome === 'success') confirmA.resolve(revision(2))
    else confirmA.reject(error(503, 'late confirm raw secret'))
    await oldConfirm
    assert.equal(workspace.working.value.premiseAndPromise, 'B BODY')
    assert.equal(workspace.errorSummary.value, null); assert.equal(workspace.recoveryCommand.value, null)
    assert.equal(workspace.confirmOpen.value, false); assert.deepEqual(focus, [])
  })
}

test('pending writes block route and unload leave even when the draft is clean', async () => {
  const store = makeStore({ saving: true, dirty: false }); const workspace = controller(store, { confirmLeave: () => true })
  assert.equal(workspace.requestLeave(), false)
  const event = { prevented: false, preventDefault() { this.prevented = true }, returnValue: undefined }
  assert.equal(workspace.beforeUnload(event), ''); assert.equal(event.prevented, true)
})

test('a failed save retries the current working Bible without hydrating or retaining raw failure data', async () => {
  const store = makeStore(); const saved = []; let saves = 0
  store.save = async (_project, value) => {
    saved.push(value)
    if (++saves === 1) throw Object.assign(new Error('raw provider key secret'), { status: 503, body: { secret: true } })
    store.dirty = false
    return { ...store.draft, draft: value }
  }
  const workspace = controller(store); await workspace.hydrate()
  workspace.edit({ ...workspace.working.value, premiseAndPromise: 'LOCAL AFTER 503' })
  await assert.rejects(workspace.save())
  assert.equal(store.dirty, true); assert.equal(store.calls.load.length, 1)
  assert.deepEqual(workspace.recoveryCommand.value, { type: 'save', project: 'project-1', generation: 1 })
  assert.doesNotMatch(JSON.stringify(workspace.recoveryCommand.value), /provider|key|secret/i)
  await workspace.retryFailure()
  assert.equal(store.calls.load.length, 1); assert.equal(saved.length, 2)
  assert.equal(saved[1].premiseAndPromise, 'LOCAL AFTER 503')
})

test('a failed confirmation retries with the controller retained idempotency key', async () => {
  const store = makeStore(); const keys = []; let confirms = 0
  store.confirm = async (_project, command) => {
    keys.push(command.idempotencyKey)
    if (++confirms === 1) throw error(503, 'outcome unknown')
    store.draft = null; store.head = revision(8)
    return store.head
  }
  const workspace = controller(store); await workspace.hydrate(); workspace.openConfirm()
  await assert.rejects(workspace.confirm())
  assert.equal(workspace.confirmOpen.value, true); assert.equal(workspace.recoveryCommand.value.type, 'confirm')
  await workspace.retryFailure()
  assert.equal(keys.length, 2); assert.equal(keys[0], keys[1]); assert.equal(workspace.confirmOpen.value, false)
})

test('load, history list, and history detail failures retry only their corresponding reads', async () => {
  const store = makeStore(); let loads = 0; let lists = 0; let details = 0
  store.load = async project => {
    store.calls.load.push(project)
    if (++loads === 1) throw error(503, 'load failed')
  }
  store.loadHistory = async (project, params) => {
    store.calls.history.push([project, params])
    if (++lists === 1) throw error(503, 'history failed')
    return { items: [], nextBeforeRevision: null }
  }
  store.loadHistoryDetail = async (project, itemRevision) => {
    store.calls.detail.push([project, itemRevision])
    if (++details === 1) throw error(503, 'detail failed')
    return revision(itemRevision)
  }
  const workspace = controller(store)
  await assert.rejects(workspace.hydrate()); assert.equal(workspace.recoveryCommand.value.type, 'hydrate')
  await workspace.retryFailure(); assert.equal(store.calls.load.length, 2)
  await assert.rejects(workspace.openHistory()); assert.equal(workspace.recoveryCommand.value.type, 'history')
  await workspace.retryFailure(); assert.equal(store.calls.history.length, 2)
  await assert.rejects(workspace.showHistoryDetail(7))
  assert.deepEqual(workspace.recoveryCommand.value, { type: 'historyDetail', project: 'project-1', generation: 2, revision: 7 })
  await workspace.retryFailure(); assert.deepEqual(store.calls.detail, [['project-1', 7], ['project-1', 7]])
})

test('state machine creates an empty first Bible only without a head, and never writes on hydrate', async () => {
  const store = makeStore({ draft: { draftVersion: null, draft: null, draftId: null, status: 'missing', canEdit: true, canConfirm: false, reasons: [] }, head: { revision: 0, bible: null, canClone: false } })
  const workspace = controller(store)
  await workspace.hydrate()
  assert.deepEqual(workspace.working.value, emptyBible())
  assert.equal(store.calls.edit.length, 0)
  assert.equal(store.calls.save.length, 0)
  assert.equal(workspace.editable.value, true)
  workspace.edit({ ...workspace.working.value, premiseAndPromise: 'first' })
  assert.equal(workspace.canSave.value, true)
})

test('active status and reasons are selected from the artifact being displayed', async () => {
  const store = makeStore({ draft: { draftVersion: null, draft: null, status: 'missing', canEdit: true, canConfirm: false, reasons: [] }, head: { ...revision(7), status: 'current', reasons: ['bible_head_changed'] }, reasons: [] })
  const workspace = controller(store); await workspace.hydrate()
  assert.equal(workspace.activeStatus.value, 'current')
  assert.deepEqual(workspace.activeReasons.value, ['bible_head_changed'])
  store.head = { ...store.head, status: 'superseded', reasons: ['contract_unavailable', 'contract_basis_invalid'] }
  assert.equal(workspace.activeStatus.value, 'superseded')
  assert.deepEqual(workspace.reasonLabels.value, ['请完成或重新签署创作契约。', '请完成或重新签署创作契约。'])
})

test('state machine displays a head-only Bible as a read-only permanent baseline', async () => {
  const headOnly = makeStore({ draft: { draftVersion: null, draft: null, status: 'missing', canEdit: true, canConfirm: false, reasons: [] }, head: revision(7) })
  const workspace = controller(headOnly); await workspace.hydrate()
  assert.deepEqual(workspace.working.value, bible()); assert.equal(workspace.editable.value, false); assert.equal(workspace.canSave.value, false)
  const archived = makeStore({ draft: null, head: { ...revision(8), lifecycle: 'archived', canClone: false }, canClone: false })
  const archivedWorkspace = controller(archived, { isArchived: () => true }); await archivedWorkspace.hydrate()
  assert.equal(archivedWorkspace.editable.value, false)
})

test('a locked baseline shows its confirmed head ahead of an archived superseded draft', async () => {
  const archivedDraft = { draftVersion: 2, draftId: 'draft-archived', draft: { ...bible(), premiseAndPromise: 'ARCHIVED DRAFT' }, status: 'superseded', lifecycle: 'archived', canEdit: false, canConfirm: false, canClone: false, reasons: ['bible_head_changed'] }
  const archivedHead = { ...revision(8), bible: { ...bible(), premiseAndPromise: 'ARCHIVED HEAD' }, status: 'current', lifecycle: 'archived', canClone: false, reasons: ['project_archived'] }
  const store = makeStore({ baselineLocked: true, draft: archivedDraft, head: archivedHead, canEdit: false, canConfirm: false, canClone: false })
  const workspace = controller(store, { isArchived: () => true }); await workspace.hydrate()
  assert.equal(workspace.mode.value, 'head')
  assert.equal(workspace.working.value.premiseAndPromise, 'ARCHIVED HEAD')
  assert.equal(workspace.activeStatus.value, 'current')
  assert.deepEqual(workspace.activeReasons.value, ['project_archived'])
  assert.equal(workspace.editable.value, false)
})

test('superseded drafts are read-only while confirmed output remains visible and focuses status', async () => {
  const store = makeStore({ draft: { draftVersion: 2, draftId: 'draft-2', draft: bible(), status: 'superseded', canEdit: false, canConfirm: false, canClone: true, reasons: [] } }); const events = []
  store.confirm = async () => { const result = { ...revision(8), bible: { ...bible(), protagonist: 'confirmed' } }; store.draft = null; store.head = result; return result }
  const workspace = controller(store, { focusStatus: () => events.push('status') }); await workspace.hydrate()
  assert.equal(workspace.editable.value, false)
  store.draft = { draftVersion: 3, draft: bible(), canEdit: true, canConfirm: true, canClone: true, reasons: [] }; store.canConfirm = true
  await workspace.hydrate(); await workspace.confirm(); await Promise.resolve()
  assert.equal(workspace.working.value.protagonist, 'confirmed'); assert.deepEqual(events, ['status'])
})

test('editing stays local until one explicit save and dirty disables confirmation', async () => {
  const store = makeStore(); const workspace = controller(store)
  await workspace.hydrate()
  const changed = { ...workspace.working.value, protagonist: 'heroine' }
  workspace.edit(changed)
  assert.equal(store.calls.edit.length, 1)
  assert.equal(store.calls.save.length, 0)
  assert.equal(workspace.canConfirm.value, false)
  await workspace.save()
  assert.equal(store.calls.save.length, 1)
  assert.equal(store.calls.save[0][0], 'project-1')
})

test('opens confirmation only for a saved full preview and restores trigger focus', async () => {
  const store = makeStore(); const events = []
  const workspace = controller(store, { focusConfirm: () => events.push('dialog'), focusTrigger: () => events.push('trigger') })
  await workspace.hydrate()
  const trigger = { focus: () => events.push('element') }
  workspace.openConfirm(trigger)
  assert.equal(workspace.confirmOpen.value, true)
  assert.deepEqual(workspace.confirmPreview.value, bible())
  await Promise.resolve()
  workspace.closeConfirm()
  await Promise.resolve()
  assert.deepEqual(events, ['dialog', 'trigger', 'element'])
})

test('confirmation reuses an attempt key for outcome-unknown failures but creates a new one after 4xx', async () => {
  const store = makeStore(); const workspace = controller(store)
  await workspace.hydrate()
  store.confirm = async (projectId, command) => { store.calls.confirm.push([projectId, command]); throw error(503) }
  await assert.rejects(workspace.confirm()); await assert.rejects(workspace.confirm())
  assert.equal(store.calls.confirm.length, 2)
  assert.equal(store.calls.confirm[0][1].idempotencyKey, store.calls.confirm[1][1].idempotencyKey)
  store.confirm = async (projectId, command) => { store.calls.confirm.push([projectId, command]); throw error(409) }
  await assert.rejects(workspace.confirm()); await assert.rejects(workspace.confirm())
  assert.notEqual(store.calls.confirm[2][1].idempotencyKey, store.calls.confirm[3][1].idempotencyKey)
})

test('history opens, loads a detail, and appends a read-only page', async () => {
  const store = makeStore(); const workspace = controller(store)
  await workspace.openHistory(); await workspace.showHistoryDetail(7); await workspace.loadMoreHistory()
  assert.deepEqual(store.calls.history, [['project-1', { append: false }], ['project-1', { append: true, beforeRevision: 6 }]])
  assert.deepEqual(store.calls.detail, [['project-1', 7]])
})

test('busy state blocks duplicate actions, every async action focuses errors, and reason labels are safe categories', async () => {
  const reasons = ['selection_missing', 'contract_not_ready', 'bible_head_changed', 'project_archived', 'unknown_reason']
  const store = makeStore({ saving: true, reasons, draft: { draftVersion: 2, draft: bible(), canEdit: true, canConfirm: true, canClone: true, reasons } }); const focused = []
  const workspace = controller(store, { focusError: () => focused.push('error') })
  await workspace.hydrate()
  assert.equal(workspace.busy.value, true)
  assert.equal(await workspace.save(), undefined)
  store.saving = false; store.dirty = true; store.save = async () => { throw error(500, 'save bad') }
  await assert.rejects(workspace.save())
  await Promise.resolve()
  assert.equal(focused[0], 'error')
  assert.deepEqual(workspace.reasonLabels.value, ['请选择种子后继续。', '请完成或重新签署创作契约。', '内容已固定为项目永久基线，请查看历史记录。', '项目已归档，只能查阅。', '状态需重新核对（unknown_reason）'])
})

test('AI Not Ready does not override manual permissions and leave protection handles beforeunload', async () => {
  const store = makeStore({ canEdit: true, canConfirm: true }); const workspace = controller(store, { confirmLeave: () => false })
  await workspace.hydrate()
  assert.equal(workspace.canSave.value, false)
  assert.equal(workspace.canConfirm.value, true)
  workspace.edit({ ...workspace.working.value, protagonist: 'changed' })
  assert.equal(workspace.canSave.value, true)
  assert.equal(workspace.canConfirm.value, false)
  const event = { prevented: false, preventDefault() { this.prevented = true }, returnValue: undefined }
  assert.equal(workspace.beforeUnload(event), '')
  assert.equal(event.prevented, true)
  assert.equal(workspace.confirmLeave(), false)
})

test('generation requires only planning readiness, a clean editable draft, and no busy work', async () => {
  let planningReady = false
  const store = makeStore()
  const workspace = controller(store, { planningReady: () => planningReady })
  await workspace.hydrate()
  assert.equal(workspace.canGenerate.value, false)
  assert.equal(workspace.editable.value, true)
  assert.equal(workspace.canSave.value, false)

  planningReady = true
  assert.equal(workspace.canGenerate.value, true)
  store.dirty = true
  assert.equal(workspace.canGenerate.value, false)
  assert.equal(workspace.generationDisabledReason.value, '请先保存本地编辑，再使用 AI 生成。')
  store.dirty = false
  store.generating = true
  assert.equal(workspace.busy.value, true)
  assert.equal(workspace.canGenerate.value, false)
  store.generating = false
  assert.equal(workspace.canGenerate.value, true)
})

test('each explicit generation gets a fresh key and outcome unknown is never auto-retried', async () => {
  const store = makeStore(); let calls = 0
  store.generate = async (projectId, command) => {
    store.calls.generate.push([projectId, command])
    calls += 1
    if (calls === 1) return { id: 'attempt-1', status: 'outcome_unknown', publicErrorCode: 'BibleGenerationRetryable' }
    store.draft = { ...store.draft, draftVersion: 3, draft: { ...bible(), premiseAndPromise: 'GENERATED AUTHORITATIVE' } }
    return { id: 'attempt-2', status: 'succeeded' }
  }
  const workspace = controller(store, { planningReady: () => true })
  await workspace.hydrate()

  const unknown = await workspace.generate('第一次要求')
  assert.equal(unknown.status, 'outcome_unknown')
  assert.equal(workspace.recoveryCommand.value.type, 'reconcile')
  assert.equal(
    workspace.errorSummary.value.message,
    '结果尚未确认，请先重新核对',
  )
  assert.equal(store.calls.generate.length, 1)
  await workspace.retryFailure()
  assert.equal(store.calls.generate.length, 1)
  assert.equal(store.calls.load.length, 2)

  const succeeded = await workspace.generate('第二次要求')
  assert.equal(succeeded.status, 'succeeded')
  assert.equal(workspace.working.value.premiseAndPromise, 'GENERATED AUTHORITATIVE')
  assert.notEqual(
    store.calls.generate[0][1].idempotencyKey,
    store.calls.generate[1][1].idempotencyKey,
  )
  assert.deepEqual(
    store.calls.generate.map(value => value[1].authorInstructions),
    ['第一次要求', '第二次要求'],
  )
})

test('late generation completion cannot publish focus or working state into a new project', async () => {
  const pending = deferred(); let currentProject = 'A'; const focused = []
  const store = makeStore()
  store.load = async project => {
    store.calls.load.push(project)
    store.draft = { draftVersion: 1, draft: { ...bible(), premiseAndPromise: `${project} BODY` }, canEdit: true, canConfirm: true, canClone: true, reasons: [] }
    store.head = revision(1)
  }
  store.generate = async project => project === 'A' ? pending.promise : { status: 'succeeded' }
  const workspace = createBibleWorkspaceController({
    store,
    projectId: () => currentProject,
    planningReady: () => true,
    focusError: () => focused.push('error'),
    focusStatus: () => focused.push('status'),
    keyFactory: () => 'generation-key',
  })
  await workspace.hydrate()
  const old = workspace.generate('')
  currentProject = 'B'
  await workspace.hydrate()
  pending.resolve({ status: 'succeeded' })
  await old
  assert.equal(workspace.working.value.premiseAndPromise, 'B BODY')
  assert.deepEqual(focused, [])
  assert.equal(workspace.errorSummary.value, null)
})
