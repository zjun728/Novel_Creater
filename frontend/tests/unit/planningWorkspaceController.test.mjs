import assert from 'node:assert/strict'
import test from 'node:test'

import { reactive } from 'vue'

import {
  createPlanningWorkspaceController,
  isCompletePlanningAggregate,
} from '../../src/application/planning/planningWorkspaceController.js'

const emptyContent = () => ({
  activeStoryBlockRef: null,
  volumes: [],
  plots: [],
  storyBlocks: [],
})

const completeContent = () => ({
  activeStoryBlockRef: 'block-1',
  volumes: [{
    id: 'volume-1',
    order: 1,
    title: '入世卷',
    coreChange: '主角从逃亡转为主动追查',
    mainPressure: '朝廷与宗门同时追索',
    ensembleFocus: ['沈砚', '陆昭'],
    forbiddenEvents: ['不得提前揭开典籍真相'],
    lifecycle: 'active',
  }],
  plots: [{
    id: 'plot-1',
    order: 1,
    title: '典籍暗线',
    plotType: 'main',
    storyQuestion: '残卷为何选择沈砚',
    futureDirection: '从县城追到京师',
    expectedPayoff: '揭露第一层目录',
    relatedCharacters: ['沈砚', '陆昭'],
    lifecycle: 'active',
  }],
  storyBlocks: [{
    id: 'block-1',
    order: 1,
    title: '夜入县衙',
    volumeRef: 'volume-1',
    plotRefs: ['plot-1'],
    lifecycle: 'active',
    stages: [{
      id: 'stage-1',
      order: 1,
      title: '潜入',
      lifecycle: 'active',
      sceneTasks: [{
        id: 'task-1',
        order: 1,
        task: '取得残卷',
        completionEvidence: '残卷到手',
        lifecycle: 'active',
      }],
    }],
  }],
})

function createStore({ content = emptyContent(), archived = false } = {}) {
  const calls = []
  return reactive({
    calls,
    projectId: 'project-1',
    state: {
      projectId: 'project-1',
      basisStatus: archived ? 'archived' : 'current',
      draft: {
        draftId: 'draft-1',
        draftRevision: 1,
        contentHash: 'a'.repeat(64),
        status: archived ? 'superseded' : 'active',
      },
      capabilities: {
        view: true,
        edit: !archived,
        confirm: !archived,
        generate: !archived,
      },
    },
    history: [],
    localContent: structuredClone(content),
    dirty: false,
    loading: false,
    saving: false,
    confirming: false,
    generating: false,
    reconciling: false,
    generationOutcomeUnknown: false,
    awaitingAuthoritativeReload: false,
    async ensureLoaded(projectId) { calls.push(['load', projectId]) },
    async createDraft(projectId, command) {
      calls.push(['create', projectId, command])
      this.state.draft = { draftId: 'draft-new', status: 'active' }
      this.localContent = emptyContent()
      return this.state.draft
    },
    editLocal(value) {
      const copy = JSON.parse(JSON.stringify(value))
      calls.push(['edit', copy])
      this.localContent = copy
      this.dirty = true
    },
    async saveDraft(command) {
      calls.push(['save', command])
      this.dirty = false
      return { draftId: 'draft-1' }
    },
    async confirmDraft(command) {
      calls.push(['confirm', command])
      return { revision: 1 }
    },
    async generateDraft(command) {
      calls.push(['generate', command])
      return { status: 'succeeded' }
    },
    async reconcileGeneration() {
      calls.push(['reconcile'])
      return { status: 'succeeded' }
    },
    discardLocal() {
      calls.push(['discard'])
      this.dirty = false
    },
  })
}

test('manual draft edits volumes and plots with stable keys and one local aggregate', () => {
  let sequence = 0
  const store = createStore()
  const controller = createPlanningWorkspaceController({
    store,
    projectId: () => 'project-1',
    keyFactory: () => `client-${++sequence}`,
  })

  controller.addVolume()
  controller.updateVolume('client-1', {
    title: '第一卷',
    coreChange: '主角真正入局',
  })
  controller.addPlot()
  controller.updatePlot('client-2', {
    title: '残卷来历',
    plotType: 'main',
  })

  assert.equal(store.localContent.volumes[0].clientNodeKey, 'client-1')
  assert.equal(store.localContent.volumes[0].title, '第一卷')
  assert.equal(store.localContent.plots[0].clientNodeKey, 'client-2')
  assert.equal(store.localContent.plots[0].plotType, 'main')
  assert.deepEqual(store.localContent.storyBlocks, [])
  assert.equal('plotRefs' in store.localContent.volumes[0], false)
  assert.equal('storyBlockRef' in store.localContent.plots[0], false)
})

