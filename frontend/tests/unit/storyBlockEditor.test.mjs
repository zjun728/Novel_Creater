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

function createStore(content = emptyContent()) {
  const calls = []
  return reactive({
    calls,
    state: {
      basisStatus: 'current',
      draft: { draftId: 'draft-1', status: 'active' },
      capabilities: { edit: true, confirm: true, generate: true },
    },
    localContent: structuredClone(content),
    dirty: false,
    loading: false,
    saving: false,
    confirming: false,
    generating: false,
    reconciling: false,
    generationOutcomeUnknown: false,
    awaitingAuthoritativeReload: false,
    editLocal(value) {
      const copy = structuredClone(value)
      calls.push(copy)
      this.localContent = copy
      this.dirty = true
    },
  })
}

function createController(content = emptyContent()) {
  let sequence = 0
  const store = createStore(content)
  const controller = createPlanningWorkspaceController({
    store,
    projectId: () => 'project-1',
    keyFactory: () => `client-${++sequence}`,
  })
  return { controller, store }
}

function activeBlockContent() {
  return {
    activeStoryBlockRef: 'block-1',
    volumes: [],
    plots: [],
    storyBlocks: [{
      id: 'block-1',
      order: 1,
      title: '旧故事块',
      blockGoal: '旧目标',
      volumeRef: '',
      plotRefs: [],
      lifecycle: 'active',
      stages: [],
    }],
  }
}

test('controller exports the complete nested story editor API', () => {
  const { controller } = createController()
  const methods = [
    'addStoryBlock',
    'updateStoryBlock',
    'removeStoryBlock',
    'moveStoryBlock',
    'selectActiveStoryBlock',
    'addStage',
    'updateStage',
    'removeStage',
    'moveStage',
    'addSceneTask',
    'updateSceneTask',
    'removeSceneTask',
    'moveSceneTask',
    'undoStoryBlockEdit',
  ]

  for (const method of methods) assert.equal(typeof controller[method], 'function')
})

test('new story nodes use stable keys, closed defaults, and the next existing order', () => {
  const content = activeBlockContent()
  content.storyBlocks[0].stages = [{
    id: 'retired-stage',
    order: 4,
    title: '旧阶段',
    lifecycle: 'retired',
    sceneTasks: [],
  }]
  content.storyBlocks.push({
    id: 'retired-block',
    order: 5,
    title: '旧块',
    lifecycle: 'retired',
    stages: [],
  })
  const { controller, store } = createController(content)

  assert.equal(controller.addStoryBlock(), true)
  assert.equal(controller.addStage('block-1'), true)
  assert.equal(controller.addSceneTask('block-1', 'client-2'), true)

  assert.deepEqual(store.localContent.storyBlocks[2], {
    clientNodeKey: 'client-1',
    order: 6,
    lifecycle: 'active',
    title: '',
    volumeRef: '',
    plotRefs: [],
    entrySituation: '',
    blockGoal: '',
    mainPressure: '',
    expectedChange: '',
    openQuestions: [],
    involvedCharacters: [],
    stages: [],
  })
  assert.deepEqual(store.localContent.storyBlocks[0].stages[1], {
    clientNodeKey: 'client-2',
    order: 5,
    lifecycle: 'active',
    title: '',
    purpose: '',
    dramaticQuestion: '',
    sceneTasks: [{
      clientNodeKey: 'client-3',
      order: 1,
      lifecycle: 'active',
      task: '',
      completionEvidence: '',
    }],
  })
  for (const node of [
    store.localContent.storyBlocks[2],
    store.localContent.storyBlocks[0].stages[1],
    store.localContent.storyBlocks[0].stages[1].sceneTasks[0],
  ]) {
    assert.equal('id' in node, false)
    assert.equal('revision' in node, false)
    assert.equal('contentHash' in node, false)
    assert.equal('targetChapterCount' in node, false)
    assert.equal('completed' in node, false)
    assert.equal('actualProgress' in node, false)
  }
  assert.equal(store.calls.length, 3)
})

