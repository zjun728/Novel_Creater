import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import { reactive } from 'vue'

import { bibleReasonLabel, createBibleWorkspaceController } from '../../src/application/bible/bibleWorkspaceController.js'

const emptyBible = () => ({
  premiseAndPromise: '', powerOrProgressionSystem: '', protagonist: '', toneAndNarrativeBoundaries: '',
  worldRules: [], coreCast: [], factions: [], longTermConflicts: [], relationshipDynamics: [],
  continuityGuardrails: [], openDesignQuestions: [],
})
const bible = () => ({ ...emptyBible(), premiseAndPromise: 'promise', worldRules: [{ id: 'world-1', text: 'rule' }] })
const revision = number => ({ revision: number, bible: bible(), canClone: true })

function error(status, message = 'failed') { return Object.assign(new Error(message), { status }) }

function makeStore(overrides = {}) {
  const calls = { load: [], edit: [], save: [], confirm: [], clone: [], history: [], detail: [] }
  const state = reactive({
    draft: { draftVersion: 2, draft: bible(), canEdit: true, canConfirm: true, canClone: true, reasons: [] },
    head: revision(7), history: [revision(7)], historyNextBeforeRevision: 6, historyDetail: null,
    loading: false, saving: false, confirming: false, cloning: false, historyLoading: false,
    dirty: false, readOnly: false, canEdit: true, canConfirm: true, canClone: true, reasons: [],
    ...overrides,
  })
  return Object.assign(state, {
    calls,
    async load(projectId) { calls.load.push(projectId); return { draft: state.draft, head: state.head } },
    edit(value) { calls.edit.push(value); state.draft = { ...state.draft, draft: value }; state.dirty = true },
    async save(projectId, value) { calls.save.push([projectId, value]); state.dirty = false; return state.draft },
    async confirm(projectId, command) { calls.confirm.push([projectId, command]); state.draft = null; state.head = revision(8); return state.head },
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

test('every current backend Bible reason code has an intentional author-facing mapping', async () => {
  const backend = (await Promise.all(['bibles.py', 'contracts/history.py', 'contracts/preview.py'].map(path => readFile(new URL(`../../../backend/services/${path}`, import.meta.url), 'utf8')))).join('\n')
  const codes = ['selection_missing', 'seed_missing', 'contract_missing', 'contract_not_ready', 'contract_revision_replaced', 'contract_basis_invalid', 'contract_unavailable', 'selection_revision_changed', 'seed_identity_changed', 'seed_revision_changed', 'seed_generation_changed', 'contract_revision_changed', 'creation_contract_changed', 'style_contract_changed', 'bible_policy_changed', 'bible_head_changed', 'bible_revision_replaced', 'project_archived']
  for (const code of codes) { assert.match(backend, new RegExp(`['\"]${code}['\"]`)); assert.doesNotMatch(bibleReasonLabel(code), new RegExp(`（${code}）`)) }
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

test('state machine displays a head-only Bible read-only, clones its revision, and keeps archived heads unclonable', async () => {
  const headOnly = makeStore({ draft: { draftVersion: null, draft: null, status: 'missing', canEdit: true, canConfirm: false, reasons: [] }, head: revision(7) })
  const workspace = controller(headOnly); await workspace.hydrate()
  assert.deepEqual(workspace.working.value, bible()); assert.equal(workspace.editable.value, false); assert.equal(workspace.canSave.value, false)
  await workspace.clone(headOnly.head); assert.deepEqual(headOnly.calls.clone[0], ['project-1', { sourceRevision: 7 }])
  const archived = makeStore({ draft: null, head: { ...revision(8), lifecycle: 'archived', canClone: false }, canClone: false })
  const archivedWorkspace = controller(archived, { isArchived: () => true }); await archivedWorkspace.hydrate()
  assert.equal(await archivedWorkspace.clone(archived.head), undefined)
})

test('archived workspace keeps a superseded draft as its single displayed artifact when a head also exists', async () => {
  const archivedDraft = { draftVersion: 2, draftId: 'draft-archived', draft: { ...bible(), premiseAndPromise: 'ARCHIVED DRAFT' }, status: 'superseded', lifecycle: 'archived', canEdit: false, canConfirm: false, canClone: false, reasons: ['bible_head_changed'] }
  const archivedHead = { ...revision(8), bible: { ...bible(), premiseAndPromise: 'ARCHIVED HEAD' }, status: 'current', lifecycle: 'archived', canClone: false, reasons: ['project_archived'] }
  const store = makeStore({ draft: archivedDraft, head: archivedHead, canEdit: false, canConfirm: false, canClone: false })
  const workspace = controller(store, { isArchived: () => true }); await workspace.hydrate()
  assert.equal(workspace.working.value.premiseAndPromise, 'ARCHIVED DRAFT')
  assert.equal(workspace.activeStatus.value, 'superseded')
  assert.deepEqual(workspace.activeReasons.value, ['bible_head_changed'])
  assert.equal(workspace.editable.value, false); assert.equal(workspace.cloneSource.value, null)
})

test('superseded drafts are read-only and clone with sourceDraftId while confirmed output remains visible and focuses status', async () => {
  const store = makeStore({ draft: { draftVersion: 2, draftId: 'draft-2', draft: bible(), status: 'superseded', canEdit: false, canConfirm: false, canClone: true, reasons: [] } }); const events = []
  store.confirm = async () => { const result = { ...revision(8), bible: { ...bible(), protagonist: 'confirmed' } }; store.draft = null; store.head = result; return result }
  const workspace = controller(store, { focusStatus: () => events.push('status') }); await workspace.hydrate()
  assert.equal(workspace.editable.value, false); await workspace.clone(store.draft)
  assert.deepEqual(store.calls.clone[0], ['project-1', { sourceDraftId: 'draft-2' }])
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

test('history opens, loads a detail, appends a page, and can clone active or archived source revisions', async () => {
  const store = makeStore(); const workspace = controller(store)
  await workspace.openHistory(); await workspace.showHistoryDetail(7); await workspace.loadMoreHistory()
  assert.deepEqual(store.calls.history, [['project-1', { append: false }], ['project-1', { append: true, beforeRevision: 6 }]])
  assert.deepEqual(store.calls.detail, [['project-1', 7]])
  await workspace.clone(revision(7)); await workspace.clone({ ...revision(6), lifecycle: 'archived' })
  assert.deepEqual(store.calls.clone, [['project-1', { sourceRevision: 7 }], ['project-1', { sourceRevision: 6 }]])
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
  assert.deepEqual(workspace.reasonLabels.value, ['请选择种子后继续。', '请完成或重新签署创作契约。', '内容已过期，请调整未来设计。', '项目已归档，只能查阅。', '状态需重新核对（unknown_reason）'])
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