test('local nodes undo by deletion while confirmed nodes retire and never reactivate', () => {
  const content = completeContent()
  content.volumes.push({
    clientNodeKey: 'local-volume',
    order: 2,
    title: '临时卷',
    lifecycle: 'active',
  })
  const store = createStore({ content })
  const controller = createPlanningWorkspaceController({
    store,
    projectId: () => 'project-1',
  })

  controller.removeVolume('local-volume')
  controller.removeVolume('volume-1')
  controller.restoreNode('volumes', 'volume-1')

  assert.equal(
    store.localContent.volumes.some(item => item.clientNodeKey === 'local-volume'),
    false,
  )
  assert.equal(store.localContent.volumes[0].lifecycle, 'retired')
})

test('reorder is deterministic and preserves node identity', () => {
  const content = emptyContent()
  content.plots = [
    { id: 'plot-a', order: 1, title: 'A', lifecycle: 'active' },
    { id: 'plot-b', order: 2, title: 'B', lifecycle: 'active' },
  ]
  const store = createStore({ content })
  const controller = createPlanningWorkspaceController({
    store,
    projectId: () => 'project-1',
  })

  controller.movePlot('plot-b', -1)

  assert.deepEqual(
    store.localContent.plots.map(item => [item.id, item.order]),
    [['plot-b', 1], ['plot-a', 2]],
  )
})

test('reorder swaps active slots only and leaves retired snapshots byte-for-byte unchanged', () => {
  const content = emptyContent()
  const retired = {
    id: 'plot-retired',
    order: 2,
    title: '旧线',
    plotType: 'other',
    storyQuestion: '旧问题',
    futureDirection: '',
    expectedPayoff: '',
    relatedCharacters: [],
    revision: 7,
    contentHash: 'c'.repeat(64),
    lifecycle: 'retired',
  }
  content.plots = [
    { id: 'plot-a', order: 1, title: 'A', lifecycle: 'active' },
    retired,
    { id: 'plot-b', order: 3, title: 'B', lifecycle: 'active' },
  ]
  const store = createStore({ content })
  const controller = createPlanningWorkspaceController({
    store,
    projectId: () => 'project-1',
  })
  const retiredSnapshot = structuredClone(retired)

  assert.equal(controller.movePlot('plot-retired', -1), false)
  assert.deepEqual(store.localContent.plots[1], retiredSnapshot)
  assert.equal(controller.movePlot('plot-b', -1), true)
  assert.deepEqual(
    store.localContent.plots.map(item => [item.id, item.order]),
    [['plot-b', 1], ['plot-retired', 2], ['plot-a', 3]],
  )
  assert.deepEqual(store.localContent.plots[1], retiredSnapshot)
})

test('a lone active node cannot cross retired nodes during reorder', () => {
  const content = emptyContent()
  content.volumes = [
    { id: 'volume-retired-a', order: 1, title: '旧一', lifecycle: 'retired' },
    { id: 'volume-active', order: 2, title: '现卷', lifecycle: 'active' },
    { id: 'volume-retired-b', order: 3, title: '旧二', lifecycle: 'retired' },
  ]
  const store = createStore({ content })
  const controller = createPlanningWorkspaceController({
    store,
    projectId: () => 'project-1',
  })
  const snapshot = JSON.parse(JSON.stringify(store.localContent.volumes))

  assert.equal(controller.moveVolume('volume-active', -1), false)
  assert.equal(controller.moveVolume('volume-active', 1), false)
  assert.deepEqual(store.localContent.volumes, snapshot)
})

test('volume and plot only drafts may save but cannot confirm until full aggregate exists', async () => {
  const content = emptyContent()
  content.volumes.push({ id: 'volume-1', order: 1, title: '第一卷', lifecycle: 'active' })
  content.plots.push({ id: 'plot-1', order: 1, title: '主线', lifecycle: 'active' })
  const store = createStore({ content })
  store.dirty = true
  const controller = createPlanningWorkspaceController({
    store,
    projectId: () => 'project-1',
    keyFactory: () => 'attempt-key',
  })

  assert.equal(isCompletePlanningAggregate(store.localContent), false)
  assert.equal(controller.canSave.value, true)
  assert.equal(controller.canConfirm.value, false)
  await controller.save()
  assert.deepEqual(store.calls.at(-1), ['save', { idempotencyKey: 'attempt-key' }])

  store.localContent = completeContent()
  assert.equal(isCompletePlanningAggregate(store.localContent), true)
  assert.equal(controller.canConfirm.value, true)
})

test('confirmation completeness follows the active block without over-gating other future blocks', () => {
  const content = completeContent()
  content.storyBlocks.push({
    id: 'block-later',
    order: 2,
    title: '后续故事块',
    volumeRef: 'volume-1',
    plotRefs: ['plot-1'],
    lifecycle: 'active',
    stages: [],
  })
  content.storyBlocks[0].stages.push({
    id: 'stage-empty',
    order: 2,
    title: '预留阶段',
    lifecycle: 'active',
    sceneTasks: [],
  })

  assert.equal(isCompletePlanningAggregate(content), true)
})