test('updates clone allowed fields only and active block selection rejects invalid targets', () => {
  const content = activeBlockContent()
  content.storyBlocks.push({
    id: 'retired-block',
    order: 2,
    title: '退役块',
    lifecycle: 'retired',
    stages: [],
  })
  const { controller, store } = createController(content)
  const original = store.localContent

  assert.equal(controller.updateStoryBlock('block-1', {
    title: '新故事块',
    plotRefs: ['plot-1'],
    involvedCharacters: ['沈砚'],
    targetChapterCount: 12,
    completed: true,
    actualProgress: 3,
    unknown: 'forbidden',
  }), true)
  assert.equal(controller.selectActiveStoryBlock('block-1'), true)
  assert.equal(controller.selectActiveStoryBlock('retired-block'), false)
  assert.equal(controller.selectActiveStoryBlock('missing'), false)

  const block = store.localContent.storyBlocks[0]
  assert.equal(block.title, '新故事块')
  assert.deepEqual(block.plotRefs, ['plot-1'])
  assert.deepEqual(block.involvedCharacters, ['沈砚'])
  assert.equal('targetChapterCount' in block, false)
  assert.equal('completed' in block, false)
  assert.equal('actualProgress' in block, false)
  assert.equal('unknown' in block, false)
  assert.equal(store.localContent.activeStoryBlockRef, 'block-1')
  assert.notEqual(store.localContent, original)
  assert.equal(original.storyBlocks[0].title, '旧故事块')
})

test('nested updates and moves affect active siblings only and preserve retired snapshots', () => {
  const content = activeBlockContent()
  const retiredStage = {
    id: 'stage-retired',
    order: 2,
    title: '退役阶段',
    purpose: '旧用途',
    dramaticQuestion: '旧问题',
    lifecycle: 'retired',
    revision: 4,
    contentHash: 'a'.repeat(64),
    sceneTasks: [],
  }
  const retiredTask = {
    id: 'task-retired',
    order: 2,
    task: '退役任务',
    completionEvidence: '旧证据',
    lifecycle: 'retired',
    revision: 2,
    contentHash: 'b'.repeat(64),
  }
  content.storyBlocks[0].stages = [
    {
      id: 'stage-a',
      order: 1,
      title: 'A',
      purpose: '',
      dramaticQuestion: '',
      lifecycle: 'active',
      sceneTasks: [
        { id: 'task-a', order: 1, task: 'A', completionEvidence: '', lifecycle: 'active' },
        retiredTask,
        { id: 'task-b', order: 3, task: 'B', completionEvidence: '', lifecycle: 'active' },
      ],
    },
    retiredStage,
    {
      id: 'stage-b',
      order: 3,
      title: 'B',
      purpose: '',
      dramaticQuestion: '',
      lifecycle: 'active',
      sceneTasks: [],
    },
  ]
  const { controller, store } = createController(content)
  const retiredStageCopy = structuredClone(retiredStage)
  const retiredTaskCopy = structuredClone(retiredTask)

  assert.equal(controller.updateStage('block-1', 'stage-a', {
    purpose: '推进潜入',
    completed: true,
  }), true)
  assert.equal(controller.updateSceneTask('block-1', 'stage-a', 'task-a', {
    completionEvidence: '拿到钥匙',
    actualProgress: 1,
  }), true)
  assert.equal(controller.moveStage('block-1', 'stage-b', -1), true)
  assert.equal(controller.moveSceneTask('block-1', 'stage-a', 'task-b', -1), true)
  assert.equal(controller.moveStage('block-1', 'stage-b', -1), false)
  assert.equal(controller.moveSceneTask('block-1', 'stage-a', 'task-b', -1), false)

  const block = store.localContent.storyBlocks[0]
  assert.deepEqual(
    block.stages.map(stage => [stage.id, stage.order]),
    [['stage-b', 1], ['stage-retired', 2], ['stage-a', 3]],
  )
  assert.deepEqual(block.stages[1], retiredStageCopy)
  const stageA = block.stages[2]
  assert.equal(stageA.purpose, '推进潜入')
  assert.equal('completed' in stageA, false)
  assert.deepEqual(
    stageA.sceneTasks.map(task => [task.id, task.order]),
    [['task-b', 1], ['task-retired', 2], ['task-a', 3]],
  )
  assert.deepEqual(stageA.sceneTasks[1], retiredTaskCopy)
  assert.equal(stageA.sceneTasks[2].completionEvidence, '拿到钥匙')
  assert.equal('actualProgress' in stageA.sceneTasks[2], false)
})

