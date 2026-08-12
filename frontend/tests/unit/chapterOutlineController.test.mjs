import assert from 'node:assert/strict'
import test from 'node:test'

import { computed, reactive } from 'vue'

import { createChapterOutlineController } from '../../src/application/planning/chapterOutlineController.js'

const HASH = 'a'.repeat(64)

function deferred() {
  let resolve
  let reject
  const promise = new Promise((onResolve, onReject) => {
    resolve = onResolve
    reject = onReject
  })
  return { promise, resolve, reject }
}

function content(goal = '取得残卷') {
  return {
    schemaVersion: 'chapter-outline-draft-v1',
    volumeRef: { id: 'volume-1', revision: 1, contentHash: HASH },
    storyBlockRef: { id: 'block-1', revision: 1, contentHash: HASH },
    stageRefs: [{ id: 'stage-1', revision: 1, contentHash: HASH }],
    sceneTaskRefs: [{ id: 'task-1', revision: 1, contentHash: HASH }],
    chapterGoal: goal,
    expectedCharacters: ['沈砚'],
    continuation: ['追兵逼近'],
    plannedTasks: ['潜入县衙'],
    scenes: ['县衙外'],
    forbiddenEarlyEvents: ['不提前揭密'],
  }
}

function state(overrides = {}) {
  return {
    projectId: 'project-1',
    lifecycle: 'active',
    authoritativeChapterNumber: 3,
    targetPath: '/projects/project-1/planning/story-blocks',
    planningAuthority: {
      planningRevisionId: 'planning-1',
      revision: 4,
      contentHash: HASH,
      content: {
        activeStoryBlockId: 'block-1',
        volumes: [{
          id: 'volume-1',
          revision: 1,
          contentHash: HASH,
          lifecycle: 'active',
          title: '第一卷',
        }],
        plots: [],
        storyBlocks: [{
          id: 'block-1',
          revision: 1,
          contentHash: HASH,
          lifecycle: 'active',
          title: '夜入县衙',
          volumeId: 'volume-1',
          plotIds: [],
          stages: [{
            id: 'stage-1',
            revision: 1,
            contentHash: HASH,
            lifecycle: 'active',
            title: '潜入',
            sceneTasks: [{
              id: 'task-1',
              revision: 1,
              contentHash: HASH,
              lifecycle: 'active',
              task: '取得残卷',
            }],
          }],
        }],
      },
    },
    canonProjectionAuthority: {
      canonRevision: 2,
      projectionRevision: 2,
      contentHash: HASH,
      synchronized: true,
    },
    confirmedOutline: null,
    draft: {
      projectId: 'project-1',
      chapterNumber: 3,
      draftId: 'draft-1',
      baseHeadRevision: 0,
      draftRevision: 1,
      contentHash: HASH,
      content: content(),
      basis: {},
      status: 'current',
    },
    activeSession: null,
    capabilities: {
      view: true,
      createDraft: false,
      editDraft: true,
      generate: false,
      confirm: true,
      startSession: false,
    },
    reasons: [],
    ...overrides,
  }
}

function storeFixture() {
  const calls = []
  const store = reactive({
    calls,
    projectId: 'project-1',
    outlineState: state(),
    outlineHistory: [],
    outlineLocalContent: content(),
    outlineDirty: false,
    outlineLoading: false,
    outlineSaving: false,
    outlineConfirming: false,
    outlineGenerating: false,
    outlineReconciling: false,
    outlineOperation: null,
    outlineRecoveryKey: '',
    outlineOutcomeUnknown: false,
    outlineAwaitingAuthority: false,
    async ensureOutlineLoaded(projectId, options) {
      calls.push(options
        ? ['hydrate', projectId, structuredClone(options)]
        : ['hydrate', projectId])
      return this.outlineState
    },
    async createOutlineDraft(projectId) {
      calls.push(['create', projectId])
      return this.outlineState.draft
    },
    editOutlineLocal(next) {
      calls.push(['edit', structuredClone(next)])
      this.outlineLocalContent = structuredClone(next)
      this.outlineDirty = true
    },
    async saveOutlineDraft() {
      calls.push(['save'])
      this.outlineDirty = false
      return this.outlineState.draft
    },
    async generateOutlineDraft(command) {
      calls.push(['generate', structuredClone(command)])
      return { status: 'succeeded' }
    },
    async reconcileOutlineGeneration() {
      calls.push(['reconcile'])
      return { status: 'succeeded' }
    },
    async confirmOutlineDraft(command) {
      calls.push(['confirm', structuredClone(command)])
      return { revision: 1 }
    },
  })
  return store
}

