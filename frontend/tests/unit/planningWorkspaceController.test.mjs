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
    blockGoal: '在追兵抵达前取得残卷',
    volumeRef: 'volume-1',
    plotRefs: ['plot-1'],
    lifecycle: 'active',
    stages: [{
      id: 'stage-1',
      order: 1,
      title: '潜入',
      purpose: '进入县衙密库',
      dramaticQuestion: '沈砚能否避开巡夜守卫',
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

function contentWithLocalTask() {
  const content = completeContent()
  content.storyBlocks[0].stages[0].sceneTasks.push({
    clientNodeKey: 'task-local',
    order: 2,
    task: '尚未保存的场景任务',
    completionEvidence: '本地证据',
    lifecycle: 'active',
  })
  return content
}

function contentWithLocalBlock() {
  const content = completeContent()
  content.storyBlocks.push({
    clientNodeKey: 'block-local',
    order: 2,
    title: '尚未保存的故事块',
    volumeRef: '',
    plotRefs: [],
    lifecycle: 'active',
    stages: [],
  })
  return content
}

function deferred() {
  let resolve
  let reject
  const promise = new Promise((onResolve, onReject) => {
    resolve = onResolve
    reject = onReject
  })
  return { promise, resolve, reject }
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
  const laterBlock = {
    id: 'block-later',
    order: 2,
    title: '后续故事块',
    volumeRef: 'volume-1',
    plotRefs: ['plot-1'],
    lifecycle: 'active',
    stages: [],
  }
  laterBlock.stages.push({
    id: 'stage-empty',
    order: 1,
    title: '预留阶段',
    lifecycle: 'active',
    sceneTasks: [],
  })
  content.storyBlocks.push(laterBlock)

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

test('successful save checkpoints local deletion undo while failed save preserves it', async () => {
  const successStore = createStore({ content: contentWithLocalTask() })
  const successController = createPlanningWorkspaceController({
    store: successStore,
    projectId: () => 'project-1',
    keyFactory: () => 'save-success',
  })
  assert.equal(
    successController.removeSceneTask('block-1', 'stage-1', 'task-local'),
    true,
  )
  assert.equal(successController.canUndoStoryBlockEdit.value, true)

  await successController.save()

  assert.equal(successController.canUndoStoryBlockEdit.value, false)
  assert.equal(successController.undoStoryBlockEdit(), false)

  const failureStore = createStore({ content: contentWithLocalTask() })
  failureStore.saveDraft = async () => {
    throw new Error('save failed')
  }
  const failureController = createPlanningWorkspaceController({
    store: failureStore,
    projectId: () => 'project-1',
    keyFactory: () => 'save-failure',
  })
  failureController.removeSceneTask('block-1', 'stage-1', 'task-local')

  await assert.rejects(failureController.save(), /save failed/)

  assert.equal(failureController.canUndoStoryBlockEdit.value, true)
  assert.equal(failureController.undoStoryBlockEdit(), true)
})

test('AI authoritative replacement and successful reconcile checkpoint the newest undo', async () => {
  let key = 0
  const store = createStore({ content: contentWithLocalTask() })
  const controller = createPlanningWorkspaceController({
    store,
    projectId: () => 'project-1',
    keyFactory: () => `checkpoint-${++key}`,
  })
  controller.removeSceneTask('block-1', 'stage-1', 'task-local')
  await controller.save()
  assert.equal(controller.canUndoStoryBlockEdit.value, false)

  controller.addSceneTask('block-1', 'stage-1')
  const generatedTask = store.localContent.storyBlocks[0]
    .stages[0].sceneTasks.at(-1).clientNodeKey
  controller.removeSceneTask('block-1', 'stage-1', generatedTask)
  store.dirty = false
  assert.equal(controller.canUndoStoryBlockEdit.value, true)
  store.generateDraft = async command => {
    store.calls.push(['generate-authority', command])
    store.localContent = completeContent()
    return { status: 'succeeded' }
  }

  await controller.generate('权威替换')

  assert.equal(controller.canUndoStoryBlockEdit.value, false)
  assert.equal(controller.undoStoryBlockEdit(), false)
  assert.equal(
    store.localContent.storyBlocks[0].stages[0].sceneTasks
      .some(task => task.clientNodeKey === generatedTask),
    false,
  )

  controller.addSceneTask('block-1', 'stage-1')
  const reconciledTask = store.localContent.storyBlocks[0]
    .stages[0].sceneTasks.at(-1).clientNodeKey
  controller.removeSceneTask('block-1', 'stage-1', reconciledTask)
  assert.equal(controller.canUndoStoryBlockEdit.value, true)

  await controller.reconcile()

  assert.equal(controller.canUndoStoryBlockEdit.value, false)
  assert.equal(controller.undoStoryBlockEdit(), false)
})

test('hydrate create and confirm success are authoritative undo checkpoints', async () => {
  const hydrateStore = createStore({ content: contentWithLocalBlock() })
  const hydrateController = createPlanningWorkspaceController({
    store: hydrateStore,
    projectId: () => 'project-1',
  })
  hydrateController.removeStoryBlock('block-local')
  assert.equal(hydrateController.canUndoStoryBlockEdit.value, true)
  await hydrateController.hydrate()
  assert.equal(hydrateController.canUndoStoryBlockEdit.value, false)

  const createStoreInstance = createStore({ content: contentWithLocalBlock() })
  const createController = createPlanningWorkspaceController({
    store: createStoreInstance,
    projectId: () => 'project-1',
    keyFactory: () => 'create-checkpoint',
  })
  createController.removeStoryBlock('block-local')
  createStoreInstance.state.draft = null
  createStoreInstance.localContent = null
  await createController.createManualDraft()
  assert.equal(createController.canUndoStoryBlockEdit.value, false)

  const confirmStore = createStore({ content: contentWithLocalBlock() })
  const confirmController = createPlanningWorkspaceController({
    store: confirmStore,
    projectId: () => 'project-1',
    keyFactory: () => 'confirm-checkpoint',
  })
  confirmController.removeStoryBlock('block-local')
  confirmStore.dirty = false
  assert.equal(confirmController.canConfirm.value, true)
  assert.equal(confirmController.canUndoStoryBlockEdit.value, true)
  await confirmController.confirm()
  assert.equal(confirmController.canUndoStoryBlockEdit.value, false)
})

test('late A save cannot clear B undo or publish a stale success notice', async () => {
  let project = 'A'
  const pending = deferred()
  const store = createStore({ content: contentWithLocalTask() })
  store.saveDraft = async () => await pending.promise
  const controller = createPlanningWorkspaceController({
    store,
    projectId: () => project,
    keyFactory: () => 'save-A',
  })
  controller.enterProject('A')
  controller.removeSceneTask('block-1', 'stage-1', 'task-local')
  const savingA = controller.save()

  project = 'B'
  controller.enterProject('B')
  store.localContent = contentWithLocalTask()
  store.dirty = false
  controller.removeSceneTask('block-1', 'stage-1', 'task-local')
  controller.notice.value = 'B notice'
  assert.equal(controller.canUndoStoryBlockEdit.value, true)

  pending.resolve({ draftId: 'draft-A' })
  await savingA

  assert.equal(controller.canUndoStoryBlockEdit.value, true)
  assert.equal(controller.notice.value, 'B notice')
  assert.equal(controller.undoStoryBlockEdit(), true)
})

test('late A generate and reconcile successes cannot alter B local controller state', async () => {
  for (const operation of ['generate', 'reconcile']) {
    let project = 'A'
    const pending = deferred()
    const store = createStore({ content: completeContent() })
    if (operation === 'generate') {
      store.generateDraft = async () => await pending.promise
    } else {
      store.reconcileGeneration = async () => await pending.promise
    }
    const controller = createPlanningWorkspaceController({
      store,
      projectId: () => project,
      keyFactory: () => `${operation}-A`,
    })
    controller.enterProject('A')
    const requestA = operation === 'generate'
      ? controller.generate('A instructions')
      : controller.reconcile()

    project = 'B'
    controller.enterProject('B')
    store.localContent = contentWithLocalTask()
    store.dirty = false
    controller.removeSceneTask('block-1', 'stage-1', 'task-local')
    controller.notice.value = `B ${operation} notice`
    assert.equal(controller.canUndoStoryBlockEdit.value, true, operation)

    pending.resolve({ status: 'succeeded' })
    await requestA

    assert.equal(controller.canUndoStoryBlockEdit.value, true, operation)
    assert.equal(controller.notice.value, `B ${operation} notice`, operation)
    assert.equal(controller.undoStoryBlockEdit(), true, operation)
  }
})

test('hydrate create and confirm share the same stale-completion fence', async () => {
  {
    let project = 'A'
    const pending = deferred()
    const store = createStore({ content: completeContent() })
    store.ensureLoaded = async () => await pending.promise
    const controller = createPlanningWorkspaceController({
      store,
      projectId: () => project,
    })
    controller.enterProject('A')
    const hydrateA = controller.hydrate()

    project = 'B'
    controller.enterProject('B')
    store.localContent = contentWithLocalTask()
    store.dirty = false
    controller.removeSceneTask('block-1', 'stage-1', 'task-local')
    pending.resolve({ projectId: 'A' })
    await hydrateA

    assert.equal(controller.canUndoStoryBlockEdit.value, true, 'hydrate')
  }

  {
    let project = 'A'
    const pending = deferred()
    const store = createStore()
    store.state.draft = null
    store.localContent = null
    store.createDraft = async () => await pending.promise
    const controller = createPlanningWorkspaceController({
      store,
      projectId: () => project,
      keyFactory: () => 'create-A',
    })
    controller.enterProject('A')
    const createA = controller.createManualDraft()

    project = 'B'
    controller.enterProject('B')
    store.localContent = null
    controller.notice.value = 'B create notice'
    const editCallsBefore = store.calls.length
    pending.resolve({ draftId: 'draft-A' })
    await createA

    assert.equal(store.localContent, null, 'create local fallback')
    assert.equal(store.calls.length, editCallsBefore, 'create edit fallback')
    assert.equal(controller.notice.value, 'B create notice', 'create notice')
  }

  {
    let project = 'A'
    const pending = deferred()
    const operations = []
    const store = createStore({ content: contentWithLocalBlock() })
    store.confirmDraft = async () => await pending.promise
    const controller = createPlanningWorkspaceController({
      store,
      projectId: () => project,
      keyFactory: () => 'confirm-A',
      operationStore: {
        start() {
          operations.push('start')
          return 'confirm-operation-A'
        },
        finish(id) { operations.push(['finish', id]) },
      },
    })
    controller.enterProject('A')
    controller.removeStoryBlock('block-local')
    store.dirty = false
    const confirmA = controller.confirm()

    project = 'B'
    controller.enterProject('B')
    store.localContent = contentWithLocalTask()
    store.dirty = false
    controller.removeSceneTask('block-1', 'stage-1', 'task-local')
    controller.notice.value = 'B confirm notice'
    pending.resolve({ revision: 2 })
    await confirmA

    assert.equal(controller.canUndoStoryBlockEdit.value, true, 'confirm')
    assert.equal(controller.notice.value, 'B confirm notice', 'confirm notice')
    assert.deepEqual(operations, [
      'start',
      ['finish', 'confirm-operation-A'],
    ])
  }
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

test('leave protection skips exactly three same-project planning tabs and prompts elsewhere', () => {
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

  for (const name of [
    'ProjectPlanningVolumes',
    'ProjectPlanningPlots',
    'ProjectPlanningStoryBlocks',
  ]) {
    assert.equal(controller.requestRouteLeave({
      name,
      params: { projectId: 'project-1' },
    }), true)
  }
  assert.equal(prompts, 0)
  assert.equal(controller.requestRouteLeave({
    name: 'ProjectPlanningStoryBlocks',
    params: { projectId: 'project-2' },
  }), false)
  assert.equal(prompts, 1)
  assert.equal(controller.requestRouteLeave({
    name: 'ProjectOverview',
    params: { projectId: 'project-1' },
  }), false)
  assert.equal(prompts, 2)

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
