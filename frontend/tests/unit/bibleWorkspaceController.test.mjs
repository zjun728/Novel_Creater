import assert from 'node:assert/strict'
import test from 'node:test'
import { reactive } from 'vue'

import { createBibleWorkspaceController } from '../../src/application/bible/bibleWorkspaceController.js'

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

test('hydrates an editable missing draft to the full 11-field shape without writing', async () => {
  const store = makeStore({ draft: { draftVersion: 2, draft: null, canEdit: true, canConfirm: false, reasons: [] } })
  const workspace = controller(store)
  await workspace.hydrate()
  assert.deepEqual(workspace.working.value, emptyBible())
  assert.equal(store.calls.edit.length, 0)
  assert.equal(store.calls.save.length, 0)
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

test('busy state blocks duplicate actions, errors focus the summary, and reason labels are human readable', async () => {
  const store = makeStore({ saving: true, reasons: ['planning_not_ready', 'unknown_reason'] }); const focused = []
  const workspace = controller(store, { focusError: () => focused.push('error') })
  await workspace.hydrate()
  assert.equal(workspace.busy.value, true)
  assert.equal(await workspace.save(), undefined)
  store.saving = false; store.dirty = true; store.save = async () => { throw error(500, 'save bad') }
  await assert.rejects(workspace.save())
  await Promise.resolve()
  assert.equal(focused[0], 'error')
  assert.deepEqual(workspace.reasonLabels.value, ['规划尚未就绪，暂不能确认。', 'unknown_reason'])
})

test('planning not ready does not override manual save/confirm permissions and leave protection handles beforeunload', async () => {
  const store = makeStore({ reasons: ['planning_not_ready'], canEdit: true, canConfirm: true }); const workspace = controller(store, { confirmLeave: () => false })
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