test('drafting Session permits outline adjustment only through server capabilities', () => {
  const store = storeFixture()
  store.outlineState.activeSession = { status: 'drafting' }
  store.outlineState.capabilities = {
    ...store.outlineState.capabilities,
    createDraft: true,
    editDraft: false,
  }

  const controller = createChapterOutlineController({
    store,
    projectId: () => 'project-1',
  })

  assert.equal(controller.canAdjustOutline.value, true)
  store.outlineState.activeSession.status = 'final'
  assert.equal(controller.canAdjustOutline.value, false)
})

test('outline controller exposes the exact authoring actions and keeps typing local', async () => {
  const store = storeFixture()
  let key = 0
  const controller = createChapterOutlineController({
    store,
    projectId: () => 'project-1',
    keyFactory: () => `outline-key-${++key}`,
  })

  for (const method of [
    'createManualDraft',
    'editLocal',
    'save',
    'generate',
    'reconcile',
    'confirm',
    'openHistory',
    'closeHistory',
  ]) {
    assert.equal(typeof controller[method], 'function', method)
  }

  await controller.hydrate()
  controller.editLocal(content('只改本地'))
  assert.equal(store.calls.filter(call => call[0] === 'save').length, 0)
  assert.equal(store.outlineLocalContent.chapterGoal, '只改本地')

  await controller.save()
  controller.authorInstructions.value = '加强人物选择'
  store.outlineState.capabilities.generate = true
  await controller.generate()
  await controller.reconcile()
  await controller.confirm()
  controller.openHistory()
  assert.equal(controller.historyOpen.value, true)
  controller.closeHistory()
  assert.equal(controller.historyOpen.value, false)
  assert.deepEqual(store.calls.slice(-4), [
    ['save'],
    ['generate', {
      idempotencyKey: 'outline-key-1',
      authorInstructions: '加强人物选择',
    }],
    ['reconcile'],
    ['confirm', { idempotencyKey: 'outline-key-2' }],
  ])
})

test('model-unready leaves manual outline work enabled and locks only outline generation', () => {
  const store = storeFixture()
  const controller = createChapterOutlineController({
    store,
    projectId: () => 'project-1',
  })

  assert.equal(controller.editable.value, true)
  assert.equal(controller.canGenerate.value, false)
  assert.match(controller.generationDisabledReason.value, /模型.*未就绪/)

  store.outlineDirty = true
  assert.equal(controller.canSave.value, true)
  store.outlineGenerating = true
  assert.equal(controller.localOverlay.value, true)
  assert.equal(controller.editorLocked.value, true)
})

test('outline confirmation alone uses the global blocking operation overlay', async () => {
  const store = storeFixture()
  const operations = []
  const operationStore = {
    start(value) {
      operations.push(['start', value])
      return 'operation-ui-1'
    },
    finish(id) {
      operations.push(['finish', id])
    },
  }
  const controller = createChapterOutlineController({
    store,
    projectId: () => 'project-1',
    operationStore,
    keyFactory: () => 'outline-confirm-1',
  })

  await controller.confirm()

  assert.deepEqual(operations, [
    ['start', {
      label: '正在确认章节小纲',
      detail: '确认会创建不可变小纲修订',
      blocking: true,
    }],
    ['finish', 'operation-ui-1'],
  ])
})