test('story block reorder swaps active slots only', () => {
  const content = activeBlockContent()
  const retired = {
    id: 'block-retired',
    order: 2,
    title: '退役块',
    lifecycle: 'retired',
    revision: 2,
    contentHash: 'c'.repeat(64),
    stages: [],
  }
  content.storyBlocks.push(retired, {
    id: 'block-2',
    order: 3,
    title: '第二块',
    lifecycle: 'active',
    stages: [],
  })
  const { controller, store } = createController(content)
  const retiredCopy = structuredClone(retired)

  assert.equal(controller.moveStoryBlock('block-2', -1), true)
  assert.deepEqual(
    store.localContent.storyBlocks.map(block => [block.id, block.order]),
    [['block-2', 1], ['block-retired', 2], ['block-1', 3]],
  )
  assert.deepEqual(store.localContent.storyBlocks[1], retiredCopy)
  assert.equal(controller.moveStoryBlock('block-2', -1), false)
})

test('move methods reject every direction except numeric minus one or one without editing', () => {
  const content = activeBlockContent()
  content.volumes = [
    { id: 'volume-1', order: 1, lifecycle: 'active' },
    { id: 'volume-2', order: 2, lifecycle: 'active' },
  ]
  content.plots = [
    { id: 'plot-1', order: 1, lifecycle: 'active' },
    { id: 'plot-2', order: 2, lifecycle: 'active' },
  ]
  content.storyBlocks.push({
    id: 'block-2',
    order: 2,
    title: '第二块',
    lifecycle: 'active',
    stages: [],
  })
  content.storyBlocks[0].stages = [{
    id: 'stage-1',
    order: 1,
    lifecycle: 'active',
    sceneTasks: [
      { id: 'task-1', order: 1, lifecycle: 'active' },
      { id: 'task-2', order: 2, lifecycle: 'active' },
    ],
  }, {
    id: 'stage-2',
    order: 2,
    lifecycle: 'active',
    sceneTasks: [],
  }]
  const { controller, store } = createController(content)
  const moves = [
    direction => controller.moveVolume('volume-1', direction),
    direction => controller.movePlot('plot-1', direction),
    direction => controller.moveStoryBlock('block-1', direction),
    direction => controller.moveStage('block-1', 'stage-1', direction),
    direction => controller.moveSceneTask('block-1', 'stage-1', 'task-1', direction),
  ]

  for (const direction of [0, '1', Number.NaN, 2, -2, undefined, null]) {
    for (const move of moves) assert.equal(move(direction), false)
  }
  assert.equal(store.calls.length, 0)
  assert.equal(store.dirty, false)
})

test('physical story block deletion clears selection and single-step undo restores subtree and position', () => {
  const content = activeBlockContent()
  content.storyBlocks.unshift({
    clientNodeKey: 'local-block',
    order: 0,
    title: '临时块',
    lifecycle: 'active',
    stages: [{
      clientNodeKey: 'local-stage',
      order: 1,
      title: '临时阶段',
      lifecycle: 'active',
      sceneTasks: [],
    }],
  })
  content.activeStoryBlockRef = 'local-block'
  const { controller, store } = createController(content)

  assert.equal(controller.removeStoryBlock('local-block'), true)
  assert.equal(store.localContent.activeStoryBlockRef, null)
  assert.deepEqual(store.localContent.storyBlocks.map(block => block.id), ['block-1'])
  assert.equal(controller.undoStoryBlockEdit(), true)
  assert.equal(store.localContent.activeStoryBlockRef, 'local-block')
  assert.equal(store.localContent.storyBlocks[0].clientNodeKey, 'local-block')
  assert.equal(store.localContent.storyBlocks[0].stages[0].clientNodeKey, 'local-stage')
  assert.equal(controller.undoStoryBlockEdit(), false)
})

test('the newest physical nested deletion replaces undo and project switches clear it', () => {
  const content = activeBlockContent()
  content.storyBlocks[0].stages = [
    {
      clientNodeKey: 'stage-local-a',
      order: 1,
      title: 'A',
      lifecycle: 'active',
      sceneTasks: [],
    },
    {
      clientNodeKey: 'stage-local-b',
      order: 2,
      title: 'B',
      lifecycle: 'active',
      sceneTasks: [
        { clientNodeKey: 'task-local-a', order: 1, task: 'A', lifecycle: 'active' },
        { clientNodeKey: 'task-local-b', order: 2, task: 'B', lifecycle: 'active' },
      ],
    },
  ]
  const { controller, store } = createController(content)
  controller.enterProject('project-1')

  assert.equal(controller.removeStage('block-1', 'stage-local-a'), true)
  assert.equal(controller.removeSceneTask('block-1', 'stage-local-b', 'task-local-a'), true)
  assert.equal(controller.undoStoryBlockEdit(), true)
  assert.equal(
    store.localContent.storyBlocks[0].stages.some(stage => stage.clientNodeKey === 'stage-local-a'),
    false,
  )
  assert.deepEqual(
    store.localContent.storyBlocks[0].stages[0].sceneTasks.map(task => task.clientNodeKey),
    ['task-local-a', 'task-local-b'],
  )

  assert.equal(controller.removeSceneTask('block-1', 'stage-local-b', 'task-local-a'), true)
  controller.enterProject('project-2')
  assert.equal(controller.undoStoryBlockEdit(), false)
})