test('one controller owns draft creation save generate recovery and blocking confirmation', async () => {
  const store = createStore({ content: completeContent() })
  store.state.draft = null
  store.localContent = null
  const operations = []
  const operationStore = {
    start(value) {
      operations.push(['start', value])
      return 'confirm-operation'
    },
    finish(id) { operations.push(['finish', id]) },
  }
  let sequence = 0
  const controller = createPlanningWorkspaceController({
    store,
    projectId: () => 'project-1',
    keyFactory: () => `attempt-${++sequence}`,
    operationStore,
  })

  await controller.createManualDraft()
  store.localContent = completeContent()
  await controller.generate('强化群像冲突')
  await controller.reconcile()
  await controller.confirm()

  assert.deepEqual(store.calls.filter(call => call[0] !== 'load' && call[0] !== 'edit'), [
    ['create', 'project-1', { idempotencyKey: 'attempt-1' }],
    ['generate', { idempotencyKey: 'attempt-2', authorInstructions: '强化群像冲突' }],
    ['reconcile'],
    ['confirm', { idempotencyKey: 'attempt-3' }],
  ])
  assert.deepEqual(operations, [
    ['start', {
      label: '正在确认故事规划',
      detail: '确认会创建不可变规划修订',
      blocking: true,
    }],
    ['finish', 'confirm-operation'],
  ])
})

test('archived and superseded planning stay immutable while history is read-only', () => {
  const store = createStore({ content: completeContent(), archived: true })
  const controller = createPlanningWorkspaceController({
    store,
    projectId: () => 'project-1',
    isArchived: () => true,
  })

  assert.equal(controller.readOnly.value, true)
  assert.equal(controller.canSave.value, false)
  assert.equal(controller.canConfirm.value, false)
  assert.equal(controller.canGenerate.value, false)
  assert.equal(controller.addVolume(), false)
  assert.deepEqual(store.calls, [])
})

test('leave protection skips same-project planning tabs and prompts once elsewhere', () => {
  let prompts = 0
  const store = createStore()
  store.dirty = true
  const controller = createPlanningWorkspaceController({
    store,
    projectId: () => 'project-1',
    confirmLeave: () => {
      prompts += 1
      return false
    },
  })

  assert.equal(controller.requestRouteLeave({
    name: 'ProjectPlanningPlots',
    params: { projectId: 'project-1' },
  }), true)
  assert.equal(prompts, 0)
  assert.equal(controller.requestRouteLeave({
    name: 'ProjectOverview',
    params: { projectId: 'project-1' },
  }), false)
  assert.equal(prompts, 1)

  const event = {
    prevented: 0,
    preventDefault() { this.prevented += 1 },
    returnValue: undefined,
  }
  assert.equal(controller.beforeUnload(event), '')
  assert.equal(event.prevented, 1)
})

test('author instructions are project-local unsaved UI and reset only after entering another project', () => {
  let prompts = 0
  let allowLeave = false
  const store = createStore()
  const controller = createPlanningWorkspaceController({
    store,
    projectId: () => store.projectId,
    confirmLeave: () => {
      prompts += 1
      return allowLeave
    },
  })
  controller.enterProject('project-1')
  controller.authorInstructions.value = 'A 项目的补充要求'
  controller.notice.value = 'A notice'
  controller.historyOpen.value = true

  assert.equal(controller.requestRouteLeave({
    name: 'ProjectPlanningPlots',
    params: { projectId: 'project-1' },
  }), true)
  assert.equal(prompts, 0)
  assert.equal(controller.requestRouteLeave({
    name: 'ProjectPlanningVolumes',
    params: { projectId: 'project-2' },
  }), false)
  assert.equal(prompts, 1)
  assert.equal(controller.authorInstructions.value, 'A 项目的补充要求')
  assert.equal(controller.historyOpen.value, true)

  allowLeave = true
  assert.equal(controller.requestRouteLeave({
    name: 'ProjectPlanningVolumes',
    params: { projectId: 'project-2' },
  }), true)
  controller.enterProject('project-2')
  assert.equal(controller.authorInstructions.value, '')
  assert.equal(controller.notice.value, '')
  assert.equal(controller.historyOpen.value, false)
})

test('author instructions participate in beforeunload protection', () => {
  const store = createStore()
  const controller = createPlanningWorkspaceController({
    store,
    projectId: () => 'project-1',
  })
  controller.enterProject('project-1')
  controller.authorInstructions.value = '尚未用于生成'
  const event = {
    prevented: 0,
    preventDefault() { this.prevented += 1 },
    returnValue: undefined,
  }

  assert.equal(controller.beforeUnload(event), '')
  assert.equal(event.prevented, 1)
})

test('critical generation recovery state also protects leaving without reposting', async () => {
  let prompts = 0
  const store = createStore()
  store.generationOutcomeUnknown = true
  const controller = createPlanningWorkspaceController({
    store,
    projectId: () => 'project-1',
    confirmLeave: () => {
      prompts += 1
      return true
    },
  })

  assert.equal(controller.hasCriticalRecovery.value, true)
  assert.equal(controller.requestRouteLeave({
    name: 'ProjectOverview',
    params: { projectId: 'project-1' },
  }), true)
  await controller.reconcile()
  assert.deepEqual(store.calls, [['reconcile']])
  assert.equal(prompts, 1)
})