test('combined leave risk includes both authoring surfaces without prompting between planning tabs', () => {
  const store = storeFixture()
  const controller = createChapterOutlineController({
    store,
    projectId: () => 'project-1',
  })
  const planningController = {
    authorInstructions: { value: '' },
    hasCriticalRecovery: computed(() => false),
  }

  assert.equal(controller.hasCombinedLeaveRisk(planningController), false)
  controller.authorInstructions.value = '临时小纲要求'
  assert.equal(controller.hasCombinedLeaveRisk(planningController), true)
  controller.authorInstructions.value = ''
  store.outlineDirty = true
  assert.equal(controller.hasCombinedLeaveRisk(planningController), true)
  store.outlineDirty = false
  store.outlineOutcomeUnknown = true
  assert.equal(controller.hasCombinedLeaveRisk(planningController), true)
})

test('controller derives fixed recovery destinations and read-only authority states', () => {
  const store = storeFixture()
  const controller = createChapterOutlineController({
    store,
    projectId: () => 'project-1',
  })

  store.outlineState.reasons = ['planningOrProjectionUnavailable']
  assert.deepEqual(
    controller.recoveryActions.value.map(action => action.path),
    [
      '/projects/project-1/bible',
      '/projects/project-1/planning/story-blocks',
    ],
  )
  store.outlineState.reasons = ['canonProjectionOutOfSync']
  assert.equal(controller.readOnly.value, false)
  assert.equal(controller.canConfirm.value, false)
  store.outlineState.draft.status = 'superseded'
  assert.equal(controller.readOnly.value, true)
})

test('superseded authority stays read-only while backend capability permits one new draft', async () => {
  const store = storeFixture()
  store.outlineState.draft.status = 'superseded'
  store.outlineState.capabilities = {
    ...store.outlineState.capabilities,
    createDraft: true,
    editDraft: false,
    generate: false,
    confirm: false,
  }
  let creates = 0
  store.createOutlineDraft = async projectId => {
    creates += 1
    const created = {
      ...store.outlineState.draft,
      projectId,
      draftId: 'draft-2',
      status: 'current',
    }
    store.outlineState.draft = created
    store.outlineState.capabilities.createDraft = false
    store.outlineState.capabilities.editDraft = true
    return created
  }
  const controller = createChapterOutlineController({
    store,
    projectId: () => 'project-1',
  })

  assert.equal(controller.readOnly.value, true)
  assert.equal(controller.canCreateDraft.value, true)
  store.outlineSaving = true
  assert.equal(controller.canCreateDraft.value, false)
  store.outlineSaving = false
  await controller.createManualDraft()
  await controller.createManualDraft()

  assert.equal(creates, 1)
  assert.equal(store.outlineState.draft.status, 'current')
  assert.equal(controller.readOnly.value, false)
  assert.equal(controller.editable.value, true)
})

test('drift and superseded recovery never link the current story-block page to itself', () => {
  const store = storeFixture()
  const controller = createChapterOutlineController({
    store,
    projectId: () => 'project-1',
  })

  store.outlineState.reasons = ['canonProjectionOutOfSync']
  assert.deepEqual(controller.recoveryActions.value, [])

  store.outlineState.reasons = []
  store.outlineState.draft.status = 'superseded'
  assert.deepEqual(controller.recoveryActions.value, [])
})