test('nested undo restores deleted nodes without overriding a later block selection', () => {
  const content = activeBlockContent()
  content.storyBlocks[0].stages = [{
    clientNodeKey: 'stage-local',
    order: 1,
    title: '本地阶段',
    lifecycle: 'active',
    sceneTasks: [{
      clientNodeKey: 'task-local',
      order: 1,
      task: '本地任务',
      lifecycle: 'active',
    }],
  }]
  content.storyBlocks.push({
    id: 'block-2',
    order: 2,
    title: '第二块',
    lifecycle: 'active',
    stages: [],
  })
  const { controller, store } = createController(content)

  assert.equal(controller.removeStage('block-1', 'stage-local'), true)
  assert.equal(controller.selectActiveStoryBlock('block-2'), true)
  assert.equal(controller.undoStoryBlockEdit(), true)
  assert.equal(store.localContent.activeStoryBlockRef, 'block-2')
  assert.equal(
    store.localContent.storyBlocks[0].stages[0].clientNodeKey,
    'stage-local',
  )

  assert.equal(controller.selectActiveStoryBlock('block-1'), true)
  assert.equal(
    controller.removeSceneTask('block-1', 'stage-local', 'task-local'),
    true,
  )
  assert.equal(controller.selectActiveStoryBlock('block-2'), true)
  assert.equal(controller.undoStoryBlockEdit(), true)
  assert.equal(store.localContent.activeStoryBlockRef, 'block-2')
  assert.equal(
    store.localContent.storyBlocks[0].stages[0].sceneTasks[0].clientNodeKey,
    'task-local',
  )
})

test('undoing deletion of a non-selected story block preserves a later selection', () => {
  const content = activeBlockContent()
  content.storyBlocks.push({
    id: 'block-2',
    order: 2,
    title: '第二块',
    lifecycle: 'active',
    stages: [],
  }, {
    clientNodeKey: 'block-local',
    order: 3,
    title: '临时块',
    lifecycle: 'active',
    stages: [],
  })
  const { controller, store } = createController(content)

  assert.equal(controller.removeStoryBlock('block-local'), true)
  assert.equal(controller.selectActiveStoryBlock('block-2'), true)
  assert.equal(controller.undoStoryBlockEdit(), true)
  assert.equal(store.localContent.activeStoryBlockRef, 'block-2')
  assert.equal(
    store.localContent.storyBlocks[2].clientNodeKey,
    'block-local',
  )
})

test('undoing deletion of the selected story block preserves a later new selection', () => {
  const content = activeBlockContent()
  content.storyBlocks.unshift({
    clientNodeKey: 'block-local',
    order: 0,
    title: '临时块',
    lifecycle: 'active',
    stages: [],
  })
  content.storyBlocks.push({
    id: 'block-2',
    order: 2,
    title: '第二块',
    lifecycle: 'active',
    stages: [],
  })
  content.activeStoryBlockRef = 'block-local'
  const { controller, store } = createController(content)

  assert.equal(controller.removeStoryBlock('block-local'), true)
  assert.equal(store.localContent.activeStoryBlockRef, null)
  assert.equal(controller.selectActiveStoryBlock('block-2'), true)
  assert.equal(controller.undoStoryBlockEdit(), true)
  assert.equal(store.localContent.activeStoryBlockRef, 'block-2')
  assert.equal(
    store.localContent.storyBlocks[0].clientNodeKey,
    'block-local',
  )
})

test('undo preserves a unique sibling order after a later add reuses the deleted order', () => {
  const content = activeBlockContent()
  content.storyBlocks[0].stages = [{
    clientNodeKey: 'stage-deleted',
    order: 1,
    title: '先删除',
    lifecycle: 'active',
    sceneTasks: [],
  }]
  const { controller, store } = createController(content)

  assert.equal(controller.removeStage('block-1', 'stage-deleted'), true)
  assert.equal(controller.addStage('block-1'), true)
  assert.equal(controller.undoStoryBlockEdit(), true)

  const stages = store.localContent.storyBlocks[0].stages
  assert.equal(stages[0].clientNodeKey, 'stage-deleted')
  assert.equal(new Set(stages.map(stage => stage.order)).size, stages.length)
})