test('generate and reconcile publish success only after exact authority is installed', async () => {
  const result = {
    operationId: 'outline-operation-1',
    status: 'succeeded',
    loaded: true,
    loadedDraftRevision: 2,
  }
  const cases = [
    {
      action: 'generate',
      storeMethod: 'generateOutlineDraft',
      before(store) {
        store.outlineState.capabilities.generate = true
      },
      during(store) {
        store.outlineAwaitingAuthority = true
        store.outlineGenerating = true
      },
    },
    {
      action: 'reconcile',
      storeMethod: 'reconcileOutlineGeneration',
      before() {},
      during(store) {
        store.outlineOutcomeUnknown = true
        store.outlineReconciling = true
      },
    },
    {
      action: 'generate',
      storeMethod: 'generateOutlineDraft',
      before(store) {
        store.outlineState.capabilities.generate = true
      },
      during(store) {
        store.outlineError = {
          code: 'ChapterOutlineGenerationRefreshFailed',
          message: 'refresh failed',
        }
      },
    },
  ]

  for (const entry of cases) {
    const store = storeFixture()
    entry.before(store)
    store[entry.storeMethod] = async () => {
      store.outlineOperation = result
      entry.during(store)
      return result
    }
    const controller = createChapterOutlineController({
      store,
      projectId: () => 'project-1',
      keyFactory: () => 'outline-operation-key',
    })

    await controller[entry.action]()
    assert.equal(controller.notice.value, '', entry.action)
  }

  for (const entry of [
    ['generate', 'generateOutlineDraft', 'AI 小纲已写入当前工作稿'],
    ['reconcile', 'reconcileOutlineGeneration', '已恢复并核对小纲生成结果'],
  ]) {
    const store = storeFixture()
    if (entry[0] === 'generate') store.outlineState.capabilities.generate = true
    store[entry[1]] = async () => {
      store.outlineOperation = result
      store.outlineState.draft = {
        ...store.outlineState.draft,
        draftRevision: 2,
        status: 'current',
      }
      store.outlineOutcomeUnknown = false
      store.outlineAwaitingAuthority = false
      store.outlineGenerating = false
      store.outlineReconciling = false
      store.outlineError = null
      return result
    }
    const controller = createChapterOutlineController({
      store,
      projectId: () => 'project-1',
      keyFactory: () => 'outline-operation-key',
    })

    await controller[entry[0]]()
    assert.equal(controller.notice.value, entry[2])
  }
})

test('hydrate forwards an explicit force read without publishing across projects', async () => {
  const pending = deferred()
  let currentProject = 'project-1'
  const store = storeFixture()
  store.ensureOutlineLoaded = async (projectId, options) => {
    store.calls.push(['hydrate', projectId, structuredClone(options)])
    return pending.promise
  }
  const controller = createChapterOutlineController({
    store,
    projectId: () => currentProject,
  })

  const hydration = controller.hydrate({ force: true })
  currentProject = 'project-2'
  controller.enterProject(currentProject)
  pending.resolve(state({ projectId: 'project-1' }))
  await hydration

  assert.deepEqual(store.calls.at(-1), [
    'hydrate',
    'project-1',
    { force: true },
  ])
  assert.equal(controller.notice.value, '')
})

test('late outline operations cannot publish notices into a newer project', async () => {
  const cases = [
    {
      action: 'createManualDraft',
      storeMethod: 'createOutlineDraft',
      prepare(store) {
        store.outlineState.draft = null
        store.outlineState.capabilities.createDraft = true
      },
      result: { draftId: 'draft-1' },
    },
    {
      action: 'save',
      storeMethod: 'saveOutlineDraft',
      prepare(store) { store.outlineDirty = true },
      result: { draftId: 'draft-1' },
    },
    {
      action: 'generate',
      storeMethod: 'generateOutlineDraft',
      prepare(store) { store.outlineState.capabilities.generate = true },
      result: { status: 'succeeded' },
    },
    {
      action: 'reconcile',
      storeMethod: 'reconcileOutlineGeneration',
      prepare() {},
      result: { status: 'succeeded' },
    },
    {
      action: 'confirm',
      storeMethod: 'confirmOutlineDraft',
      prepare() {},
      result: { revision: 1 },
    },
  ]

  for (const entry of cases) {
    let currentProject = 'project-1'
    const pending = deferred()
    const store = storeFixture()
    entry.prepare(store)
    store[entry.storeMethod] = async () => pending.promise
    const controller = createChapterOutlineController({
      store,
      projectId: () => currentProject,
      keyFactory: () => 'outline-operation-key',
    })
    controller.enterProject(currentProject)

    const operation = controller[entry.action]()
    currentProject = 'project-2'
    controller.enterProject(currentProject)
    pending.resolve(entry.result)
    await operation

    assert.equal(controller.notice.value, '', entry.action)
  }
})