test('historical retirement cascades without reactivation while local descendants disappear', () => {
  const content = activeBlockContent()
  content.storyBlocks[0].stages = [
    {
      id: 'stage-history',
      order: 1,
      title: '历史阶段',
      lifecycle: 'active',
      sceneTasks: [
        { id: 'task-history', order: 1, task: '历史任务', lifecycle: 'active' },
        { clientNodeKey: 'task-local', order: 2, task: '本地任务', lifecycle: 'active' },
      ],
    },
    {
      clientNodeKey: 'stage-local',
      order: 2,
      title: '本地阶段',
      lifecycle: 'active',
      sceneTasks: [],
    },
  ]
  const { controller, store } = createController(content)

  assert.equal(controller.removeStoryBlock('block-1'), true)
  const retiredBlock = store.localContent.storyBlocks[0]
  assert.equal(retiredBlock.lifecycle, 'retired')
  assert.equal(retiredBlock.stages.length, 1)
  assert.equal(retiredBlock.stages[0].lifecycle, 'retired')
  assert.equal(retiredBlock.stages[0].sceneTasks.length, 1)
  assert.equal(retiredBlock.stages[0].sceneTasks[0].lifecycle, 'retired')
  assert.equal(store.localContent.activeStoryBlockRef, null)
  assert.equal(controller.undoStoryBlockEdit(), false)
  assert.equal(controller.updateStoryBlock('block-1', { title: '复活' }), false)
  assert.equal(controller.selectActiveStoryBlock('block-1'), false)
  assert.equal(controller.removeStoryBlock('block-1'), false)
})

test('cascade retirement keeps formal history and drops every local descendant regardless of lifecycle', () => {
  const content = activeBlockContent()
  content.storyBlocks[0].stages = [{
    clientNodeKey: 'stage-local-retired',
    order: 1,
    title: '异常本地阶段',
    lifecycle: 'retired',
    sceneTasks: [{
      clientNodeKey: 'task-under-local-stage',
      order: 1,
      task: '随本地阶段移除',
      lifecycle: 'active',
    }],
  }, {
    id: 'stage-history-retired',
    order: 2,
    title: '历史阶段',
    lifecycle: 'retired',
    sceneTasks: [{
      id: 'task-history-active',
      order: 1,
      task: '历史任务',
      lifecycle: 'active',
    }, {
      clientNodeKey: 'task-local-retired',
      order: 2,
      task: '异常本地任务',
      lifecycle: 'retired',
    }],
  }]
  const { controller, store } = createController(content)

  assert.equal(controller.removeStoryBlock('block-1'), true)
  const retiredBlock = store.localContent.storyBlocks[0]
  assert.deepEqual(
    retiredBlock.stages.map(stage => [stage.id, stage.lifecycle]),
    [['stage-history-retired', 'retired']],
  )
  assert.deepEqual(
    retiredBlock.stages[0].sceneTasks.map(task => [task.id, task.lifecycle]),
    [['task-history-active', 'retired']],
  )
})

test('historical stage and scene task retirement cascade independently', () => {
  const content = activeBlockContent()
  content.storyBlocks[0].stages = [{
    id: 'stage-history',
    order: 1,
    title: '历史阶段',
    lifecycle: 'active',
    sceneTasks: [
      { id: 'task-history', order: 1, task: '历史任务', lifecycle: 'active' },
      { clientNodeKey: 'task-local', order: 2, task: '本地任务', lifecycle: 'active' },
    ],
  }, {
    id: 'stage-other',
    order: 2,
    title: '另一阶段',
    lifecycle: 'active',
    sceneTasks: [{
      id: 'task-other',
      order: 1,
      task: '另一任务',
      lifecycle: 'active',
    }],
  }]
  const { controller, store } = createController(content)

  assert.equal(controller.removeStage('block-1', 'stage-history'), true)
  const retiredStage = store.localContent.storyBlocks[0].stages[0]
  assert.equal(retiredStage.lifecycle, 'retired')
  assert.deepEqual(retiredStage.sceneTasks.map(task => [task.id, task.lifecycle]), [
    ['task-history', 'retired'],
  ])
  assert.equal(controller.updateStage('block-1', 'stage-history', { title: '复活' }), false)
  assert.equal(controller.removeStage('block-1', 'stage-history'), false)

  assert.equal(controller.removeSceneTask('block-1', 'stage-other', 'task-other'), true)
  assert.equal(
    store.localContent.storyBlocks[0].stages[1].sceneTasks[0].lifecycle,
    'retired',
  )
  assert.equal(
    controller.updateSceneTask('block-1', 'stage-other', 'task-other', { task: '复活' }),
    false,
  )
})

function confirmableContent() {
  return {
    activeStoryBlockRef: 'block-1',
    volumes: [{
      id: 'volume-1',
      order: 1,
      title: '第一卷',
      coreChange: '从逃亡转为追查',
      lifecycle: 'active',
    }],
    plots: [{
      id: 'plot-1',
      order: 1,
      title: '残卷主线',
      storyQuestion: '残卷为何择主',
      lifecycle: 'active',
    }],
    storyBlocks: [{
      id: 'block-1',
      order: 1,
      title: '夜入县衙',
      blockGoal: '取得残卷',
      volumeRef: 'volume-1',
      plotRefs: ['plot-1'],
      lifecycle: 'active',
      stages: [{
        id: 'stage-1',
        order: 1,
        title: '潜入',
        purpose: '进入密库',
        dramaticQuestion: '能否避开守卫',
        lifecycle: 'active',
        sceneTasks: [{
          id: 'task-1',
          order: 1,
          task: '偷取钥匙',
          completionEvidence: '钥匙到手',
          lifecycle: 'active',
        }],
      }],
    }],
  }
}

test('planning completeness matches the minimum active aggregate contract', () => {
  const valid = confirmableContent()
  assert.equal(isCompletePlanningAggregate(valid), true)

  const invalidVariants = [
    content => { content.volumes[0].title = '' },
    content => { content.volumes[0].coreChange = '' },
    content => { content.plots[0].title = '' },
    content => { content.plots[0].storyQuestion = '' },
    content => { content.activeStoryBlockRef = 'missing' },
    content => { content.storyBlocks[0].title = '' },
    content => { content.storyBlocks[0].blockGoal = '' },
    content => { content.storyBlocks[0].volumeRef = 'missing' },
    content => { content.storyBlocks[0].plotRefs = [] },
    content => { content.storyBlocks[0].plotRefs = ['plot-1', 'plot-1'] },
    content => { content.storyBlocks[0].plotRefs = ['retired-plot'] },
    content => { content.storyBlocks[0].stages = [] },
    content => { content.storyBlocks[0].stages[0].title = '' },
    content => { content.storyBlocks[0].stages[0].purpose = '' },
    content => { content.storyBlocks[0].stages[0].dramaticQuestion = '' },
    content => { content.storyBlocks[0].stages[0].sceneTasks = [] },
    content => { content.storyBlocks[0].stages[0].sceneTasks[0].task = '' },
    content => { content.storyBlocks[0].stages[0].sceneTasks[0].completionEvidence = '' },
    content => { content.volumes[0].lifecycle = 'completed' },
    content => { content.plots[0].lifecycle = undefined },
    content => { content.storyBlocks[0].lifecycle = 'completed' },
    content => { content.storyBlocks[0].stages[0].lifecycle = 'completed' },
    content => { content.storyBlocks[0].stages[0].sceneTasks[0].lifecycle = 'completed' },
    content => {
      content.storyBlocks[0].stages[0].sceneTasks.push({
        id: 'task-incomplete',
        order: 2,
        task: '',
        completionEvidence: '没有任务描述',
        lifecycle: 'active',
      })
    },
  ]
  for (const makeInvalid of invalidVariants) {
    const content = structuredClone(valid)
    content.plots.push({
      id: 'retired-plot',
      order: 2,
      title: '退役线',
      storyQuestion: '旧问题',
      lifecycle: 'retired',
    })
    makeInvalid(content)
    assert.equal(isCompletePlanningAggregate(content), false)
  }
})

test('editor methods fail closed for non-active lifecycle values', () => {
  const content = activeBlockContent()
  content.storyBlocks[0].lifecycle = 'completed'
  const { controller, store } = createController(content)

  assert.equal(controller.selectActiveStoryBlock('block-1'), false)
  assert.equal(controller.updateStoryBlock('block-1', { title: '不得编辑' }), false)
  assert.equal(controller.addStage('block-1'), false)
  assert.deepEqual(store.calls, [])
})
